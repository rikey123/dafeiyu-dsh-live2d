"""Opt-in isolated fixture: synthetic canvas/DSH/System One/PCM, never real capture."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

if os.environ.get('DAFEIYU_PRESENCE_ACCEPTANCE') != '1':
    raise SystemExit('Explicit isolated presence acceptance opt-in required')
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('DAFEIYU_PRESENCE_QA', 'E:/Dafeiyu/qa/companion-presence-20261116'))
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'tmp').mkdir(exist_ok=True)
os.environ.update(TEMP=str(OUT / 'tmp'), TMP=str(OUT / 'tmp'))
os.environ.update(DAFEIYU_DATA_DIR=str(OUT / 'isolated-store'), DAFEIYU_HARNESS='dsh',
                  DAFEIYU_PLUGIN_TOKEN='presence-fixture-only', DAFEIYU_DSH_ORIGIN='http://127.0.0.1:18878')
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from fastapi import Request
from server import main, pipecat_voice, systemone, idle_companion, screen_companion
from server.dsh import BridgeClient
from speech.pipecat_services import LocalSpeechTTS

PERSONA = 'OFFLINE_PERSONA_鲸鱼娘：好奇、嘴硬心软，喜欢陪主人聊眼前的小事。'
INTERESTS = 'OFFLINE_INTERESTS_星露谷与音乐视频'
state = {'fixture': True, 'time_offset': 0, 'busy': False, 'silence': False, 'judgment_calls': 0, 'decision_calls': 0,
         'vision_calls': 0, 'idle_calls': 0, 'idle_images': 0, 'tts_calls': 0, 'playback_acks': 0,
         'persona_seen': False, 'interests_seen': False, 'voice_connections': 0, 'contexts': 0,
         'direct_calls': 0, 'idle_interests_seen': False, 'normal_calls': 0}
sessions, queues = {}, {}
server_instance = None


def clock():
    return time.monotonic() + state['time_offset']


OriginalIdle, OriginalScreen = idle_companion.IdleCompanion, screen_companion.ScreenCompanion


class FixtureIdle(OriginalIdle):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{**kwargs, 'clock': clock, 'jitter': lambda: 0})


class FixtureScreen(OriginalScreen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{**kwargs, 'clock': clock})


async def preview_transport(request):
    body = json.loads(request.content)
    meta = body['dafeiyu']
    image = meta.get('images', [])
    if meta['kind'] == 'idle':
        state['idle_calls'] += 1
        state['idle_images'] += len(image)
        state['idle_interests_seen'] = meta.get('companion_interests') == INTERESTS
    elif meta['kind'] == 'screen':
        state['vision_calls'] += 1
        state['direct_calls'] += meta.get('screen_mode') == 'direct'
    else:
        raise AssertionError('Only proactive previews use this fixture transport')
    chunks = '' if state['silence'] else 'data: ' + json.dumps({'choices': [{'delta': {'content': '这是离线陪伴测试。'}}]}) + '\n\n'
    chunks += 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n'
    return httpx.Response(200, text=chunks, headers={'content-type': 'text/event-stream'})


class OfflineBridge(BridgeClient):
    def __init__(self):
        super().__init__('http://127.0.0.1:1', 'offline-only', transport=httpx.MockTransport(preview_transport))

    async def status(self):
        return {'ready': True, 'configured': True, 'screen_ready': True,
                'model': 'offline-presence-fixture', 'temperature_supported': False}

    async def create_session(self, session_id=None):
        identifier = session_id or 'presence-' + uuid.uuid4().hex
        sessions.setdefault(identifier, [])
        queues.setdefault(identifier, asyncio.Queue())
        return {'id': identifier, 'title': 'offline presence fixture'}

    async def sessions(self):
        return [{'id': key, 'title': 'offline presence fixture'} for key in sessions]

    async def messages(self, identifier): return sessions.setdefault(identifier, [])

    async def voice_state(self, _session, _connection, active, _microphone=False):
        state['voice_connections'] += 1 if active else -1
        return {'accepted': True}

    async def voice_context(self, _identifier):
        state['contexts'] += 1
        return {'persona': PERSONA, 'busy': state['busy'], 'messages': [], 'environment': 'offline voice context'}

    async def voice_events(self, identifier, _cursor=None):
        yield 'fixture:0', {'type': 'ready'}
        queue = queues.setdefault(identifier, asyncio.Queue())
        while True:
            yield 'fixture:' + uuid.uuid4().hex, await queue.get()

    async def voice_turn(self, body):
        state['normal_calls'] += 1
        meta, text = body['dafeiyu'], body['messages'][-1]['content']
        queue = queues.setdefault(meta['session_id'], asyncio.Queue())
        request_id, generation_id = meta['request_id'], uuid.uuid4().hex
        await queue.put({'type': 'conversation.user', 'message_id': uuid.uuid4().hex, 'text': text, 'request_id': request_id})
        for typ, fields in [('response.start', {}), ('response.text', {'text': '收到，先回应再处理。'}), ('response.end', {})]:
            await queue.put({'type': typ, 'generation_id': generation_id, 'request_id': request_id, 'kind': 'normal', **fields})
        await queue.put({'type': 'turn.end', 'request_id': request_id})
        return {'accepted': True, 'request_id': request_id}

    async def playback(self, *args):
        state['playback_acks'] += 1
        return {'accepted': True}


async def decision_transport(request):
    body = json.loads(request.content)
    serialized = json.dumps(body, ensure_ascii=False)
    state['judgment_calls'] += 'speak_now' in body['questions']
    state['decision_calls'] += 1
    state['persona_seen'] = state['persona_seen'] or PERSONA in serialized
    state['interests_seen'] = state['interests_seen'] or INTERESTS in serialized
    answers = {}
    for key, question in body['questions'].items():
        if question['type'] == 'noul':
            answers[key] = {'type': 'noul', 'noul': .01}
        elif question['type'] == 'choice':
            preferred = 'wait' if key == 'intent' else 'neutral' if 'emotion' in key else 'natural' if key == 'expression' else 'none'
            answers[key] = {'type': 'choice', 'choice': preferred, 'confidence': .99,
                            'probabilities': {value: float(value == preferred) for value in question['criteria']}}
        else:
            answers[key] = {'type': 'score', 'score': 1, 'confidence': .99, 'probabilities': {'0': 0, '1': 1, '2': 0}}
    return httpx.Response(200, json={'model': body['model'], 'answers': answers})


OriginalDecision = systemone.SystemOneClient


class OfflineDecision(OriginalDecision):
    def __init__(self, settings, **kwargs):
        super().__init__(settings, **{**kwargs, 'transport': httpx.MockTransport(decision_transport)})


def tone(settings):
    async def speech(_request):
        state['tts_calls'] += 1
        return httpx.Response(200, content=b'\x20\x00' * 4800, headers={
            'X-Audio-Sample-Rate': '24000', 'X-Audio-Channels': '1', 'X-Audio-Format': 'pcm_s16le'})
    service = LocalSpeechTTS(base_url='http://127.0.0.1:1', sample_rate=24000, reuse_context_id_within_turn=False)
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(speech))
    return service


@main.app.get('/api/presence-fixture')
async def current(): return dict(state)


@main.app.put('/api/presence-fixture')
async def change(request: Request):
    body = await request.json()
    for name in ('busy', 'silence'):
        if type(body.get(name)) is bool: state[name] = body[name]
    if type(body.get('advance_s')) is int and 0 < body['advance_s'] <= 3601:
        state['time_offset'] += body['advance_s']
    if body.get('shutdown') is True and server_instance is not None:
        server_instance.should_exit = True
    return dict(state)


async def run():
    global server_instance
    main.dsh.BridgeClient = OfflineBridge
    systemone.SystemOneClient = OfflineDecision
    idle_companion.IdleCompanion = FixtureIdle
    screen_companion.ScreenCompanion = FixtureScreen
    pipecat_voice.create_tts = tone
    main.store.update_settings({'systemone_enabled': True, 'systemone_ark_api_key': 'offline-only',
        'screen_companion_enabled': True, 'screen_companion_interval_ms': 1000,
        'screen_companion_refresh_ms': 5000, 'screen_companion_cooldown_s': 10,
        'screen_request_enabled': False, 'screen_request_timeout_ms': 5000,
        'companion_interests': INTERESTS, 'idle_companion_enabled': False,
        'idle_companion_after_s': 30, 'idle_companion_cooldown_s': 30, 'idle_companion_max_per_hour': 6,
        'systemone_initiative_enabled': False, 'tts_mode': 'cpu'})
    main.app.router.routes[:] = sorted(main.app.router.routes,
        key=lambda route: 0 if getattr(route, 'path', '') == '/api/presence-fixture' else 1)
    try:
        server_instance = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=18878, log_level='warning'))
        await server_instance.serve()
    finally:
        main.store.db.close()


if __name__ == '__main__': asyncio.run(run())
