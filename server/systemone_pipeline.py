"""Optional decisions around the existing Pipecat ASR / LLM / TTS pipeline."""
from __future__ import annotations

import asyncio
from collections import OrderedDict

from pipecat.frames.frames import (AggregatedTextFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
    CancelFrame, EndFrame, InputAudioRawFrame, InterruptionFrame, InterimTranscriptionFrame,
    LLMFullResponseStartFrame, OutputTransportMessageUrgentFrame, TranscriptionFrame, TTSTextFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.models import ServerMessage
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame
from speech.pipecat_turns import ModelInterruptFrame


class SystemOneInput(FrameProcessor):
    def __init__(self, client, context, *, owner_only=False, **kwargs):
        super().__init__(**kwargs)
        self.client, self.context, self.owner_only = client, context, owner_only
        self.bot_speaking = False
        self.records = OrderedDict()
        self.current = None
        self.task = None
        self.final_task = None
        self.revision = 0

    def cancel_early(self):
        if self.task:
            self.task.cancel()
        if self.current:
            self.current["guard"]["active"] = False

    async def cleanup(self):
        self.cancel_early()
        tasks = [task for task in (self.task, self.final_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.records.clear()
        await super().cleanup()

    async def early(self, record, text="", pcm=None):
        result = await self.client.turn(text, pcm, self.context(), True)
        if record["guard"]["active"] and record is self.current and not record["interrupted"]:
            preview = record.get("preview")
            if result and result.interrupt >= self.client.threshold and result.backchannel < .5:
                record["interrupted"] = True
                self.client.user_emotion = result.emotion
                await self.push_frame(ModelInterruptFrame(guard=record["guard"]))
            elif preview and (result is None or result.backchannel < self.client.threshold):
                fallback = InterimTranscriptionFrame(text=preview.text, user_id=preview.user_id, timestamp=preview.timestamp)
                fallback.metadata.update(preview.metadata)
                fallback.metadata.pop("systemone_interrupt", None)
                await self.push_frame(fallback)

    def schedule(self, record, text="", pcm=None):
        if record["attempts"] >= 2 or record["interrupted"] or self.task and not self.task.done():
            return False
        record["attempts"] += 1
        self.task = asyncio.create_task(self.early(record, text, pcm), name="systemone-live-turn")
        return True

    async def remember_affect(self, text, pcm, revision):
        result = await self.client.turn(text, pcm, self.context(), False)
        if result and revision == self.revision:
            self.client.user_emotion = result.emotion

    def new_input(self):
        self.revision += 1
        self.client.user_emotion = None
        if self.final_task:
            self.final_task.cancel()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self.cancel_early()
        elif isinstance(frame, (InterruptionFrame, EndFrame, CancelFrame)):
            self.cancel_early()
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self.cancel_early()
            self.new_input()
            # VAD travels upstream: this processor sees it before STT stamps
            # its segment number. Keep the shared metadata reference, not a
            # snapshot of a field that may not exist yet.
            record = {"guard": {"active": True}, "source": frame.metadata, "overlap": self.bot_speaking, "pcm": bytearray(), "attempts": 0, "interrupted": False}
            self.current = record
            self.records[self.revision] = record
            while len(self.records) > 8:
                self.records.popitem(last=False)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.cancel_early()
        elif isinstance(frame, RTVISendTextFrame):
            self.new_input()
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, InputAudioRawFrame):
            record = self.current
            if (record and record["guard"]["active"] and record["overlap"] and not self.owner_only
                    and self.client.audio_enabled and frame.sample_rate == 16000 and frame.num_channels == 1):
                record["pcm"].extend(frame.audio)
                del record["pcm"][:-128000]
                trigger = 20800 if record["attempts"] == 0 else 57600
                if len(record["pcm"]) >= trigger:
                    self.schedule(record, pcm=bytes(record["pcm"]))
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, InterimTranscriptionFrame):
            record = self.current
            preview_guard = frame.metadata.get("_preview_guard")
            valid = preview_guard is None or (preview_guard.get("active") and preview_guard.get("generation") == frame.metadata.get("preview_generation"))
            if record and record["guard"]["active"] and record["overlap"] and not self.owner_only and valid:
                # Optional online text can also ask the model; audio decisions do
                # not require an online ASR model. Final fallback remains intact.
                record["preview"] = frame
                scheduled = self.schedule(record, text=frame.text)
                if scheduled or self.task and not self.task.done():
                    frame.metadata["systemone_interrupt"] = False
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame):
            segment = frame.metadata.get("systemone_segment")
            key = next((key for key, item in self.records.items() if segment is not None and item["source"].get("systemone_segment") == segment), None)
            record = self.records.pop(key, None)
            pcm = frame.metadata.pop("systemone_pcm", None)
            # Earlier queued ASR segments must not drive the new live utterance.
            current = record is self.current or record is None and self.current is None
            if current:
                self.cancel_early()
                if record and record["interrupted"]:
                    frame.metadata["systemone_backchannel"] = False
                elif not record or not record["overlap"]:
                    # A normal user turn needs no interruption gate. Its affect
                    # can be inferred alongside DeepSeek instead of delaying it.
                    self.final_task = asyncio.create_task(self.remember_affect(frame.text, pcm, self.revision))
                else:
                    self.final_task = asyncio.create_task(self.client.turn(frame.text, pcm, self.context(), bool(record and record["overlap"])))
                    try:
                        result = await self.final_task
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        result = None
                    if result and (record is self.current or record is None and self.current is None):
                        self.client.user_emotion = result.emotion
                        if record and record["overlap"]:
                            if result.interrupt >= self.client.threshold:
                                frame.metadata["systemone_backchannel"] = False
                            elif result.backchannel >= self.client.threshold and result.interrupt < .5:
                                frame.metadata["systemone_backchannel"] = True
                            elif result.backchannel <= 1 - self.client.threshold:
                                frame.metadata["systemone_backchannel"] = False
                if record:
                    record["pcm"].clear()
        await self.push_frame(frame, direction)


class SystemOneAffect(FrameProcessor):
    def __init__(self, client, context, **kwargs):
        super().__init__(**kwargs)
        self.client, self.context = client, context
        self.tasks = set()
        self.generation = 0
        self.count = 0

    def cancel_pending(self):
        self.generation += 1
        for task in self.tasks:
            task.cancel()

    async def cleanup(self):
        self.cancel_pending()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.close()
        await super().cleanup()

    async def decide(self, epoch, text, generation):
        result = await self.client.affect(text, self.context())
        if generation != self.generation:
            return
        data = {"type": "voice.behavior", "epoch": epoch, "source": self.client.source if result else "rules",
                "model": self.client.model, "behavior": result or {}, "reason": self.client.last_reason}
        await self.push_frame(OutputTransportMessageUrgentFrame(message=ServerMessage(data=data).model_dump(exclude_none=False)))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self.cancel_pending()
        elif isinstance(frame, LLMFullResponseStartFrame):
            self.count = 0
        elif (direction == FrameDirection.DOWNSTREAM and isinstance(frame, AggregatedTextFrame)
              and not isinstance(frame, TTSTextFrame) and frame.will_be_spoken and frame.context_id
              and self.count < 8 and len(self.tasks) < 2):
            self.count += 1
            task = asyncio.create_task(self.decide(frame.context_id, frame.text, self.generation), name="systemone-affect")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        await self.push_frame(frame, direction)
