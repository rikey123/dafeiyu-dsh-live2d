"""Opt-in isolated gateway for synthetic-browser screen-tool acceptance only."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import uuid

if os.environ.get('DAFEIYU_SCREEN_TOOL_ACCEPTANCE') != '1':
    raise SystemExit('Explicit isolated screen-tool acceptance opt-in required')
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('DAFEIYU_SCREEN_TOOL_QA', 'E:/Dafeiyu/qa/dsh-screen-tool-20261115'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(DAFEIYU_DATA_DIR=str(OUT / 'isolated-store'), DAFEIYU_HARNESS='dsh',
                  DAFEIYU_PLUGIN_TOKEN='screen-tool-fixture-only', DAFEIYU_DSH_ORIGIN='http://127.0.0.1:18876')
sys.path.insert(0, str(ROOT))

import uvicorn
from server import main, pipecat_voice
from server.screen_registry import providers
from speech.pipecat_services import LocalSpeechTTS

sessions = {}


class OfflineBridge:
    async def status(self):
        return {'ready': True, 'configured': True, 'screen_ready': True,
                'model': 'offline-screen-tool-fixture', 'temperature_supported': False}

    async def create_session(self, session_id=None):
        identifier = session_id or 'offline-screen-' + uuid.uuid4().hex
        sessions.setdefault(identifier, [])
        return {'id': identifier, 'title': 'offline screen fixture'}

    async def sessions(self):
        return [{'id': identifier, 'title': 'offline screen fixture'} for identifier in sessions]

    async def messages(self, identifier):
        return sessions.setdefault(identifier, [])

    async def voice_state(self, *args):
        return {'accepted': True}

    async def voice_events(self, *args):
        yield 'offline:0', {'type': 'ready'}
        await asyncio.Event().wait()

    async def voice_turn(self, *args):
        raise AssertionError('No model request is allowed in screen-tool acceptance')


@main.app.get('/api/screen-tool-fixture')
async def fixture_status():
    return {'fixture': True, 'providers': list(providers), 'systemone_enabled': False,
            'screen_request_enabled': False, 'model_requests': 0}


async def run():
    main.dsh.BridgeClient = OfflineBridge
    # No synthesis is requested; any accidental request fails at a closed local port.
    pipecat_voice.create_tts = lambda settings: LocalSpeechTTS(base_url='http://127.0.0.1:1', sample_rate=24000)
    main.store.update_settings({'systemone_enabled': False, 'screen_companion_enabled': True,
                               # Software-rendered Live2D can delay canvas readback in headless Edge.
                               # Use the supported maximum only in this fixture, not production.
                               'screen_request_enabled': False, 'screen_request_timeout_ms': 5000,
                               'screen_companion_interval_ms': 1000, 'tts_mode': 'cpu'})
    main.app.router.routes[:] = sorted(main.app.router.routes,
        key=lambda route: 0 if getattr(route, 'path', '') == '/api/screen-tool-fixture' else 1)
    try:
        await uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=18876, log_level='warning')).serve()
    finally:
        main.store.db.close()


if __name__ == '__main__':
    asyncio.run(run())
