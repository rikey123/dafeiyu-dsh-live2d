"""Isolated browser protocol fixture, NOT DSH/cloud/desktop inference evidence.

Only generated browser canvas frames enter this server. No user's settings,
credentials, microphone, GPU models or DSH profile are read or changed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('SCREEN_FIXTURE_OUTPUT_DIR', 'E:/Dafeiyu/verification/screen-request'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ['DAFEIYU_DATA_DIR'] = str(OUT / 'isolated-import-store')
os.environ['DAFEIYU_HARNESS'] = 'dsh'
os.environ['DAFEIYU_PLUGIN_TOKEN'] = 'screen-fixture-only'
os.environ['DAFEIYU_DSH_ORIGIN'] = os.environ.get('SCREEN_FIXTURE_ORIGIN', 'http://127.0.0.1:18875')
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from fastapi import Request
from server import main, pipecat_voice, systemone
from server.storage import Store
from speech.pipecat_services import LocalSpeechTTS

state = {'fixture': True, 'proactive': 'wait', 'normal_images': 0, 'proactive_images': 0,
    'intent_calls': 0, 'judgment_calls': 0, 'tts_calls': 0, 'playback_acks': 0,
    'reply_delay_ms': 0, 'tts_samples': 4800}
rows = {}


class BridgeFixture:
    async def status(self):
        return {'ready': True, 'configured': True, 'screen_ready': True,
            'model': 'screen-protocol-fixture', 'temperature_supported': False}

    async def create_session(self, session_id=None):
        identifier = session_id or 'fixture-' + uuid.uuid4().hex
        rows.setdefault(identifier, [])
        return {'id': identifier, 'title': 'screen fixture'}

    async def sessions(self):
        return [{'id': identifier, 'title': 'screen fixture'} for identifier in rows]

    async def messages(self, identifier): return rows.setdefault(identifier, [])
    async def delete_session(self, identifier): return {'deleted': rows.pop(identifier, None) is not None}

    async def chat_text(self, body):
        meta = body['dafeiyu']
        image = meta.get('images', [])
        key = 'normal_images' if meta['kind'] == 'normal' else 'proactive_images'
        state[key] += len(image)
        if image:
            state['last_image_hash'] = hashlib.sha256(image[0]['data'].encode()).hexdigest()
        state['last_kind'] = meta['kind']
        state['last_screen_state'] = meta.get('screen_state')
        await asyncio.sleep(state['reply_delay_ms'] / 1000)
        text = '这是合成画面的协议测试。' if image else '尚未共享屏幕，请先授权。'
        yield text

    async def playback(self, *args):
        state['playback_acks'] += 1
        return {'accepted': True}


async def decision_transport(request):
    body = json.loads(request.content)
    questions = body['questions']
    if 'look_at_screen' in questions:
        state['intent_calls'] += 1
    if 'speak_now' in questions:
        state['judgment_calls'] += 1
    answers = {}
    for key, question in questions.items():
        kind = question['type']
        if kind == 'noul':
            probability = .98 if key == 'look_at_screen' or key == 'speak_now' and state['proactive'] in {'strong', 'ambiguous'} else .01
            answers[key] = {'type': kind, 'noul': probability}
        elif kind == 'choice':
            preferred = {'intent': 'comment' if state['proactive'] in {'strong', 'ambiguous'} else 'wait',
                'emotion': 'neutral', 'expression': 'natural', 'gesture': 'none', 'user_emotion': 'neutral'}[key]
            answers[key] = {'type': kind, 'choice': preferred, 'confidence': .99,
                'probabilities': {value: float(value == preferred) for value in question['criteria']}}
            if key == 'intent' and state['proactive'] == 'ambiguous':
                answers[key] = {'type': kind, 'choice': 'comment', 'confidence': .4709962195,
                    'probabilities': {'wait': .00009, 'warn': .00066, 'cheer': .38576,
                                      'comment': .56128, 'empathize': .05221}}
        else:
            answers[key] = {'type': kind, 'score': 1, 'confidence': .99,
                'probabilities': {'0': 0, '1': 1, '2': 0}}
    return httpx.Response(200, json={'model': body['model'], 'answers': answers})


OriginalClient = systemone.SystemOneClient
class DecisionFixture(OriginalClient):
    def __init__(self, settings, **kwargs):
        super().__init__(settings, transport=httpx.MockTransport(decision_transport), **kwargs)


def tone_fixture(settings):
    async def speech(request):
        state['tts_calls'] += 1
        return httpx.Response(200, content=b'\x20\x00' * state['tts_samples'], headers={
            'X-Audio-Sample-Rate':'24000', 'X-Audio-Channels':'1', 'X-Audio-Format':'pcm_s16le'})
    service = LocalSpeechTTS(base_url='http://screen-fixture', sample_rate=24000,
        reuse_context_id_within_turn=False)
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(speech))
    return service


@main.app.get('/api/screen-fixture')
async def current(): return dict(state)


@main.app.put('/api/screen-fixture')
async def change(request: Request):
    body = await request.json()
    value = body.get('proactive')
    if value in {'wait', 'strong', 'ambiguous'}: state['proactive'] = value
    for name, lower, upper in [('reply_delay_ms', 0, 2000), ('tts_samples', 4800, 48000)]:
        value = body.get(name)
        if type(value) is int and lower <= value <= upper: state[name] = value
    return dict(state)


async def run():
    main.app.router.routes[:] = sorted(main.app.router.routes,
        key=lambda route: 0 if getattr(route, 'path', '') == '/api/screen-fixture' else 1)
    main.dsh.BridgeClient = BridgeFixture
    systemone.SystemOneClient = DecisionFixture
    pipecat_voice.create_tts = tone_fixture
    with tempfile.TemporaryDirectory(prefix='browser-', dir=OUT) as directory:
        main.store.db.close()
        main.store = Store(Path(directory))
        main.store.update_settings({'systemone_enabled': True, 'systemone_ark_api_key': 'fixture-only',
            'screen_companion_enabled': True, 'screen_companion_interval_ms': 1000,
            'screen_companion_refresh_ms': 5000, 'screen_companion_cooldown_s': 10,
            'systemone_initiative_enabled': False, 'tts_mode': 'cpu'})
        try:
            await uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=18875, log_level='warning')).serve()
        finally: main.store.db.close()


if __name__ == '__main__': asyncio.run(run())
