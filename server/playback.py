"""Conservative, per-connection confirmation of whole TTS output turns."""

from __future__ import annotations

import uuid
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from pipecat.frames.frames import (AggregatedTextFrame, ErrorFrame, Frame, InterruptionFrame, LLMContextFrame, OutputAudioRawFrame,
                                   OutputTransportMessageFrame, TTSStartedFrame, TTSTextFrame, TTSStoppedFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.models import ServerMessage
from pipecat.processors.aggregators.llm_context import LLMContext
from .context import context_messages


@dataclass
class PlaybackTurn:
    epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    samples: int = 0
    text: list[str] = field(default_factory=list)
    boundary: bool = False
    confirmed: bool = False
    interrupted: bool = False
    started_at: float = field(default_factory=time.monotonic)
    group: str = ""
    committed: bool = False
    generation_id: str | None = None


class PlaybackLedger:
    def __init__(self, on_confirm, metrics=None, on_begin=None, on_retire=None, on_interrupt=None):
        self.turn: PlaybackTurn | None = None
        self.turns: OrderedDict[str, PlaybackTurn] = OrderedDict()
        self.group = uuid.uuid4().hex
        self.generation_id = None
        self.group_prefix: OrderedDict[str, str] = OrderedDict()
        self.epoch_groups: dict[str, str] = {}
        self.on_confirm = on_confirm
        self.on_begin = on_begin
        self.on_retire = on_retire
        self.on_interrupt = on_interrupt
        self.interrupted_groups = set()
        self.closed_groups: set[str] = set()
        self.metrics = metrics
        self.confirmed_text: list[str] = []
        self.generating_epoch: str | None = None
        self.failed_epochs: set[str] = set()
        self.generation_failed = False

    def begin_generation(self, generation_id=None):
        self.closed_groups.add(self.group)
        self._retire()
        self.group = generation_id or uuid.uuid4().hex
        self.generation_id = generation_id
        self.group_prefix[self.group] = ""
        self.generation_failed = False
        if self.on_begin:
            self.on_begin(self.group)

    def generating(self, epoch, group=None):
        self.generating_epoch = epoch
        if len(self.epoch_groups) < 128:
            self.epoch_groups[epoch] = group or self.group
        else:
            self.generation_failed = True
        if self.generation_failed:
            self.failed_epochs.add(epoch)

    def fail_generation(self, context_id=None):
        if context_id:
            if len(self.failed_epochs) < 128:
                self.failed_epochs.add(context_id)
            else:
                self.generation_failed = True
            if context_id in self.turns:
                self.turns[context_id].interrupted = True
            return
        self.generation_failed = True
        if self.generating_epoch:
            self.failed_epochs.add(self.generating_epoch)
            if self.turn and self.turn.epoch == self.generating_epoch:
                self.turn.interrupted = True

    def start(self, epoch=None):
        epoch = epoch or uuid.uuid4().hex
        if epoch in self.turns:
            return self.turns[epoch]
        if len(self.turns) >= 128:
            self.turn = PlaybackTurn(epoch=epoch, interrupted=True, group=self.group)
            return self.turn
        self.turn = PlaybackTurn(epoch=epoch, group=self.epoch_groups.get(epoch, self.group))
        self.turn.interrupted = self.turn.epoch in self.failed_epochs
        self.turns[epoch] = self.turn
        return self.turn

    def interrupt(self):
        if self.on_interrupt:
            groups = {turn.group for turn in self.turns.values() if not turn.confirmed and not turn.interrupted}
            groups.update(self.epoch_groups.values())
            if self.group in self.group_prefix:
                groups.add(self.group)
            for group in groups - self.interrupted_groups:
                self.interrupted_groups.add(group)
                self.on_interrupt(group, self.group_prefix.get(group, ""))
        for turn in self.turns.values():
            if not turn.confirmed:
                turn.interrupted = True
        for epoch in list(self.epoch_groups):
            if epoch not in self.turns:
                self.failed_epochs.add(epoch)
                self.epoch_groups.pop(epoch, None)
        self._retire()

    def acknowledge(self, data):
        turn = self.turns.get(data.get("epoch")) if isinstance(data, dict) and isinstance(data.get("epoch"), str) else None
        if not isinstance(data, dict) or not turn or turn.interrupted or turn.confirmed or not turn.boundary:
            return False
        samples = data.get("consumed_samples")
        if (data.get("epoch") != turn.epoch or data.get("completed") is not True
                or type(samples) is not int or samples != turn.samples
                or type(data.get("sample_rate")) is not int or data["sample_rate"] != 24000):
            return False
        turn.confirmed = True
        if self.metrics:
            self.metrics.increment("playback_completed")
            self.metrics.add("playback.completion", time.monotonic() - turn.started_at)
        self._commit_prefix(turn.group)
        self._retire()
        return True

    def _retire(self):
        for group in tuple(self.closed_groups):
            items = [turn for turn in self.turns.values() if turn.group == group]
            if any(epoch not in self.turns for epoch, owner in self.epoch_groups.items() if owner == group):
                continue
            if any(not turn.confirmed and not turn.interrupted for turn in items):
                continue
            for turn in items:
                self.turns.pop(turn.epoch, None)
                self.epoch_groups.pop(turn.epoch, None)
                self.failed_epochs.discard(turn.epoch)
            self.closed_groups.discard(group)
            self.interrupted_groups.discard(group)
            if not self.group_prefix.get(group):
                self.group_prefix.pop(group, None)
            if self.on_retire:
                self.on_retire(group)

    def _commit_prefix(self, group):
        prefix = self.group_prefix.get(group, "")
        committed = []
        for item in self.turns.values():
            if item.group != group:
                continue
            if not item.confirmed or item.interrupted:
                break
            prefix += "".join(item.text)
            committed.append(item.epoch)
        if prefix and prefix != self.group_prefix.get(group):
            self.group_prefix[group] = prefix
            while len(self.group_prefix) > 128:
                self.group_prefix.popitem(last=False)
            self.confirmed_text = [value for value in self.group_prefix.values() if value]
            self.on_confirm(group, prefix)
        for epoch in committed:
            self.turns.pop(epoch, None)
            self.epoch_groups.pop(epoch, None)
            self.failed_epochs.discard(epoch)


def server_message(data):
    return OutputTransportMessageFrame(message=ServerMessage(data=data).model_dump(exclude_none=False))


class ConfirmedContext(FrameProcessor):
    """Keep generated assistant messages out of future prompts until acknowledged."""
    def __init__(self, ledger, initial_messages, snapshot=None):
        super().__init__()
        self.ledger = ledger
        self.initial_ids = {id(message) for message in initial_messages}
        self.snapshot = snapshot

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            if self.snapshot is not None:
                frame = LLMContextFrame(LLMContext(messages=self.snapshot(), tools=frame.context.tools,
                                                   tool_choice=frame.context.tool_choice))
                await self.push_frame(frame, direction)
                return
            messages = frame.context.messages
            if len(messages) > 161:
                system = [message for message in messages[:1] if isinstance(message, dict) and message.get("role") == "system"]
                frame.context.set_messages(system + messages[-160:])
            remaining = list(self.ledger.confirmed_text)
            kept = []
            for message in frame.context.messages:
                if not isinstance(message, dict) or message.get("role") != "assistant" or id(message) in self.initial_ids:
                    kept.append(message)
                elif isinstance(message.get("content"), str):
                    match = next((text for text in remaining if message["content"].startswith(text)), None)
                    if match:
                        remaining.remove(match)
                        kept.append({**message, "content": match})
            if kept and isinstance(kept[0], dict) and kept[0].get("role") == "system":
                history = [message for message in kept[1:] if isinstance(message, dict) and message.get("role") in {"user", "assistant"} and isinstance(message.get("content"), str)]
                kept = context_messages({"system_prompt": kept[0]["content"]}, [], history)
            frame = LLMContextFrame(LLMContext(messages=kept, tools=frame.context.tools,
                                               tool_choice=frame.context.tool_choice))
        await self.push_frame(frame, direction)


class PlaybackStart(FrameProcessor):
    def __init__(self, ledger):
        super().__init__()
        self.ledger = ledger
        self.started = False
        self.pending_text: OrderedDict[str, str] = OrderedDict()
        self.active_epoch = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, InterruptionFrame):
                self.ledger.interrupt()
                self.started = False
                self.active_epoch = None
                self.pending_text.clear()
            elif isinstance(frame, AggregatedTextFrame) and not isinstance(frame, TTSTextFrame) and frame.will_be_spoken and frame.context_id:
                self.pending_text[frame.context_id] = frame.text
                while len(self.pending_text) > 128:
                    self.pending_text.popitem(last=False)
            elif isinstance(frame, (TTSStartedFrame, OutputAudioRawFrame)) and not self.started:
                epoch = getattr(frame, "context_id", None) or uuid.uuid4().hex
                group = frame.metadata.get("playback_group_id") or frame.metadata.get("generation_id")
                self.ledger.generating(epoch, group)
                self.started = True
                self.active_epoch = epoch
                start = {"type": "voice.playback.start", "epoch": epoch, "sample_rate": 24000,
                         "text": self.pending_text.pop(epoch, "")}
                generation_id = frame.metadata.get("generation_id")
                if generation_id is None and not frame.metadata.get("playback_group_id"):
                    generation_id = self.ledger.generation_id
                if generation_id:
                    start["generation_id"] = generation_id
                await self.push_frame(server_message(start))
            if isinstance(frame, TTSStoppedFrame):
                self.started = False
                self.active_epoch = None
        await self.push_frame(frame, direction)


class PlaybackBoundary(FrameProcessor):
    def __init__(self, ledger, rtvi):
        super().__init__()
        self.ledger, self.rtvi = ledger, rtvi
        self.pending_tts_text: OrderedDict[str, list[str]] = OrderedDict()
        self.pending_tts_size = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, InterruptionFrame):
            self.pending_tts_text.clear()
            self.pending_tts_size = 0
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, OutputTransportMessageFrame):
            message = frame.message
            data = message.get("data") if isinstance(message, dict) else None
            if isinstance(data, dict) and data.get("type") == "voice.playback.start":
                turn = self.ledger.start(data["epoch"])
                turn.generation_id = data.get("generation_id")
                pending = self.pending_tts_text.pop(turn.epoch, [])
                self.pending_tts_size -= sum(map(len, pending))
                if not turn.interrupted:
                    turn.text.extend(pending)
                if turn.epoch not in self.ledger.turns:
                    await self.rtvi.send_server_message({"type": "voice.playback.unavailable", "reason": "sentence_limit"})
        turn = self.ledger.turn
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TTSTextFrame) and frame.text:
            epoch = frame.context_id
            target = self.ledger.turns.get(epoch) if epoch else turn
            if target and not target.interrupted:
                target.text.append(frame.text)
            elif epoch and epoch not in self.ledger.failed_epochs:
                if (epoch not in self.pending_tts_text and len(self.pending_tts_text) >= 128) or self.pending_tts_size + len(frame.text) > 8000:
                    self.ledger.fail_generation(epoch)
                    removed = self.pending_tts_text.pop(epoch, [])
                    self.pending_tts_size -= sum(map(len, removed))
                else:
                    self.pending_tts_text.setdefault(epoch, []).append(frame.text)
                    self.pending_tts_size += len(frame.text)
        if direction == FrameDirection.DOWNSTREAM and turn and not turn.interrupted:
            if isinstance(frame, OutputAudioRawFrame):
                if frame.sample_rate != 24000 or frame.num_channels != 1 or len(frame.audio) % 2:
                    turn.interrupted = True
                else:
                    turn.samples += len(frame.audio) // 2
            elif isinstance(frame, TTSStoppedFrame) and turn.samples:
                turn.boundary = True
                message = {"type": "voice.playback.boundary", "epoch": turn.epoch,
                           "samples": turn.samples, "sample_rate": 24000, "text": "".join(turn.text)}
                if turn.generation_id:
                    message["generation_id"] = turn.generation_id
                await self.rtvi.send_server_message(message)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TTSStoppedFrame) and frame.context_id:
            removed = self.pending_tts_text.pop(frame.context_id, [])
            self.pending_tts_size -= sum(map(len, removed))
        await self.push_frame(frame, direction)
