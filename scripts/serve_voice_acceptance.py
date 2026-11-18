"""Isolated real Pipecat gateway + local speech, controlled SSE model for browser QA.

Run with .venv-voice Python. Never changes primary settings or calls a cloud LLM.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.responses import Response
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import main
from server.storage import Store

provider = FastAPI()
requests_seen = []
expression_fixture = False
controlled_reply = None
api_audio_fixture = None
deepseek_fixture_outcome = 'success'


@provider.get('/v1/models')
def models():
    return {'data': [{'id': 'controlled-voice-test'}]}


@provider.post('/v1/chat/completions')
async def completion(request: Request):
    body = await request.json()
    last_user = next((message.get('content', '') for message in reversed(body['messages']) if message.get('role') == 'user'), '')
    # This isolated provider receives test conversations only. Preserve ordering
    # so browser QA can verify cancelled/identical replies against their turns.
    requests_seen.append({'text': last_user, 'at': time.time(), 'messages': [
        {'role': message.get('role'), 'content': message.get('content')}
        for message in body['messages']
    ]})
    text = '好的，我们换一个问题。你想聊些什么？' if '换' in str(last_user) or '等一下' in str(last_user) else (
        '你好，我是大肥鱼，很高兴和你聊天。我们可以慢慢聊今天发生的事情。'
        '你可以在我说话的时候随时插话。简单的附和不会让我重新开始回答。'
        '如果你想换个话题，直接告诉我就好。我会停下来认真听你的问题。')
    if expression_fixture:
        text = '今天很开心，听到你的消息真好。抱歉，刚才的事情让人难过。'
    if controlled_reply:
        text = controlled_reply

    async def chunks():
        for index in range(0, len(text), 5):
            data = {'id': 'voice-test', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'controlled-voice-test', 'choices': [{'index': 0, 'delta': {'content': text[index:index + 5]}, 'finish_reason': None}]}
            yield 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'
            await asyncio.sleep(.035)
        yield 'data: ' + json.dumps({'id': 'voice-test', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}) + '\n\n'
        yield 'data: [DONE]\n\n'
    return StreamingResponse(chunks(), media_type='text/event-stream')


@provider.get('/test/requests')
def requests():
    return requests_seen


@provider.put('/test/reply')
async def set_test_reply(request: Request):
    global controlled_reply
    from fastapi import HTTPException
    value = (await request.json()).get('text')
    if not isinstance(value, str) or not 1 <= len(value) <= 2000:
        raise HTTPException(400, 'bounded fixture reply required')
    controlled_reply = value
    return {'test_fixture': True}


@provider.post('/v1/audio/speech')
async def fixture_api_tts(request: Request):
    """A labelled protocol fixture, never evidence of an external paid API."""
    from fastapi import HTTPException
    if api_audio_fixture is None or request.headers.get('authorization') != 'Bearer audit-tts-only':
        raise HTTPException(401, 'test-only credentials required')
    body = await request.json()
    if body.get('response_format') != 'pcm':
        raise HTTPException(400, 'fixture supports PCM only')
    requests_seen.append({'type': 'api_tts_fixture', 'model': body.get('model'), 'at': time.time()})
    import wave
    with wave.open(str(api_audio_fixture), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
            raise HTTPException(500, 'fixture must be mono PCM16 24kHz WAV')
        return Response(wav.readframes(wav.getnframes()), media_type='audio/pcm')


@provider.put('/test/tts-outcome')
async def set_tts_outcome(request: Request):
    """Only this isolated test provider can simulate native cloud failures."""
    global deepseek_fixture_outcome
    from fastapi import HTTPException
    outcome = (await request.json()).get('outcome')
    if outcome not in {'success', 'content_filter', 'disconnect', 'slow'}:
        raise HTTPException(400, 'unknown test outcome')
    deepseek_fixture_outcome = outcome
    return {'test_fixture': True, 'outcome': outcome}


@provider.websocket('/v1/tools/tts')
async def fixture_deepseek_tts(socket: WebSocket):
    """DeepSeek wire-protocol fixture; PCM is a labelled local WAV, not cloud TTS."""
    if api_audio_fixture is None or socket.headers.get('authorization') != 'Bearer audit-tts-only':
        await socket.close(code=1008)
        return
    await socket.accept()
    record = {'type': 'deepseek_tts_fixture', 'voice': socket.query_params.get('voice_id'),
              'filter_markdown': socket.query_params.get('filter_markdown'),
              'outcome': deepseek_fixture_outcome, 'closed': False}
    requests_seen.append(record)
    try:
        start, end = await socket.receive_json(), await socket.receive_json()
        if (start.get('event') != 'text' or not start.get('text')
                or end != {'event': 'finish_text'} or socket.query_params.get('format') != 'pcm'
                or record['voice'] not in {'stella', 'tide'}):
            await socket.close(code=1008)
            return
        if record['outcome'] == 'content_filter':
            await socket.send_json({'event': 'finish', 'code': 'content_filter', 'message': 'DO NOT ECHO provider-private-body'})
            return
        import wave
        with wave.open(str(api_audio_fixture), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
                await socket.close(code=1011)
                return
            while audio := wav.readframes(2400):
                await socket.send_bytes(audio)
                if record['outcome'] == 'disconnect':
                    await socket.close()
                    return
                if record['outcome'] == 'slow':
                    # Await the client close to prove actual upstream cancellation.
                    while True:
                        await socket.receive_text()
                await asyncio.sleep(.02)
        await socket.send_json({'event': 'finish', 'code': 'success', 'message': ''})
    except WebSocketDisconnect:
        pass
    finally:
        record['closed'] = True
        try:
            await socket.close()
        except RuntimeError:
            pass


async def run():
    global expression_fixture, controlled_reply, api_audio_fixture
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8875)
    parser.add_argument('--provider-port', type=int, default=8874)
    parser.add_argument('--speech-url', default='http://127.0.0.1:8766')
    parser.add_argument('--streaming-asr', action='store_true', help='Enable stable interim policy in this isolated store; speech must enable its online model')
    parser.add_argument('--expressions', action='store_true', help='Return two fixed emotion-bearing sentences for playback-aligned expression QA')
    parser.add_argument('--reply', help='Controlled LLM reply; speech generation and playback remain real')
    parser.add_argument('--tts-engine', choices=['local', 'cosyvoice'], default='local')
    parser.add_argument('--cosyvoice-url', default='http://127.0.0.1:8770')
    parser.add_argument('--tts-mode', choices=['gpu', 'cpu', 'auto', 'api'])
    parser.add_argument('--gpu-tts-model', choices=['gpt_sovits', 'index_tts'], default='gpt_sovits')
    parser.add_argument('--manage-model-services', action='store_true', help='Reconcile real local TTS services with this isolated store only')
    parser.add_argument('--api-audio-fixture', type=Path, help='Test-only PCM API fixture; not an external provider test')
    parser.add_argument('--deepseek-api-fixture', action='store_true', help='Use native DeepSeek WS protocol with local WAV, no cloud API or GPU')
    args = parser.parse_args()
    if args.deepseek_api_fixture and not args.api_audio_fixture:
        parser.error('--deepseek-api-fixture requires --api-audio-fixture')
    expression_fixture = args.expressions
    controlled_reply = args.reply
    api_audio_fixture = args.api_audio_fixture
    with tempfile.TemporaryDirectory(prefix='dafeiyu-pipecat-acceptance-') as directory:
        test_store = Store(Path(directory))
        test_store.update_settings({'llm_base_url': f'http://127.0.0.1:{args.provider_port}/v1', 'llm_model': 'controlled-voice-test', 'llm_api_key': 'test-only', 'speech_base_url': args.speech_url, 'voice': 'default', 'streaming_asr_preview': args.streaming_asr})
        test_store.update_settings({'tts_engine': args.tts_engine, 'cosyvoice_url': args.cosyvoice_url})
        if args.tts_mode:
            test_store.update_settings({'tts_mode': args.tts_mode, 'gpu_tts_model': args.gpu_tts_model})
        if args.deepseek_api_fixture:
            test_store.update_settings({'tts_mode': 'api', 'tts_api_provider': 'deepseek',
                'tts_api_base_url': f'http://127.0.0.1:{args.provider_port}/v1',
                'tts_api_voice': 'stella', 'tts_api_key': 'audit-tts-only', 'systemone_enabled': False})
        main.store = test_store
        # Trust only this isolated gateway's own loopback origin for browser QA.
        production_origin_check = main.trusted_origin
        main.trusted_origin = lambda origin: production_origin_check(origin) or origin == f'http://127.0.0.1:{args.port}'
        service = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=args.port, log_level='info'))
        model = uvicorn.Server(uvicorn.Config(provider, host='127.0.0.1', port=args.provider_port, log_level='warning'))
        manager = None
        stop_file = Path(directory) / 'stop-model-manager'
        if args.manage_model_services:
            import subprocess
            manager = await asyncio.create_subprocess_exec(
                str(ROOT / '.venv/Scripts/python.exe'), str(ROOT / 'scripts/audit_model_services.py'),
                '--data-dir', directory, '--stop-file', str(stop_file), cwd=ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            await asyncio.gather(model.serve(), service.serve())
        finally:
            if manager:
                stop_file.touch()
                await asyncio.wait_for(manager.wait(), 30)
            test_store.db.close()


if __name__ == '__main__':
    asyncio.run(run())
