import json

import pytest
from loguru import logger
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.frames.protobufs import frames_pb2

from server.voice_serializer import VoiceProtobufSerializer


@pytest.mark.asyncio
async def test_screenshot_payload_roundtrip_is_private_in_diagnostics():
    payload = {'label': 'rtvi-ai', 'type': 'client-message', 'id': 'frame',
        'data': {'t': 'voice.screen.frame', 'd': {'data': 'PRIVATE-IMAGE-BASE64'}}}
    wire = frames_pb2.Frame()
    wire.message.data = json.dumps(payload)
    records = []
    sink = logger.add(lambda message: records.append(str(message)))
    try:
        result = await VoiceProtobufSerializer().deserialize(wire.SerializeToString())
        assert result.message == payload
        logger.debug('frame {} / {!r}', result, result)
        assert 'PRIVATE-IMAGE-BASE64' not in '\n'.join(records)
    finally:
        logger.remove(sink)


@pytest.mark.asyncio
async def test_native_audio_roundtrip_and_invalid_message_fail_closed():
    serializer = VoiceProtobufSerializer()
    wire = await serializer.serialize(OutputAudioRawFrame(b'\x01\x00' * 240, 24000, 1))
    frame = await serializer.deserialize(wire)
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.audio == b'\x01\x00' * 240 and frame.sample_rate == 24000
    assert await serializer.deserialize(b'invalid protobuf') is None
    wire = frames_pb2.Frame()
    for body in ['{', '[]', 'null']:
        wire.message.data = body
        assert await serializer.deserialize(wire.SerializeToString()) is None
