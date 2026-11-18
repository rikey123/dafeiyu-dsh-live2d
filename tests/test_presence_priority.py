from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import LLMFullResponseStartFrame
from pipecat.processors.frame_processor import FrameDirection

from server.screen_voice import IdleRequestFrame, ScreenReplyGate, ScreenVoice
from server.storage import DEFAULTS


@pytest.mark.asyncio
async def test_queued_idle_reply_rechecks_playback_busy():
    screen = ScreenVoice(None, {**DEFAULTS, 'idle_companion_enabled': True}, lambda: (),
                         notify=AsyncMock(), native_context=AsyncMock())
    gate = ScreenReplyGate(screen, lambda: [])
    gate.push_frame = AsyncMock()
    screen.pending_reply = True
    screen.idle.deadline = screen.idle.clock() + 10
    screen.playback_busy = lambda: True
    try:
        await gate.process_frame(IdleRequestFrame(None, screen.idle.generation, None), FrameDirection.DOWNSTREAM)
        gate.push_frame.assert_not_awaited()
        assert not screen.pending_reply
    finally:
        await screen.cleanup()


@pytest.mark.asyncio
async def test_native_async_output_invalidates_idle_but_own_output_does_not():
    screen = ScreenVoice(None, DEFAULTS, lambda: (), notify=AsyncMock(), native_context=AsyncMock())
    try:
        before = screen.idle.generation
        own = LLMFullResponseStartFrame()
        own.metadata['kind'] = 'idle'
        screen.observe(own)
        assert screen.idle.generation == before
        normal = LLMFullResponseStartFrame()
        normal.metadata['kind'] = 'normal'
        screen.observe(normal)
        assert screen.idle.generation > before
        assert screen.generating
    finally:
        await screen.cleanup()
