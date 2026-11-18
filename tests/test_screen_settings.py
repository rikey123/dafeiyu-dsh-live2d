import math
import pytest
from pydantic import ValidationError
from server.main import SettingsUpdate
from server.storage import DEFAULTS
from server.storage import Store
from server import main
from fastapi.testclient import TestClient


def test_screen_defaults_and_strict_settings():
    assert DEFAULTS['screen_companion_enabled'] is False
    assert DEFAULTS['screen_companion_interval_ms'] == 2500
    assert DEFAULTS['screen_companion_speak_threshold'] == .9
    assert DEFAULTS['screen_request_enabled'] is True
    assert DEFAULTS['screen_request_threshold'] == .75
    assert DEFAULTS['screen_companion_refresh_ms'] == 15000
    assert SettingsUpdate(screen_companion_wait_threshold=0).screen_companion_wait_threshold == 0
    for patch in ({'screen_companion_interval_ms': 1000.0},
                  {'screen_companion_enabled': 1},
                  {'screen_companion_speak_threshold': math.nan},
                  {'screen_companion_change_threshold': math.inf},
                  {'screen_companion_max_reply_chars': 121},
                  {'screen_request_enabled': 1}, {'screen_request_threshold': math.nan},
                  {'screen_companion_refresh_ms': 4999}, {'screen_request_timeout_ms': 5001},
                  {'screen_request_timeout_ms': 2000.0}):
        with pytest.raises(ValidationError):
            SettingsUpdate(**patch)


@pytest.mark.parametrize('threshold', [.5, .65, .777, .8, .9, .99])
def test_screen_speak_threshold_accepts_lower_range(threshold):
    assert SettingsUpdate(screen_companion_speak_threshold=threshold).screen_companion_speak_threshold == threshold


@pytest.mark.parametrize('threshold', [.4999, .9901, math.nan, math.inf, -math.inf, True, '0.5'])
def test_screen_speak_threshold_rejects_out_of_range_and_invalid_types(threshold):
    with pytest.raises(ValidationError):
        SettingsUpdate(screen_companion_speak_threshold=threshold)


def test_screen_lower_threshold_saves_and_survives_reload_without_changing_other_settings(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    try:
        store.update_settings({'screen_companion_speak_threshold': .8})
        with TestClient(main.app) as browser:
            before = browser.get('/api/settings').json()
            assert before['screen_companion_speak_threshold'] == .8
            for threshold in [.4999, .9901, '0.5', True]:
                response = browser.put('/api/settings', json={'screen_companion_speak_threshold': threshold})
                assert response.status_code == 422
                assert browser.get('/api/settings').json()['screen_companion_speak_threshold'] == .8
            for threshold in [.65, .5]:
                response = browser.put('/api/settings', json={'screen_companion_speak_threshold': threshold})
                assert response.status_code == 200
                assert response.json()['screen_companion_speak_threshold'] == threshold
                after = browser.get('/api/settings').json()
                assert after == {**before, 'screen_companion_speak_threshold': threshold}
            # Unrelated saves must not reset the selected threshold to the default.
            assert browser.put('/api/settings', json={'screen_request_timeout_ms': 2500}).status_code == 200
            assert browser.get('/api/settings').json()['screen_companion_speak_threshold'] == .5
    finally:
        store.db.close()
    reloaded = Store(tmp_path)
    try:
        assert reloaded.settings()['screen_companion_speak_threshold'] == .5
    finally:
        reloaded.db.close()


def test_screen_requires_systemone_and_compatible_voice_mode(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    try:
        with TestClient(main.app) as browser:
            assert browser.put('/api/settings', json={'screen_companion_enabled': True}).status_code == 409
            assert browser.put('/api/settings', json={'screen_companion_enabled': True, 'systemone_enabled': True,
                                                      'systemone_ark_api_key': 'fixture-key'}).status_code == 200
            assert browser.put('/api/settings', json={'systemone_enabled': False}).status_code == 409
            assert browser.put('/api/settings', json={'conversation_mode': 'moss_live'}).status_code == 409
            assert browser.put('/api/settings', json={'screen_companion_enabled': False, 'systemone_enabled': False}).status_code == 200
    finally:
        store.db.close()

@pytest.mark.parametrize('style', ['quiet', 'balanced', 'lively'])
def test_screen_style_saves_and_survives_reload(tmp_path, monkeypatch, style):
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    try:
        with TestClient(main.app) as browser:
            assert browser.get('/api/settings').json()['screen_companion_style'] == 'balanced'
            assert browser.put('/api/settings', json={'screen_companion_style': style}).json()['screen_companion_style'] == style
            for invalid in ['other', '', 1, True, [], {}]:
                assert browser.put('/api/settings', json={'screen_companion_style': invalid}).status_code == 422
                assert browser.get('/api/settings').json()['screen_companion_style'] == style
    finally:
        store.db.close()
    reloaded = Store(tmp_path)
    try:
        assert reloaded.settings()['screen_companion_style'] == style
    finally:
        reloaded.db.close()


def test_presence_settings_bounds_and_persistence(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    patch = {'screen_companion_mode': 'direct', 'companion_interests': '画画',
             'idle_companion_enabled': False, 'idle_companion_after_s': 30,
             'idle_companion_cooldown_s': 3600, 'idle_companion_max_per_hour': 1,
             'idle_companion_include_screen': False, 'idle_companion_max_reply_chars': 240}
    try:
        with TestClient(main.app) as browser:
            assert browser.put('/api/settings', json=patch).status_code == 200
            assert browser.put('/api/settings', json={'screen_companion_enabled': True}).status_code == 200
            for invalid in ({'screen_companion_mode': 'unknown'}, {'companion_interests': 'x' * 2001},
                            {'idle_companion_after_s': 29}, {'idle_companion_after_s': 30.0},
                            {'idle_companion_cooldown_s': 3601}, {'idle_companion_max_per_hour': 0},
                            {'idle_companion_max_reply_chars': 241}, {'idle_companion_enabled': 1}):
                assert browser.put('/api/settings', json=invalid).status_code == 422
            public = browser.get('/api/settings').json()
            assert all(public[k] == v for k, v in patch.items())
            assert 'systemone_ark_api_key' not in public
    finally:
        store.db.close()
    reloaded = Store(tmp_path)
    try:
        assert all(reloaded.settings()[k] == v for k, v in patch.items())
    finally:
        reloaded.db.close()


def test_unknown_saved_screen_mode_falls_back_safely(tmp_path):
    store = Store(tmp_path)
    try:
        store.update_settings({'screen_companion_mode': 'future_mode'})
        assert store.settings()['screen_companion_mode'] == 'systemone'
    finally:
        store.db.close()


def test_idle_requires_dsh_for_activation_but_can_be_disabled(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main.dsh, 'enabled', lambda: False)
    try:
        with TestClient(main.app) as browser:
            assert browser.put('/api/settings', json={'idle_companion_enabled': True}).status_code == 409
            store.update_settings({'idle_companion_enabled': True})
            assert browser.put('/api/settings', json={'idle_companion_enabled': False}).status_code == 200
    finally:
        store.db.close()
