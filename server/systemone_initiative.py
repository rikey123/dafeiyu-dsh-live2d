"""Opt-in assistant interjections, separate from user barge-in decisions.

No fake final transcript, user-turn-end signal, discarded microphone input or
permanent prompt/history mutation. A speculative request is valid only while
its original utterance is still live and the assistant is otherwise idle.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
    CancelFrame, DataFrame, EndFrame, ErrorFrame, InputAudioRawFrame, InterruptionFrame,
    InterimTranscriptionFrame, LLMContextFrame, LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, OutputTransportMessageUrgentFrame,
    TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame
from pipecat.processors.frameworks.rtvi.models import ServerMessage

from speech.pipecat_turns import is_backchannel
from .systemone import INITIATIVE_INTENTS, InitiativeDecision


def asks_to_finish(text):
    normalized = "".join(char for char in text if char.isalnum())
    return any(phrase in normalized for phrase in (
        "不要打断", "别打断", "不许打断", "不要插话", "别插话", "听我说完",
        "让我说完", "等我说完", "先别说话", "不要说话", "别说话"))


@dataclass
class LiveSpeech:
    active: bool = True
    blocked: bool = False
    used: bool = False
    attempts: int = 0
    samples: int = 0
    next_sample: int = 0
    pcm: bytearray = field(default_factory=bytearray)
    preview: str = ""
    preview_at: float = 0


@dataclass
class InitiativeRequestFrame(DataFrame):
    speech: LiveSpeech
    text: str
    decision: InitiativeDecision
    deadline: float


class SystemOneInitiative(FrameProcessor):
    """Listen without blocking, with bounded probes and one reply/utterance."""
    def __init__(self, client, context, transcribe, settings, *, clock=time.monotonic, **kwargs):
        super().__init__(**kwargs)
        self.client, self.context, self.transcribe = client, context, transcribe
        self.clock = clock
        self.enabled = (settings.get("systemone_enabled", False)
            and settings.get("systemone_initiative_enabled", False)
            and settings.get("conversation_mode", "duplex") == "duplex"
            and not settings.get("owner_voice_only", False))
        self.capture_active = False
        self.threshold = settings.get("systemone_initiative_threshold", .9)
        self.min_samples = settings.get("systemone_initiative_min_speech_ms", 3000) * 16
        self.cooldown = settings.get("systemone_initiative_cooldown_s", 20)
        self.wait_threshold = settings.get("systemone_initiative_wait_threshold", .2)
        self.max_reply_chars = settings.get("systemone_initiative_max_reply_chars", 48)
        self.probe_interval_samples = settings.get("systemone_initiative_probe_interval_ms", 3000) * 16
        self.max_probes = settings.get("systemone_initiative_max_probes", 3)
        self.last_spoke = float("-inf")
        self.current = None
        self.task = None
        self.tasks = set()
        self.bot_speaking = False
        self.generating = False
        self.pending_generation = False
        self.initiative_reply = False
        self.playback_busy = lambda: False

    def count(self, name):
        if self.client.metrics:
            self.client.metrics.increment(f"systemone_initiative_{name}")

    def busy(self):
        return self.bot_speaking or self.generating or self.pending_generation or self.playback_busy()

    def live(self, speech, deadline=None):
        return (self.enabled and self.capture_active and speech is self.current and speech.active and not speech.blocked
            and (deadline is None or self.clock() <= deadline))

    def valid(self, speech, deadline=None):
        return (self.live(speech, deadline) and not speech.used and not self.busy()
            and self.clock() - self.last_spoke >= self.cooldown)

    def cancel_pending(self):
        if self.current:
            self.current.active = False
            self.current.pcm.clear()
        for task in self.tasks:
            task.cancel()

    async def set_capture_active(self, active):
        self.capture_active = active
        if not active:
            self.cancel_pending()
            if self.initiative_reply:
                self.initiative_reply = False
                await self.broadcast_interruption()

    def observe(self, frame):
        # Called once per original push by the pipeline observer, including LLM
        # frames which do not travel backwards through this input processor.
        if isinstance(frame, LLMFullResponseStartFrame):
            self.generating = True
            self.pending_generation = False
        elif isinstance(frame, LLMFullResponseEndFrame):
            self.generating = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self.initiative_reply = False
        elif isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self.cancel_pending()
            self.generating = self.pending_generation = False
            self.initiative_reply = False
        elif isinstance(frame, ErrorFrame):
            self.pending_generation = False

    async def notify(self, status, reason, decision=None):
        data = {"type": "voice.initiative", "status": status, "reason": reason,
                "source": self.client.source, "model": self.client.model}
        if decision:
            data.update(desire=decision.desire, intent=decision.intent)
        await self.push_frame(OutputTransportMessageUrgentFrame(
            message=ServerMessage(data=data).model_dump(exclude_none=False)))

    async def assess_live(self, speech, pcm, preview):
        # Both local recognition and cloud inference are speculative. Normal
        # final recognition runs independently and can invalidate either task.
        deadline = self.clock() + 4
        self.count("probes")
        text = preview or await self.transcribe(pcm)
        if not self.valid(speech, deadline):
            return
        if not text or is_backchannel(text) or len("".join(c for c in text if c.isalnum())) < 4:
            self.count("wait")
            await self.notify("waiting", "no_usable_speech")
            return
        if asks_to_finish(text):
            speech.blocked = True
            self.count("wait")
            await self.notify("waiting", "respect_floor")
            return
        result = await self.client.initiative(text, pcm, self.context())
        if not self.valid(speech, deadline):
            return
        if result is None:
            self.count("unavailable")
            await self.notify("unavailable", self.client.last_reason)
        elif (result.desire < self.threshold or result.must_wait > self.wait_threshold
                or result.intent not in INITIATIVE_INTENTS or result.intent == "wait"):
            self.count("wait")
            reason = "respect_floor" if result.must_wait > self.wait_threshold else "low_desire" if result.desire < self.threshold else "low_confidence"
            await self.notify("waiting", reason, result)
        else:
            # Rechecked when this queued DataFrame actually reaches the LLM gate.
            await self.push_frame(InitiativeRequestFrame(speech, text[:1000], result, deadline))

    async def cleanup(self):
        self.cancel_pending()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await super().cleanup()

    def task_done(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.count("unavailable")
            logging.getLogger("dafeiyu").error("Assistant initiative task failed (%s)", type(error).__name__)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            cancel_unheard = self.initiative_reply and not self.bot_speaking
            self.cancel_pending()
            if cancel_unheard:
                # Don't let a slow speculative LLM/TTS start talking after the
                # user has finished. Their final transcript gets the normal reply.
                self.initiative_reply = False
                await self.broadcast_interruption()
        elif isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self.cancel_pending()
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self.cancel_pending()
            self.current = LiveSpeech(blocked=self.busy(), next_sample=self.min_samples)
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, (TranscriptionFrame, RTVISendTextFrame)):
            self.cancel_pending()
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, InterimTranscriptionFrame):
            guard = frame.metadata.get("_preview_guard")
            valid = guard is None or (guard.get("active") and guard.get("generation") == frame.metadata.get("preview_generation"))
            if valid and self.current and self.current.active:
                self.current.preview, self.current.preview_at = frame.text[:1000], self.clock()
                if asks_to_finish(frame.text):
                    self.current.blocked = True
                    for task in self.tasks:
                        task.cancel()
                    if self.initiative_reply:
                        self.initiative_reply = False
                        await self.broadcast_interruption()
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, InputAudioRawFrame):
            speech = self.current
            if speech and self.valid(speech):
                if frame.sample_rate == 16000 and frame.num_channels == 1 and len(frame.audio) % 2 == 0:
                    speech.samples += len(frame.audio) // 2
                    speech.pcm.extend(frame.audio)
                    del speech.pcm[:-128000]
                    if speech.samples >= speech.next_sample and speech.attempts < self.max_probes and not self.tasks:
                        speech.attempts += 1
                        speech.next_sample = speech.samples + self.probe_interval_samples
                        preview = speech.preview if self.clock() - speech.preview_at <= 1 else ""
                        task = asyncio.create_task(self.assess_live(speech, bytes(speech.pcm), preview), name="systemone-initiative")
                        self.task = task
                        self.tasks.add(task)
                        task.add_done_callback(self.task_done)
        await self.push_frame(frame, direction)


class InitiativeSpeechLimit(FrameProcessor):
    """Track the initiative response lifecycle without changing its text."""
    def __init__(self, max_chars=48, **kwargs):
        super().__init__(**kwargs)
        self.armed = False
        self.max_chars = max_chars

    def arm(self):
        self.armed = True

    def disarm(self):
        self.armed = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, EndFrame, CancelFrame, LLMFullResponseEndFrame)):
            self.disarm()
        await self.push_frame(frame, direction)


class InitiativeReplyGate(FrameProcessor):
    """Runs after ConfirmedContext; transient partial text never enters history."""
    def __init__(self, controller, snapshot, limiter, **kwargs):
        super().__init__(**kwargs)
        self.controller, self.snapshot, self.limiter = controller, snapshot, limiter

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        control = self.controller
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, InitiativeRequestFrame):
            if not control.valid(frame.speech, frame.deadline):
                control.count("stale")
                return
            frame.speech.used = True
            frame.speech.pcm.clear()
            control.last_spoke = control.clock()
            control.pending_generation = True
            control.initiative_reply = True
            control.count("accepted")
            self.limiter.arm()
            instruction = (
                "用户仍在说话。现在只作一次简短主动接话，不要接管话题。"
                f"接话目的：{INITIATIVE_INTENTS[frame.decision.intent]}。"
                f"尽量简短，约{self.limiter.max_chars}字，并保持意思完整；澄清时尽量只问一个问题，然后把话语权交还用户。"
                "末条用户消息是本机识别的发言片段，不是完整问题，不要替用户续写，不假装听到了尚未说出的内容。")
            messages = [*self.snapshot()]
            # Keep one leading system message for DeepSeek-compatible providers;
            # copy, never mutate the persisted persona or shared aggregator context.
            if messages and messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
                messages[0] = {**messages[0], "content": messages[0]["content"] + "\n\n" + instruction}
            else:
                messages.insert(0, {"role": "system", "content": instruction})
            messages.append({"role": "user", "content": frame.text})
            await control.notify("accepted", "strong_desire", frame.decision)
            if not control.live(frame.speech, frame.deadline):
                # The urgent diagnostic push can yield to a stop/capture-off.
                # Never resurrect a speculative reply after that cancellation.
                if control.initiative_reply:
                    control.initiative_reply = control.pending_generation = False
                self.limiter.disarm()
                control.count("stale")
                return
            await self.push_frame(LLMContextFrame(LLMContext(messages=messages)), direction)
            return
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            control.cancel_pending()
            control.pending_generation = True
            control.initiative_reply = False
            self.limiter.disarm()
        await self.push_frame(frame, direction)
