"""Audio interaction policy independent of the language and speech providers."""
from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                  InputAudioRawFrame, InterruptionFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class ConversationInputGate(FrameProcessor):
    """Keep duplex capture live; suppress captured audio during turn-based playback."""
    def __init__(self, mode="duplex", **kwargs):
        super().__init__(**kwargs)
        if mode not in {"pipeline", "duplex"}:
            raise ValueError("invalid conversation mode")
        self.mode = mode
        self.speaking = False

    def observe(self, frame):
        if isinstance(frame, BotStartedSpeakingFrame):
            self.speaking = True
        elif isinstance(frame, (BotStoppedSpeakingFrame, InterruptionFrame)):
            self.speaking = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if (direction == FrameDirection.DOWNSTREAM and self.mode == "pipeline"
                and self.speaking and isinstance(frame, InputAudioRawFrame)):
            # Drain VAD/STT with silence instead of leaving a captured turn open.
            frame.audio = bytes(len(frame.audio))
        await self.push_frame(frame, direction)
