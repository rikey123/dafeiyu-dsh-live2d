import asyncio
import base64
import io
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from server import main
from server.storage import Store
from server.systemone import AFFECT_QUESTIONS, TURN_QUESTIONS, SystemOneClient
from server.systemone_providers import ARK_MODEL, provider_for


def answer(questions, model=ARK_MODEL):
    answers = {}
    for name, question in questions.items():
        kind = question['type']
        if kind == 'noul':
            answers[name] = {'type': kind, 'noul': .9 if name == 'interrupt' else .05}
        else:
            keys = list(question['criteria']) if kind == 'choice' else [str(i) for i in range(len(question['criteria']))]
            answers[name] = {'type': kind, kind: keys[0] if kind == 'choice' else 0,
                             'confidence': .9, 'probabilities': {key: 1 if i == 0 else 0 for i, key in enumerate(keys)}}
    return {'model': model, 'answers': answers, 'usage': {'input_tokens': 30, 'output_tokens': 0}}


def make_client(handler, **settings):
    return SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': 'ark-test-key',
                            'systemone_api_key': 'never-send-this-clef-key', **settings}, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize('model', [ARK_MODEL, 'ep-20261114-fixture'])
async def test_exact_ark_audio_wire_contract_and_resolved_model(model):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=answer(TURN_QUESTIONS))
    client = make_client(handle, systemone_ark_model=model)
    try:
        result = await client.turn('请停一下', bytes(32000 * 8), [], True)
        assert result.interrupt == .9 and result.backchannel == .05
        request = requests[0]
        assert str(request.url) == 'https://ark.cn-beijing.volces.com/api/v1/systemone'
        assert request.headers['ark-beta-systemone-api'] == 'true'
        assert request.headers['Authorization'] == 'Bearer ark-test-key'
        assert 'Idempotency-Key' not in request.headers
        body = json.loads(request.content)
        assert set(body) == {'model', 'state', 'questions'} and body['model'] == model
        text, audio = body['state']
        assert text == {'type': 'text', 'text': {'user_text': '请停一下', 'assistant_speaking': True, 'recent_dialogue': []}}
        assert audio['type'] == 'audio' and audio['audio_url'].startswith('data:audio/wav;base64,')
        with wave.open(io.BytesIO(base64.b64decode(audio['audio_url'].split(',', 1)[1]))) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 16000, 64000)
        client.audio_enabled = False
        await client.turn('文字', b'\0\0', [], False)
        assert isinstance(json.loads(requests[-1].content)['state'], dict)
        assert client.source == 'doubao-systemone'
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,reason', [('disconnect', 'network'), ('pending', 'http_error'), ('conflict', 'http_error')])
async def test_ark_never_reposts_or_invents_results_endpoint(failure, reason):
    seen = []
    def handle(request):
        seen.append(request)
        if failure == 'disconnect':
            raise httpx.ReadError('private provider text', request=request)
        return httpx.Response(202 if failure == 'pending' else 409, json={'status': 'pending'})
    client = make_client(handle)
    try:
        assert await client.affect('测试', []) is None
        assert client.last_reason == reason
        assert [request.method for request in seen] == ['POST']
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,reason', [
    (403, 'model_not_supported_in_region', 'region_restricted'),
    (403, 'Forbidden', 'permission_denied'), (401, 'Unauthorized', 'authentication'),
    (403, 'ModelNotOpen', 'model_not_open'), (404, 'InvalidEndpointOrModel.NotFound', 'endpoint_not_found'),
    (429, 'RateLimitExceeded', 'rate_limit'), (402, 'AccountOverdue', 'billing'),
    (400, 'InvalidParameter', 'invalid_request'), (500, ['untrusted'], 'http_error'),
])
async def test_sanitized_errors_distinguish_region_permission_and_credentials(status, code, reason):
    client = make_client(lambda _: httpx.Response(status, json={'error': {'code': code, 'message': 'private ark-test-key'}}))
    try:
        assert await client.affect('测试', []) is None
        assert client.last_reason == reason
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['model', 'choice', 'score', 'confidence'])
async def test_ark_rejects_unrelated_model_and_inconsistent_probabilities(kind):
    payload = answer(AFFECT_QUESTIONS)
    if kind == 'model': payload['model'] = 'unrelated-model'
    if kind == 'choice': payload['answers']['emotion']['choice'] = 'sad'
    if kind == 'score': payload['answers']['energy']['score'] = 2
    if kind == 'confidence': del payload['answers']['energy']['confidence']
    client = make_client(lambda _: httpx.Response(200, json=payload))
    try:
        assert await client.affect('测试', []) is None
        assert client.last_reason == 'invalid_response'
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shared_client_reason_is_task_local():
    success = asyncio.Event()
    async def handle(request):
        if json.loads(request.content)['state']['assistant_text'] == 'fail':
            return httpx.Response(403, json={})
        return httpx.Response(200, json=answer(AFFECT_QUESTIONS))
    client = make_client(handle)
    async def failing():
        await client.affect('fail', [])
        await success.wait()
        return client.last_reason
    async def succeeding():
        await asyncio.sleep(.01)
        await client.affect('success', [])
        success.set()
        return client.last_reason
    try:
        assert await asyncio.gather(failing(), succeeding()) == ['permission_denied', 'ok']
    finally:
        await client.close()


def test_provider_config_separates_credentials_and_preserves_legacy(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    with TestClient(main.app) as browser:
        assert browser.get('/api/settings').json()['systemone_provider'] == 'ark'
        assert browser.put('/api/settings', json={'systemone_enabled': True, 'systemone_api_key': 'clef-secret'}).status_code == 409
        saved = browser.put('/api/settings', json={'systemone_enabled': True, 'systemone_ark_api_key': 'ark-secret', 'systemone_ark_model': 'ep-my-endpoint'})
        assert saved.status_code == 200 and saved.json()['systemone_ark_api_key_set']
        assert 'ark-secret' not in saved.text and 'systemone_ark_api_key' not in saved.json()
        assert browser.put('/api/settings', json={'systemone_provider': 'tokentosea'}).status_code == 409
        assert browser.put('/api/settings', json={'systemone_api_key': 'clef-secret'}).status_code == 200
        assert browser.put('/api/settings', json={'systemone_provider': 'tokentosea'}).status_code == 200
        assert provider_for(store.settings(private=True)).key == 'clef-secret'
        # Removing an inactive provider's key does not disable the selected one.
        assert browser.put('/api/settings', json={'clear_systemone_ark_api_key': True}).status_code == 200
        assert not store.settings()['systemone_ark_api_key_set']
        assert browser.put('/api/settings', json={'systemone_provider': 'ark'}).status_code == 409
        assert browser.put('/api/settings', json={'systemone_enabled': False, 'systemone_provider': 'ark'}).status_code == 200
        assert browser.post('/api/systemone/test').status_code == 409
        for patch in [{'systemone_provider': 'custom'}, {'systemone_ark_model': 'https://untrusted.test'}, {'systemone_ark_api_key': 'secret\nbad'}]:
            rejected = browser.put('/api/settings', json=patch)
            assert rejected.status_code == 422 and 'secret' not in rejected.text
        assert browser.put('/api/settings', json={'systemone_ark_api_key': 'replacement', 'clear_systemone_ark_api_key': True}).status_code == 422
    store.db.close()


def test_legacy_store_is_not_silently_migrated_to_another_provider(tmp_path):
    store = Store(tmp_path)
    store.update_settings({'systemone_api_key': 'legacy-secret', 'systemone_enabled': True})
    settings = store.settings(private=True)
    assert settings['systemone_provider'] == 'tokentosea'
    assert provider_for(settings).key == 'legacy-secret'
    assert 'legacy-secret' not in repr(provider_for(settings))
    store.db.close()


def test_ark_connectivity_route_uses_saved_provider_and_redacts_key(tmp_path, monkeypatch):
    import server.systemone as module
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    store.update_settings({'systemone_provider': 'ark', 'systemone_ark_api_key': 'ark-secret'})
    original = module.SystemOneClient
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=answer(AFFECT_QUESTIONS))
    monkeypatch.setattr(module, 'SystemOneClient', lambda settings: original(settings, transport=httpx.MockTransport(handler)))
    with TestClient(main.app) as browser:
        browser.get('/api/settings')
        assert not seen
        response = browser.post('/api/systemone/test')
        assert response.status_code == 200 and response.json()['ok']
        assert response.json()['provider'] == 'ark' and response.json()['model'] == ARK_MODEL
        assert 'ark-secret' not in response.text and len(seen) == 1
    store.db.close()
