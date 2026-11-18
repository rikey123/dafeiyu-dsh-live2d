"""Exercise real automatic voice routing through an isolated gateway, without a mic.

Run serve_voice_acceptance.py with DAFEIYU_VOICE_MODE=auto first. This checks
server PCM and stop/recovery, not browser consumption or physical playback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

import httpx
import websockets
from pipecat.frames.protobufs import frames_pb2


async def run(url, output=None, interrupt_first=False):
    async with httpx.AsyncClient(base_url=url, timeout=15) as client:
        status = (await client.get('/api/status')).json()
        session = (await client.post('/api/sessions')).json()['id']
        async with websockets.connect(url.replace('http', 'ws', 1) + '/ws/voice?session_id=' + session,
                                      max_size=8 * 1024 * 1024) as socket:
            async def send(kind, identifier, data):
                frame = frames_pb2.Frame()
                frame.message.data = json.dumps({'label': 'rtvi-ai', 'type': kind, 'id': identifier, 'data': data})
                await socket.send(frame.SerializeToString())

            async def receive():
                frame = frames_pb2.Frame.FromString(await socket.recv())
                if frame.WhichOneof('frame') == 'audio':
                    return {'audio_bytes': len(frame.audio.audio), 'rate': frame.audio.sample_rate}
                if frame.WhichOneof('frame') == 'message':
                    return json.loads(frame.message.data)
                return {}

            await send('client-ready', 'ready', {})
            async with asyncio.timeout(30):
                while (await receive()).get('type') != 'bot-ready':
                    pass
            results = []
            for turn in range(2):
                started = time.monotonic()
                await send('send-text', f'text-{turn}', {'content': f'第{turn + 1}次测试'})
                first = None
                pcm = 0
                async with asyncio.timeout(120):
                    while True:
                        event = await receive()
                        if event.get('type') == 'error':
                            raise RuntimeError(str(event))
                        if event.get('audio_bytes'):
                            first = first if first is not None else time.monotonic() - started
                            assert event['rate'] == 24000
                            pcm += event['audio_bytes']
                            if turn == 0 and interrupt_first:
                                break
                        data = event.get('data') or {}
                        if event.get('type') == 'server-message' and data.get('type') == 'voice.playback.boundary':
                            if not pcm:
                                raise RuntimeError('Boundary without actual PCM')
                            break
                await send('client-message', f'stop-{turn}', {'t': 'voice.stop', 'd': {}})
                async with asyncio.timeout(10):
                    while True:
                        event = await receive()
                        if event.get('id') == f'stop-{turn}':
                            break
                results.append({'first_pcm_seconds': first, 'pcm_bytes': pcm,
                                'stopped_during_audio': turn == 0 and interrupt_first})
            history = (await client.get(f'/api/sessions/{session}/messages')).json()
            # No fake playback receipts: transport reception does not confirm hearing.
            assert not any(row['role'] == 'assistant' for row in history), history
            after = (await client.get('/api/status')).json()
            report = {'method': 'real local inference; protobuf PCM; no microphone, playback or receipts',
                      'voice_policy': status.get('voice_policy'),
                      'local_speech': status.get('speech'),
                      'cosy_after': after.get('optional', {}).get('cosyvoice'),
                      'turns': results, 'unconfirmed_assistant_history': 0}
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + '\n', encoding='utf-8')
            print(rendered)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8875')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--interrupt-first', action='store_true', help='Stop after first PCM chunk, then verify the next answer')
    args = parser.parse_args()
    asyncio.run(run(args.url, args.output, args.interrupt_first))
