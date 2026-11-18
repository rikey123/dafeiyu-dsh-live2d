"""Chinese short acknowledgement policy using Pipecat's turn-start lifecycle."""

import unicodedata
from dataclasses import dataclass, field

from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame, InterimTranscriptionFrame, TranscriptionFrame, UserBackchannelFrame, VADUserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.turns.user_start.base_user_turn_start_strategy import BaseUserTurnStartStrategy
from pipecat.frames.frames import SystemFrame


@dataclass
class ModelInterruptFrame(SystemFrame):
    """A decision about the current live utterance, never a fake transcript."""
    guard: dict = field(default_factory=dict)


ACKNOWLEDGEMENTS = {"嗯", "嗯嗯", "哦", "噢", "啊", "对", "是", "好的", "好", "是的", "对的", "没错", "明白", "知道了"}


def is_backchannel(text: str) -> bool:
    normalized = "".join(char for char in text if not char.isspace() and not unicodedata.category(char).startswith("P"))
    if not normalized:
        return True
    if len(normalized) > 8:
        return False
    # Recognize combinations like 对，好的 without suppressing longer requests.
    while normalized:
        match = next((item for item in sorted(ACKNOWLEDGEMENTS, key=len, reverse=True) if normalized.startswith(item)), None)
        if not match:
            return False
        normalized = normalized[len(match):]
    return True


class ChineseTurnStartStrategy(BaseUserTurnStartStrategy):
    """Start on a stable meaningful interim or confirmed final text."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot_speaking = False
        self.overlap_at_start = False
        self.started_early = False

    async def process_frame(self, frame: Frame):
        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self.overlap_at_start = self.bot_speaking
            self.started_early = False
        elif isinstance(frame, ModelInterruptFrame):
            if frame.guard.get("active") and self.overlap_at_start and not self.started_early:
                self.started_early = True
                await self.report_user_turn_started()
        elif isinstance(frame, InterimTranscriptionFrame):
            guard = frame.metadata.get("_preview_guard")
            if guard is not None and (not guard.get("active") or guard.get("generation") != frame.metadata.get("preview_generation")):
                return
            normalized = "".join(c for c in frame.text if c.isalnum())
            explicit = any(phrase in normalized for phrase in ("暂停", "停下", "别说", "打住", "等一下", "换话题"))
            decision = frame.metadata.get("systemone_interrupt")
            meaningful = decision if type(decision) is bool else not is_backchannel(frame.text) and (explicit or len(normalized) >= 4)
            if self.overlap_at_start and not self.started_early and meaningful:
                self.started_early = True
                await self.report_user_turn_started()
        elif isinstance(frame, TranscriptionFrame):
            backchannel = frame.metadata.get("systemone_backchannel")
            backchannel = backchannel if type(backchannel) is bool else is_backchannel(frame.text)
            if not self.started_early and not (self.overlap_at_start and backchannel):
                await self.report_user_turn_started()
            self.overlap_at_start = False
            self.started_early = False


class ChineseBackchannelFilter(FrameProcessor):
    """Drop overlap acknowledgements before user-context aggregation."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot_speaking = False
        self.overlap_at_start = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame):
            guard = frame.metadata.get("_preview_guard")
            if guard is not None and (not guard.get("active") or guard.get("generation") != frame.metadata.get("preview_generation")):
                return
        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self.overlap_at_start = self.bot_speaking
        if isinstance(frame, TranscriptionFrame):
            overlap = self.overlap_at_start
            self.overlap_at_start = False
            backchannel = frame.metadata.get("systemone_backchannel")
            backchannel = backchannel if type(backchannel) is bool else is_backchannel(frame.text)
            if overlap and backchannel:
                await self.push_frame(UserBackchannelFrame(text=frame.text, user_id=frame.user_id, timestamp=frame.timestamp), direction)
                return
        await self.push_frame(frame, direction)
