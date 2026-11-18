import asyncio

import httpx
import pytest

from server.dsh import BridgeClient, BridgeUnavailable


@pytest.mark.parametrize("url", ["http://example.com:1234", "https://127.0.0.1:1234", "http://127.0.0.1:1234/path", "http://user:pass@127.0.0.1:1234", "http://127.0.0.1:1234?x=1"])
def test_bridge_rejects_non_loopback_or_unsafe_url(url):
    with pytest.raises(BridgeUnavailable):
        BridgeClient(url, "secret")


def test_bridge_auth_and_no_redirect():
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "http://example.com/"})
    async def run():
        client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
        with pytest.raises(BridgeUnavailable, match="DSH bridge request failed"):
            await client.status()
    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer secret"


def test_stream_closed_on_cancellation():
    closed = []
    entered = asyncio.Event()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""
        async def aclose(self):
            closed.append(True)
    async def handler(request):
        return httpx.Response(200, stream=Stream())
    async def run():
        client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
        async def consume():
            async with client.stream_chat({"stream": True}) as response:
                async for _ in response.aiter_bytes():
                    pass
        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True]
    asyncio.run(run())
