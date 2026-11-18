"""Native wire-protocol tests use loopback WebSockets, never a paid account."""
import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import websockets
from pipecat.frames.frames import (ErrorFrame, LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame, TTSStoppedFrame)
from websockets.http11 import Response
from websockets.datastructures import Headers

from speech.deepseek_tts import DeepSeekSpeechTTS, _text_message, websocket_url


def service_for(server, **kwargs):
    return DeepSeekSpeechTTS(base_url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1",
                             api_key="private-test-secret", **kwargs)


async def finish(ws, code="success"):
    await ws.send(json.dumps({"event": "finish", "code": code, "message": "private-test-secret remote text"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("voice,filter_markdown", [("stella", True), ("tide", False)])
async def test_real_socket_contract_streams_without_waiting_for_finish(voice, filter_markdown):
    seen, messages = [], []
    first_audio_seen = asyncio.Event()

    async def handler(ws):
        seen.append(ws.request)
        messages.extend([json.loads(await ws.recv()), json.loads(await ws.recv())])
        for chunk in [b"\x01", b"\x02\x03", b"\x04"]:
            await ws.send(chunk)
        await asyncio.wait_for(first_audio_seen.wait(), 2)
        await finish(ws)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server, voice=voice, filter_markdown=filter_markdown)
        frames = []
        async for frame in service.run_tts("你好 DeepSeek", "ctx"):
            frames.append(frame)
            if isinstance(frame, TTSAudioRawFrame):
                first_audio_seen.set()
        await service.cleanup()
    assert all(isinstance(frame, TTSAudioRawFrame) for frame in frames)
    assert b"".join(f.audio for f in frames) == b"\x01\x02\x03\x04"
    assert all((f.sample_rate, f.num_channels, f.context_id) == (24000, 1, "ctx") for f in frames)
    assert seen[0].headers["authorization"] == "Bearer private-test-secret"
    parts = urlsplit(seen[0].path)
    assert parts.path == "/v1/tools/tts"
    assert parse_qs(parts.query) == {"voice_id": [voice], "format": ["pcm"], "filter_markdown": [str(filter_markdown).lower()]}
    assert messages == [{"event": "text", "text": "你好 DeepSeek"}, {"event": "finish_text"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["invalid_input", "content_filter", "input_timeout", "service_error", "unknown", {"bad": "code"}])
async def test_finish_error_sanitized_no_automatic_retry(code):
    calls = []
    async def handler(ws):
        calls.append(1)
        await ws.recv(); await ws.recv()
        await finish(ws, code)
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(calls) == len(frames) == 1
    assert isinstance(frames[0], ErrorFrame)
    assert "private-test-secret" not in frames[0].error
    assert frames[0].metadata["tts_context_id"] == "ctx"


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [[b""], [b"a"], [b"R", b"I", b"F", b"Fabcdefgh"], [b"OggS1234"], [b"fLaC1234"]])
async def test_empty_odd_and_split_container_audio_rejected_before_playback(chunks):
    async def handler(ws):
        await ws.recv(); await ws.recv()
        for chunk in chunks:
            await ws.send(chunk)
        await finish(ws)
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", [None, "not json", "[]", '{"event":"unknown"}', "x" * 8193])
async def test_partial_audio_requires_explicit_valid_success_and_never_replays(tail):
    calls = []
    async def handler(ws):
        calls.append(1)
        await ws.recv(); await ws.recv()
        await ws.send(b"\x01\x00" * 4800)
        if tail is not None:
            await ws.send(tail)
        await ws.close()
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(calls) == 1
    assert isinstance(frames[-1], ErrorFrame)
    assert len([f for f in frames if isinstance(f, TTSAudioRawFrame)]) == 2
    assert all(len(f.audio) <= 4800 for f in frames if isinstance(f, TTSAudioRawFrame))


@pytest.mark.asyncio
@pytest.mark.parametrize("after_audio", [False, True])
async def test_total_deadline_even_after_yield_closes_connection(after_audio):
    closed = asyncio.Event()
    async def handler(ws):
        await ws.recv(); await ws.recv()
        if after_audio:
            await ws.send(b"\x01\x00" * 2400)
        await ws.wait_closed()
        closed.set()
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server, timeout=0.1)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await asyncio.wait_for(closed.wait(), 2)
        await service.cleanup()
    assert isinstance(frames[-1], ErrorFrame) and "超时" in frames[-1].error
    assert any(isinstance(f, TTSAudioRawFrame) for f in frames) == after_audio


@pytest.mark.asyncio
async def test_spoken_interruption_closes_socket_without_error_or_reconnect():
    started, closed = asyncio.Event(), asyncio.Event()
    calls = []
    async def handler(ws):
        calls.append(1)
        await ws.recv(); await ws.recv()
        started.set()
        await ws.wait_closed()
        closed.set()
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        async def consume():
            return [f async for f in service.run_tts("test", "ctx")]
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 2)
        await service.on_audio_context_interrupted("ctx")
        assert await asyncio.wait_for(task, 2) == []
        await asyncio.wait_for(closed.wait(), 2)
        await service.cleanup()
    assert calls == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 503, 504])
async def test_upgrade_http_failures_redacted_and_never_retried(status):
    calls = []
    async def reject(connection, request):
        calls.append(1)
        return Response(status, "Denied", Headers(), b"private-test-secret upstream body")
    async with websockets.serve(lambda ws: ws.wait_closed(), "127.0.0.1", 0, process_request=reject) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(calls) == len(frames) == 1
    assert isinstance(frames[0], ErrorFrame)
    assert str(status) in frames[0].error and "private-test-secret" not in frames[0].error


@pytest.mark.asyncio
async def test_redirect_never_sends_bearer_to_second_socket():
    calls = []
    async def reject(connection, request):
        calls.append(request.path)
        return Response(307, "Redirect", Headers({"Location": "/stolen"}), b"")
    async with websockets.serve(lambda ws: ws.wait_closed(), "127.0.0.1", 0, process_request=reject) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(calls) == 1 and "/stolen" not in calls
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)


@pytest.mark.asyncio
async def test_pcm_limit_is_bounded_without_retry(monkeypatch):
    monkeypatch.setattr("speech.deepseek_tts.MAX_PCM_BYTES", 8)
    async def handler(ws):
        await ws.recv(); await ws.recv()
        await ws.send(b"\x01\x00" * 10)
        await finish(ws)
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        frames = [f async for f in service.run_tts("test", "ctx")]
        await service.cleanup()
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)


@pytest.mark.asyncio
async def test_invalid_input_and_missing_key_do_not_open_socket(monkeypatch):
    def fail():
        raise AssertionError("must not open socket")
    for text, voice, key in [("", "stella", "key"), ("你" * 5001, "stella", "key"), ("你好", "unknown", "key"), ("你好", "stella", "")]:
        service = DeepSeekSpeechTTS(voice=voice, api_key=key)
        monkeypatch.setattr(service, "_connect", fail)
        frames = [f async for f in service.run_tts(text, "ctx")]
        assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
        await service.cleanup()


def test_url_normalization_and_character_limits():
    for url in ["https://api.deepseek.com", "https://api.deepseek.com/", "https://api.deepseek.com/v1/"]:
        assert websocket_url(url, "stella", True).startswith("wss://api.deepseek.com/v1/tools/tts?")
    for url in ["http://untrusted.test", "https://user:secret@host", "https://host/?key=secret", "https://host/#secret"]:
        with pytest.raises(ValueError):
            websocket_url(url, "stella", True)
    assert _text_message("你" * 5000)
    with pytest.raises(ValueError):
        _text_message("a" * 10001)


@pytest.mark.asyncio
async def test_pipecat_context_playback_and_failed_last_sentence_complete():
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.tests.utils import run_test
    from server.playback import PlaybackLedger, PlaybackStart
    calls = []
    async def handler(ws):
        calls.append(json.loads(await ws.recv()))
        await ws.recv()
        if len(calls) == 1:
            await ws.send(b"\x01\x00" * 240)
            await finish(ws)
        else:
            await finish(ws, "service_error")
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        service = service_for(server)
        pipeline = Pipeline([service, PlaybackStart(PlaybackLedger(lambda *_: None))])
        downstream, upstream = await asyncio.wait_for(run_test(pipeline, frames_to_send=[
            LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()]), 5)
    assert len(calls) == 2
    assert any(isinstance(f, TTSAudioRawFrame) for f in downstream)
    assert any(isinstance(f, TTSStoppedFrame) for f in downstream)
    assert any(isinstance(f, ErrorFrame) for f in upstream)
