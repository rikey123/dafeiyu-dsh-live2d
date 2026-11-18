"""Real local ASR/TTS + production Conversation, controlled SSE model, temp DB.

No DeepSeek request, physical microphone, browser playback or live settings writes.
Playback acknowledgements are simulated and must not be read as audible latency.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import wave

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.engine import Conversation
from server.storage import Store


class Tokens(httpx.AsyncByteStream):
    def __init__(self, sentences):
        self.sentences = sentences

    async def __aiter__(self):
        for text in self.sentences:
            await asyncio.sleep(.025)
            yield ('data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\n').encode()
        yield b'data: [DONE]\n\n'


async def model(request):
    prompt = json.loads(request.content)['messages'][-1]['content']
    sentences = ['新的问题已经收到了。'] if prompt == '下一轮' else [
        '这是已经播放完成的第一句。',
        '接下来这一段比较长用来验证语音生成过程中取消请求是否影响下一轮回复而不是验证模型本身的回复质量。',
    ]
    return httpx.Response(200, stream=Tokens(sentences), headers={'content-type': 'text/event-stream'})


class Recorder:
    def __init__(self):
        self.events = []
        self.changed = asyncio.Condition()

    async def send_json(self, event):
        async with self.changed:
            self.events.append({**event, '_at': time.perf_counter()})
            self.changed.notify_all()

    async def until(self, kind, after=0, timeout=60):
        async with asyncio.timeout(timeout):
            async with self.changed:
                while True:
                    for event in self.events[after:]:
                        if event['type'] == 'error':
                            raise AssertionError(event)
                        if event['type'] == kind:
                            return event
                    await self.changed.wait()


async def main():
    async with httpx.AsyncClient(timeout=120, mounts={'http://voice-audit-llm': httpx.MockTransport(model)}) as client:
        health = (await client.get('http://127.0.0.1:8766/health')).json()
        assert health['asr']['ready'] and health['tts']['ready'], health
        with tempfile.TemporaryDirectory(prefix='dafeiyu-voice-audit-') as directory:
            store = Store(Path(directory))
            try:
                store.update_settings({'llm_base_url': 'http://voice-audit-llm/v1', 'llm_model': 'controlled-sse', 'llm_api_key': 'controlled-test-only', 'speech_base_url': 'http://127.0.0.1:8766', 'voice': 'default'})
                session = store.session()
                recorder = Recorder()
                conversation = Conversation(recorder, store, client, session)
                with wave.open(io.BytesIO((ROOT / 'artifacts/live-smoke/input.wav').read_bytes()), 'rb') as audio:
                    assert audio.getframerate() == 16000 and audio.getsampwidth() == 2 and audio.getnchannels() == 1
                    pcm = base64.b64encode(audio.readframes(audio.getnframes())).decode()
                started = time.perf_counter()
                await conversation.start({'type': 'audio', 'audio': pcm, 'sample_rate': 16000})
                first = await recorder.until('audio')
                first_ms = (first['_at'] - started) * 1000
                await conversation.ack(first['epoch'], first['segment_id'])
                await asyncio.sleep(.15)  # Let the following real TTS HTTP request start.
                cutoff = len(recorder.events)
                cancel_started = time.perf_counter()
                await conversation.interrupt()
                cancel_ms = (time.perf_counter() - cancel_started) * 1000
                old_epoch = first['epoch']
                next_started = time.perf_counter()
                await conversation.start({'type': 'text', 'text': '下一轮'})
                next_audio = await recorder.until('audio', cutoff)
                assert next_audio['epoch'] > old_epoch
                await conversation.ack(next_audio['epoch'], next_audio['segment_id'])
                await conversation.task
                history = store.messages(session)
                assistant = [row for row in history if row['role'] == 'assistant']
                assert assistant[0]['content'] == first['text'] and assistant[0]['interrupted']
                assert assistant[-1]['content'] == next_audio['text'] and not assistant[-1]['interrupted']
                assert not any(ev['type'] == 'audio' and ev['epoch'] == old_epoch for ev in recorder.events[cutoff:])
                result = {'method': __doc__, 'asr_device': health['asr']['device'], 'tts_device': health['tts']['device'], 'transcript': next(ev['text'] for ev in recorder.events if ev['type'] == 'transcript'), 'submitted_pcm_to_first_wav_ms': first_ms, 'gateway_cancel_completion_ms': cancel_ms, 'next_text_to_wav_ms': (next_audio['_at'] - next_started) * 1000, 'late_old_audio': 0, 'heard_history_verified': True, 'assistant_history': [{'text': row['content'], 'interrupted': row['interrupted']} for row in assistant]}
                target = ROOT / 'artifacts/voice-audit/pipeline.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                if 'conversation' in locals() and conversation.task and not conversation.task.done():
                    await conversation.interrupt()
                store.db.close()


if __name__ == '__main__':
    asyncio.run(main())
