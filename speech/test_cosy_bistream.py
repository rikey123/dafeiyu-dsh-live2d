import asyncio
import json
import hashlib
import httpx

import pytest
import websockets
from pipecat.frames.frames import ErrorFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame
from pipecat.tests.utils import run_test

from speech.cosy_bistream import CosyBistreamTTS


@pytest.mark.asyncio
async def test_token_stream_uses_one_session_and_preserves_audio():
    messages = []
    async def handler(socket):
        messages.append(json.loads(await socket.recv()))
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
        async for raw in socket:
            message = json.loads(raw)
            messages.append(message)
            if message["type"] == "text":
                await socket.send(b"\x01\x00" * 80)
            elif message["type"] == "end":
                await socket.send(json.dumps({"type": "done"}))
                return
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}/v1/tts/bistream")
        downstream, _ = await asyncio.wait_for(run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好"), LLMTextFrame("世界。"), LLMFullResponseEndFrame()]), 10)
    assert [m["type"] for m in messages] == ["init", "text", "text", "end"]
    assert "".join(m["text"] for m in messages if m["type"] == "text") == "你好世界。"
    assert len([f for f in downstream if isinstance(f, TTSAudioRawFrame)]) == 2


@pytest.mark.asyncio
async def test_interrupted_session_closes_and_does_not_reopen_same_context():
    connected = asyncio.Event()
    closed = asyncio.Event()
    calls = []
    async def handler(socket):
        calls.append(1)
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
        connected.set()
        try:
            async for raw in socket:
                if json.loads(raw)["type"] == "cancel":
                    break
        finally:
            closed.set()
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        errors = []
        async def capture(frame):
            errors.append(frame)
        tts.push_error_frame = capture
        tts.audio_context_available = lambda context: context == "ctx"
        assert [f async for f in tts.run_tts("你好", "ctx")] == [None]
        await connected.wait()
        await tts.on_audio_context_interrupted("ctx")
        await asyncio.wait_for(closed.wait(), 2)
        assert [f async for f in tts.run_tts("继续", "ctx")] == []
        await tts.cleanup()
    assert len(calls) == 1
    assert errors == []


@pytest.mark.asyncio
async def test_retired_context_cannot_reopen_after_history_rollover(monkeypatch):
    calls = []
    def connect(*args, **kwargs):
        calls.append(1)
        raise OSError("expected connect attempt")
    monkeypatch.setattr(websockets, "connect", connect)
    tts = CosyBistreamTTS()
    tts.audio_context_available = lambda context: context == "new"
    for index in range(140):
        tts._failed_contexts.append(str(index))
    assert [frame async for frame in tts.run_tts("旧", "0")] == []
    assert not calls
    assert [frame async for frame in tts.run_tts("新", "new")]
    assert len(calls) == 1




@pytest.mark.asyncio
async def test_acknowledged_tokens_are_sent_one_at_a_time():
    received = []
    async def handler(socket):
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "text_ack": True}))
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "text":
                received.append(message["text"])
                await socket.send(json.dumps({"type": "text_ack", "sequence": len(received)}))
                await socket.send(b"\0\0" * 20)
            elif message["type"] == "end":
                await socket.send(json.dumps({"type": "done"}))
                return
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        downstream, _ = await asyncio.wait_for(run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好"), LLMTextFrame("世界。"), LLMFullResponseEndFrame()]), 10)
    assert received == ["你好", "世界。"]
    assert len([frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]) == 2


@pytest.mark.asyncio
async def test_cancellation_unblocks_pending_ack():
    started = asyncio.Event()
    async def handler(socket):
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "text_ack": True}))
        await socket.recv()
        started.set()
        await socket.wait_closed()
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        tts.audio_context_available = lambda context: True
        async def send():
            return [frame async for frame in tts.run_tts("你好", "ctx")]
        task = asyncio.create_task(send())
        await asyncio.wait_for(started.wait(), 2)
        await tts.on_audio_context_interrupted("ctx")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        await tts.cleanup()


@pytest.mark.asyncio
async def test_done_without_audio_reports_error():
    async def handler(socket):
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
        async for raw in socket:
            if json.loads(raw)["type"] == "end":
                await socket.send(json.dumps({"type": "done"}))
                return
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        downstream, upstream = await asyncio.wait_for(run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好。"), LLMFullResponseEndFrame()]), 10)
    assert any(isinstance(frame, ErrorFrame) and "empty sidecar audio" in frame.error for frame in upstream)
    assert not any(isinstance(frame, TTSAudioRawFrame) for frame in downstream)


@pytest.mark.asyncio
async def test_cold_start_has_separate_budget_and_timeout_is_not_blank():
    async def handler(socket):
        await socket.recv()
        await asyncio.sleep(.1)
        try:
            await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
            await socket.wait_closed()
        except websockets.WebSocketException:
            pass

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        for budget, succeeds in [(.5, True), (.02, False)]:
            tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}", timeout=.02, startup_timeout=budget)
            tts.audio_context_available = lambda context: True
            frames = [frame async for frame in tts.run_tts("hello", "ctx")]
            if succeeds:
                assert frames == [None]
            else:
                assert any(isinstance(frame, ErrorFrame) and "TimeoutError" in frame.error for frame in frames)
            await tts.cleanup()


@pytest.mark.asyncio
async def test_busy_during_previous_turn_cleanup_retries_then_succeeds():
    calls = []
    async def handler(socket):
        calls.append(1)
        if len(calls) <= 2:
            await socket.send(json.dumps({"type": "error", "reason": "busy"}))
            return
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "text":
                await socket.send(b"\x01\x00" * 80)
            elif message["type"] == "end":
                await socket.send(json.dumps({"type": "done"}))
                return
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        downstream, upstream = await asyncio.wait_for(run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("hello"), LLMFullResponseEndFrame()]), 10)
    assert len(calls) == 3
    assert any(isinstance(frame, TTSAudioRawFrame) for frame in downstream)
    assert not any(isinstance(frame, ErrorFrame) for frame in upstream)


@pytest.mark.asyncio
async def test_unexpected_peer_close_still_reports_error():
    async def handler(socket):
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}))
        await socket.recv()
        await socket.close()
    errors = []
    async def capture(frame):
        errors.append(frame)
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        tts.push_error_frame = capture
        tts.audio_context_available = lambda _: True
        assert [frame async for frame in tts.run_tts("hello", "ctx")] == [None]
        reader = tts._reader
        tts.audio_context_available = lambda _: False
        await asyncio.wait_for(reader, 2)
        await tts.cleanup()
    assert len(errors) == 1 and "1000" in errors[0].error


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", [False, True])
async def test_interrupt_during_startup_or_busy_wait_does_not_reopen(busy):
    started = asyncio.Event()
    calls, errors = [], []
    async def handler(socket):
        calls.append(1)
        await socket.recv()
        if busy:
            await socket.send(json.dumps({"type": "error", "reason": "busy"}))
        started.set()
        await socket.wait_closed()
    async def capture(frame):
        errors.append(frame)
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}", startup_timeout=.2)
        tts.audio_context_available = lambda _: True
        tts.push_error_frame = capture
        async def send():
            return [frame async for frame in tts.run_tts("hello", "ctx")]
        task = asyncio.create_task(send())
        await asyncio.wait_for(started.wait(), 2)
        await tts.on_audio_context_interrupted("ctx")
        assert await asyncio.wait_for(task, 2) == []
        await tts.cleanup()
    assert len(calls) == 1 and not errors


@pytest.mark.asyncio
async def test_gpu_mode_rejects_cpu_sidecar_before_sending_text():
    messages = []
    async def handler(socket):
        messages.append(json.loads(await socket.recv()))
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "device": "cpu"}))
        async for raw in socket:
            messages.append(json.loads(raw))
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        service = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}", require_cuda=True)
        service.audio_context_available = lambda _context: True
        frames = [frame async for frame in service.run_tts("text", "ctx")]
        assert any(isinstance(frame, ErrorFrame) and "CUDA" in frame.error for frame in frames)
        await service.cleanup()
    assert not any(message["type"] == "text" for message in messages)
