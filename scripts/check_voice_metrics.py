"""Observe native RTVI metrics against isolated serve_voice_acceptance.py.

Default 8875 must be the controlled QA gateway, never primary user settings.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
import websockets
from pipecat.frames.protobufs import frames_pb2


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8875')
    args = parser.parse_args()
    base = args.url.rstrip('/')
    async with httpx.AsyncClient() as client:
        session = (await client.post(base + '/api/sessions')).json()['id']
        try:
            async with websockets.connect(base.replace('http', 'ws', 1) + f'/ws/voice?session_id={session}', max_size=4000000) as ws:
                def msg(kind, data):
                    frame = frames_pb2.Frame()
                    frame.message.data = json.dumps({'label': 'rtvi-ai', 'type': kind, 'id': kind, 'data': data})
                    return frame.SerializeToString()
                await ws.send(msg('client-ready', {}))
                sent = False
                metrics = []
                audio_bytes = 0
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    packet = frames_pb2.Frame.FromString(await asyncio.wait_for(ws.recv(), timeout=60))
                    kind = packet.WhichOneof('frame')
                    if kind == 'audio':
                        audio_bytes += len(packet.audio.audio)
                    if kind != 'message':
                        continue
                    event = json.loads(packet.message.data)
                    if event.get('type') == 'bot-ready' and not sent:
                        await ws.send(msg('send-text', {'content': '你好，请简单介绍自己。'}))
                        sent = True
                    if event.get('type') == 'metrics':
                        metrics.append(event)
                    if audio_bytes and any(any(x.get('processor', '').startswith('LocalSpeechTTS') for x in item.get('data', {}).get('processing', [])) for item in metrics):
                        break
                assert audio_bytes and any(item.get('data', {}).get('ttfb') for item in metrics)
                result = {'method': 'Native RTVI processor metrics; controlled model SSE, real local CPU speech. Not physical output latency.', 'audio_bytes': audio_bytes, 'metrics': metrics}
                target = Path(__file__).resolve().parents[1] / 'artifacts/voice-metrics.json'
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False))
        finally:
            await client.delete(base + f'/api/sessions/{session}')


asyncio.run(main())
