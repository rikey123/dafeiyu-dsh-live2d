import asyncio
import json

import pytest
import websockets
from pipecat.frames.frames import ErrorFrame, InterruptionFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputTransportMessageFrame, TTSAudioRawFrame, TTSStoppedFrame, TTSTextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import SleepFrame, run_test

from server.playback import PlaybackLedger, PlaybackStart
from speech.cosy_bistream import CosyBistreamTTS


@pytest.mark.asyncio
async def test_cosy_token_mode_native_pipeline_one_context_and_order():
    async def handler(socket):
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
        pipeline = Pipeline([CosyBistreamTTS(url=f"ws://127.0.0.1:{port}"), PlaybackStart(PlaybackLedger(lambda _group, _text: None))])
        downstream, _ = await asyncio.wait_for(run_test(pipeline, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好"), LLMTextFrame("世界。"), LLMFullResponseEndFrame()]), 10)
    starts = [frame for frame in downstream if isinstance(frame, OutputTransportMessageFrame) and frame.message.get("data", {}).get("type") == "voice.playback.start"]
    audio = [frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]
    assert len(starts) == 1 and len(audio) == 2
    assert all(frame.context_id == starts[0].message["data"]["epoch"] for frame in audio)
    assert any(isinstance(frame, TTSStoppedFrame) for frame in downstream)
    assert any(isinstance(frame, TTSTextFrame) for frame in downstream)


@pytest.mark.asyncio
@pytest.mark.parametrize("audio_before_interrupt", [False, True])
async def test_native_interruption_has_no_false_errors_and_next_turn_plays(audio_before_interrupt):
    sessions = []
    old_audio = b"\x01\x00" * 80
    new_audio = b"\x02\x00" * 80
    async def handler(socket):
        session = len(sessions)
        sessions.append([])
        await socket.recv()
        await socket.send(json.dumps({"type": "ready", "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "text_ack": True}))
        async for raw in socket:
            message = json.loads(raw)
            sessions[session].append(message["type"])
            if message["type"] == "text":
                await socket.send(json.dumps({"type": "text_ack", "sequence": 1}))
                if session or audio_before_interrupt:
                    await socket.send(new_audio if session else old_audio)
            elif message["type"] == "cancel":
                return
            elif message["type"] == "end":
                await socket.send(json.dumps({"type": "done"}))
                return
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        tts = CosyBistreamTTS(url=f"ws://127.0.0.1:{port}")
        downstream, upstream = await asyncio.wait_for(run_test(tts, frames_to_send=[
            LLMFullResponseStartFrame(), LLMTextFrame("old"), SleepFrame(.05),
            InterruptionFrame(), SleepFrame(.05),
            LLMFullResponseStartFrame(), LLMTextFrame("new"), LLMFullResponseEndFrame(),
        ]), 10)
    assert len(sessions) == 2
    assert sessions[0] == ["text", "cancel"]
    assert sessions[1] == ["text", "end"]
    assert not any(isinstance(frame, ErrorFrame) for frame in upstream)
    audio = [frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]
    assert audio[-1].audio == new_audio
    if audio_before_interrupt:
        assert audio[0].context_id != audio[-1].context_id
