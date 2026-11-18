import json

import httpx
import pytest
from fastapi.testclient import TestClient

from server import main
from server.model_tts_sidecar import create_app
from server.storage import Store
from server.tts_voices import installed_catalog, service_catalog, VoiceCatalogUnavailable, MAX_CATALOG_BYTES


def manifest(tmp_path, *, nested=False, rows=None):
    directory = tmp_path / 'MOSS-TTS-Nano-100M-ONNX' if nested else tmp_path
    directory.mkdir(exist_ok=True)
    rows = rows if rows is not None else [
        {'voice': 'Junhao', 'display_name': 'CN 欢迎关注模思智能', 'group': 'Chinese Male', 'prompt_audio_codes': [[1, 2]], 'audio_file': 'private.wav'},
        {'voice': 'Lingyu', 'display_name': 'CN 深夜电台', 'group': 'Chinese Female', 'prompt_audio_codes': [[3, 4]]},
    ]
    path = directory / 'browser_poc_manifest.json'
    path.write_text(json.dumps({'builtin_voices': rows}, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.mark.parametrize('nested', [False, True])
def test_manifest_uses_same_locations_order_and_default_as_runtime(tmp_path, nested):
    manifest(tmp_path, nested=nested)
    catalog = installed_catalog(tmp_path)
    assert catalog['default_voice'] == 'Junhao'
    assert [v['id'] for v in catalog['voices']] == ['Junhao', 'Lingyu']
    assert all(set(v) == {'id', 'name', 'group'} for v in catalog['voices'])
    assert 'private.wav' not in json.dumps(catalog) and 'prompt_audio_codes' not in json.dumps(catalog)


@pytest.mark.parametrize('rows', [[], {}, [None], [
    {'voice': 'x', 'display_name': 'name', 'group': 'group', 'prompt_audio_codes': []}], [
    {'voice': 'x', 'display_name': 'name', 'group': 'group', 'prompt_audio_codes': [1]},
    {'voice': 'x', 'display_name': 'name', 'group': 'group', 'prompt_audio_codes': [2]}]])
def test_bad_presets_fail_closed(tmp_path, rows):
    manifest(tmp_path, rows=rows)
    with pytest.raises(VoiceCatalogUnavailable):
        installed_catalog(tmp_path)


@pytest.mark.parametrize('raw', [b'not json', b'[]', b'null', b'x' * (MAX_CATALOG_BYTES + 1)])
def test_missing_corrupt_and_oversize_catalog_do_not_leak_paths(tmp_path, raw):
    with pytest.raises(VoiceCatalogUnavailable):
        installed_catalog(tmp_path)
    (tmp_path / 'browser_poc_manifest.json').write_bytes(raw)
    with pytest.raises(VoiceCatalogUnavailable) as exc:
        installed_catalog(tmp_path)
    assert str(tmp_path) not in str(exc.value)


def test_moss_sidecar_catalog_never_starts_inference(tmp_path, monkeypatch):
    manifest(tmp_path)
    app = create_app('moss_tts', {'source': str(tmp_path), 'model': str(tmp_path)})
    async def forbidden(*args):
        raise AssertionError('Catalog queries cannot start inference')
    monkeypatch.setattr(app.state.host, 'prepare', forbidden)
    with TestClient(app) as client:
        response = client.get('/v1/audio/voices')
    assert response.status_code == 200
    assert response.json()['voices'][1]['id'] == 'Lingyu'
    assert app.state.host.process is None


def test_gpu_service_does_not_advertise_cpu_presets(tmp_path):
    app = create_app('index_tts', {'source': str(tmp_path), 'model': str(tmp_path), 'preload': False})
    with TestClient(app) as client:
        assert client.get('/v1/audio/voices').status_code == 404
    assert app.state.host.process is None


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    store = Store(tmp_path / 'database')
    store.update_settings({'tts_mode': 'gpu', 'voice': 'Lingyu'})
    monkeypatch.setattr(main, 'store', store)
    model = tmp_path / 'model'
    model.mkdir(); manifest(model)
    monkeypatch.setenv('DAFEIYU_MOSS_MODEL', str(model))
    with TestClient(main.app) as client:
        yield client, store, model
    store.db.close()


def mock_http(monkeypatch, handler):
    native = httpx.AsyncClient
    monkeypatch.setattr(main.httpx, 'AsyncClient', lambda **kw: native(transport=httpx.MockTransport(handler), **kw))


def test_inactive_managed_cpu_catalog_remains_available_in_gpu_mode(gateway, monkeypatch):
    client, store, _ = gateway
    def stopped(request):
        assert str(request.url) == 'http://127.0.0.1:8772/v1/audio/voices'
        raise httpx.ConnectError('not running', request=request)
    mock_http(monkeypatch, stopped)
    before = store.settings(private=True)
    response = client.get('/api/tts/voices')
    assert response.status_code == 200
    assert response.json()['source'] == 'installed_manifest'
    assert response.json()['default_voice'] == 'Junhao'
    assert store.settings(private=True) == before


def test_live_service_is_authoritative_not_the_gateway_disk(gateway, monkeypatch):
    client, _, _ = gateway
    payload = {'model': 'MOSS-TTS-Nano', 'default_voice': 'Remote', 'voices': [{'id': 'Remote', 'name': 'Other installation', 'group': 'Custom', 'private': 'secret'}]}
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = client.get('/api/tts/voices').json()
    assert result['source'] == 'service' and result['default_voice'] == 'Remote'
    assert 'Junhao' not in json.dumps(result) and 'secret' not in json.dumps(result)


def test_unreachable_custom_service_cannot_use_unrelated_local_presets(gateway, monkeypatch):
    client, store, _ = gateway
    store.update_settings({'moss_tts_url': 'http://127.0.0.1:9999'})
    def stopped(request):
        raise httpx.ConnectError('private details', request=request)
    mock_http(monkeypatch, stopped)
    response = client.get('/api/tts/voices')
    assert response.status_code == 503 and 'private details' not in response.text


@pytest.mark.parametrize('status,payload', [(404, {}), (302, {}), (200, {'model': 'wrong'}), (200, {'model': 'MOSS-TTS-Nano', 'default_voice': 'missing', 'voices': [{'id': 'x', 'name': 'x', 'group': 'x'}]})])
def test_invalid_service_catalog_is_not_hidden_with_local_fallback(gateway, monkeypatch, status, payload):
    client, _, _ = gateway
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=payload, headers={'location': 'https://example.invalid'}))
    assert client.get('/api/tts/voices').status_code == 503


def test_catalog_respects_origin_guard(gateway):
    client, _, _ = gateway
    assert client.get('/api/tts/voices', headers={'origin': 'https://evil.invalid'}).status_code == 403
