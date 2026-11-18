import asyncio

import pytest

from server import main
from server.storage import Store


@pytest.mark.asyncio
async def test_rejected_socket_close_does_not_block_other_voice_sessions(tmp_path, monkeypatch):
    from server import pipecat_voice

    store = Store(tmp_path)
    busy = store.session(None)
    other = store.session(None)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "active_sessions", {busy})
    monkeypatch.setattr(main, "active_voice_sockets", {})
    monkeypatch.setattr(main, "voice_policy_lock", asyncio.Lock())
    closing, release, connected = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Socket:
        headers = {}

        async def accept(self):
            pass

        async def close(self, **kwargs):
            closing.set()
            await release.wait()

    async def run_voice(*args):
        connected.set()

    monkeypatch.setattr(pipecat_voice, "run_voice", run_voice)
    rejecting = asyncio.create_task(main.voice(Socket(), busy))
    await closing.wait()
    joining = asyncio.create_task(main.voice(Socket(), other))
    try:
        await asyncio.wait_for(connected.wait(), timeout=.3)
        assert busy in main.active_sessions  # a rejected peer must not evict its owner
    finally:
        release.set()
        await asyncio.gather(rejecting, joining)


@pytest.mark.asyncio
async def test_policy_change_has_bounded_close_wait(monkeypatch):
    release = asyncio.Event()

    class Socket:
        async def close(self, **kwargs):
            await release.wait()

    monkeypatch.setattr(main, "active_voice_sockets", {"slow": Socket()})
    monkeypatch.setattr(main, "VOICE_CLOSE_TIMEOUT", .02, raising=False)
    try:
        await asyncio.wait_for(main.close_old_voice_sessions(), timeout=.3)
    finally:
        release.set()
        await asyncio.sleep(0)
