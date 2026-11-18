"""Offline bridge protocol failures must never look like a successful empty turn."""
import asyncio

import httpx
import pytest

from server.dsh import AgentTaskError, BridgeClient, BridgeUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    'event: error\ndata: {"message":"bridge-secret"}\n\ndata: [DONE]\n\n',
    'data: {"error":{"message":"bridge-secret"}}\n\ndata: [DONE]\n\n',
    'data: [DONE]\n\n',
    '',
    'data: {"choices":[{"delta":{"content":" "}}]}\n\ndata: [DONE]\n\n',
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"stop"}]}\n\n',
    'data: {"choices":{}}\n\ndata: [DONE]\n\n',
    'data: {"choices":[{"delta":null}]}\n\ndata: [DONE]\n\n',
    'data: not-json\n\ndata: [DONE]\n\n',
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\ndata: {"error":"bridge-secret"}\n\ndata: [DONE]\n\n',
])
async def test_sse_errors_empty_and_truncated_responses_fail_without_retry(payload):
    calls, closed = [], []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self): yield payload.encode()
        async def aclose(self): closed.append(True)
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())
    client = BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(BridgeUnavailable) as exc:
        async for _ in client.chat_text({"stream": True}):
            pass
    assert "bridge-secret" not in str(exc.value)
    assert len(calls) == 1 and closed == [True]


@pytest.mark.asyncio
async def test_sse_multiline_comments_usage_and_done_close_immediately():
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b': keepalive\r\nevent: message\r\ndata: {"choices":\r\ndata: [{"delta":{"content":"hello"}}]}\r\n\r\n'
            yield b'data: {"choices":[],"usage":{"total_tokens":1}}\n\ndata: [DONE]\n\n'
            await asyncio.Event().wait()
        async def aclose(self): closed.append(True)
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    async with asyncio.timeout(1):
        assert [text async for text in client.chat_text({})] == ["hello"]
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": {"message": "secret"}}, {"choices": []},
    {"error": {"message": "secret"}, "choices": [{"message": {"content": "discard"}}]},
    {"choices": [{"message": {"content": ""}}]}, {"choices": [{"message": {"content": None}}]}])
async def test_json_completion_cannot_succeed_without_text(body):
    async def handler(request): return httpx.Response(200, json=body)
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(BridgeUnavailable):
        _ = [text async for text in client.chat_text({})]


def test_bridge_client_disables_environment_proxies_and_redirects():
    client = BridgeClient("http://127.0.0.1:1234", "secret")._client()
    assert not client.trust_env and not client.follow_redirects
    asyncio.run(client.aclose())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    'event: error\ndata: {"code":"AGENT_ERROR","message":"private"}\n\n',
    'data: {"error":{"code":"AGENT_ERROR","message":"private"}}\n\n',
])
async def test_explicit_agent_task_failure_is_distinct_from_transport(payload):
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=payload)
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentTaskError, match="DSH agent task failed"):
        _ = [text async for text in client.chat_text({})]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 500, 503])
async def test_json_explicit_agent_task_failure_is_distinct_from_transport(status):
    async def handler(request):
        return httpx.Response(status, json={"error": {"code": "AGENT_ERROR", "message": "private"}})
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentTaskError, match="DSH agent task failed"):
        _ = [text async for text in client.chat_text({})]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [
    (401, {"error": {"message": "private"}}),
    (403, {"error": {"code": "DSH_UNAVAILABLE", "message": "private"}}),
    (503, {"error": {"message": "AGENT_ERROR private"}}),
    (503, {"error": {"code": "VOICE_STREAM_GAP", "message": "private"}}),
])
async def test_uncoded_or_transport_http_failures_are_not_silenced(status, payload):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(BridgeUnavailable) as exc:
        _ = [text async for text in client.chat_text({})]
    assert "private" not in str(exc.value) and "secret" not in str(exc.value)
    assert len(calls) == 1
