"""Private, single-attempt transport for the DSH host bridge.

This module deliberately does not own a harness, credentials for a model, or
persistent conversation state. Closing the native voice event stream only
detaches the listener; it does not cancel a host generation.
"""
from __future__ import annotations

import ipaddress
import asyncio
import json as json_module
import os
from contextlib import aclosing, asynccontextmanager
from urllib.parse import quote, urlsplit

import httpx


def enabled() -> bool:
    return os.environ.get("DAFEIYU_HARNESS") == "dsh"


class BridgeUnavailable(Exception):
    """A sanitized bridge error, safe to return to callers."""
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code if status_code in {400, 404, 409, 410, 422} else 503


class AgentTaskError(Exception):
    """A host-reported agent task failure, independent of voice transport."""


def _agent_error(payload):
    if not isinstance(payload, dict):
        return False
    error = payload.get("error", payload)
    return isinstance(error, dict) and error.get("code") == "AGENT_ERROR"


class BridgeClient:
    def __init__(self, url: str | None = None, token: str | None = None, *, transport=None):
        url = url if url is not None else os.environ.get("DAFEIYU_DSH_BRIDGE_URL", "")
        token = token if token is not None else os.environ.get("DAFEIYU_DSH_BRIDGE_TOKEN", "")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            loopback = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
            valid = (parsed.scheme == "http" and loopback and parsed.port is not None
                     and not parsed.username and not parsed.password and not parsed.query
                     and not parsed.fragment and parsed.path in ("", "/"))
        except ValueError:
            valid = False
        if not valid or not token or any(c in token for c in "\r\n"):
            raise BridgeUnavailable("DSH bridge configuration unavailable")
        self._url = url.rstrip("/")
        self._token = token
        self._transport = transport

    def _client(self):
        return httpx.AsyncClient(base_url=self._url, headers={"Authorization": "Bearer " + self._token},
                                 trust_env=False, follow_redirects=False, timeout=60,
                                 transport=self._transport)

    async def request(self, method: str, path: str, *, json=None):
        try:
            async with self._client() as client:
                response = await client.request(method, path, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            raise BridgeUnavailable("DSH bridge request failed", exc.response.status_code) from None
        except (httpx.HTTPError, ValueError):
            raise BridgeUnavailable("DSH bridge request failed") from None

    async def status(self):
        return await self.request("GET", "/v1/status")

    async def sessions(self):
        return await self.request("GET", "/v1/sessions")

    async def create_session(self, session_id=None):
        return await self.request("POST", "/v1/sessions", json={"session_id": session_id} if session_id else {})

    async def messages(self, session_id):
        return await self.request("GET", "/v1/sessions/" + quote(session_id, safe="") + "/messages")

    async def delete_session(self, session_id):
        return await self.request("DELETE", "/v1/sessions/" + quote(session_id, safe=""))

    async def playback(self, session_id, generation_id, text, interrupted=False):
        return await self.request("POST", "/v1/playback", json={"session_id": session_id,
            "generation_id": generation_id, "text": text, "interrupted": interrupted})

    async def voice_turn(self, body):
        result = await self.request("POST", "/v1/voice/turns", json=body)
        if not isinstance(result, dict) or result.get("accepted") is not True or result.get("request_id") != body["dafeiyu"]["request_id"]:
            raise BridgeUnavailable("DSH voice admission failed")
        return result

    async def voice_state(self, session_id, connection_id, active, microphone=False):
        return await self.request("POST", "/v1/voice/state", json={"session_id": session_id,
            "connection_id": connection_id, "active": active, "microphone": microphone})

    async def voice_context(self, session_id):
        result = await self.request("GET", "/v1/voice/context?session_id=" + quote(session_id, safe=""))
        if not isinstance(result, dict) or not isinstance(result.get("persona"), str) or not isinstance(result.get("messages"), list):
            raise BridgeUnavailable("DSH voice context invalid")
        return result

    async def voice_observation(self, session_id, event_id, role, text, revised=False):
        result = await self.request("POST", "/v1/voice/observations", json={"session_id":session_id,
            "event_id":event_id, "role":role, "text":text, "revised":revised})
        if not isinstance(result, dict) or result.get("accepted") is not True:
            raise BridgeUnavailable("DSH voice observation failed")
        return result

    async def voice_events(self, session_id, cursor=None):
        """One SSE connection. The caller owns bounded reconnection and its cursor."""
        headers = {"Last-Event-ID": cursor} if cursor else {}
        try:
            async with self._client() as client:
                async with client.stream("GET", "/v1/voice/events", params={"session_id": session_id},
                                         headers=headers, timeout=httpx.Timeout(60, read=None)) as response:
                    response.raise_for_status()
                    if "text/event-stream" not in response.headers.get("content-type", "").lower():
                        raise BridgeUnavailable("DSH voice event stream invalid")
                    event_id, data = None, []
                    async for line in response.aiter_lines():
                        if line:
                            field, _, value = line.partition(":")
                            value = value.removeprefix(" ")
                            if field == "id" and "\x00" not in value:
                                event_id = value
                            elif field == "data":
                                data.append(value)
                            continue
                        if data:
                            try:
                                event = json_module.loads("\n".join(data))
                                if not isinstance(event, dict) or not event_id or len(event_id) > 256:
                                    raise ValueError
                            except (ValueError, TypeError):
                                raise BridgeUnavailable("DSH voice event stream invalid") from None
                            yield event_id, event
                        event_id, data = None, []
        except httpx.HTTPError:
            raise BridgeUnavailable("DSH voice event stream unavailable") from None

    @asynccontextmanager
    async def stream_chat(self, body):
        try:
            async with self._client() as client:
                async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                    # A task can fail before the first token, so the native
                    # bridge returns coded JSON with an error HTTP status rather
                    # than opening SSE. Preserve the same task/transport split.
                    if response.is_error and "application/json" in response.headers.get("content-type", "").lower():
                        try:
                            payload = json_module.loads(await response.aread())
                        except (ValueError, TypeError):
                            payload = None
                        if _agent_error(payload):
                            raise AgentTaskError("DSH agent task failed")
                    response.raise_for_status()
                    yield response
        except httpx.HTTPError:
            raise BridgeUnavailable("DSH bridge request failed") from None

    async def chat_text(self, body):
        """Read OpenAI SSE, allowing intentional empty idle and direct previews."""
        meta = body.get("dafeiyu", {}) if isinstance(body, dict) else {}
        allow_empty = isinstance(meta, dict) and (meta.get("kind") == "idle" or
            (meta.get("kind") == "screen" and meta.get("screen_mode") == "direct"))
        async with self.stream_chat(body) as response:
            if "text/event-stream" not in response.headers.get("content-type", "").lower():
                try:
                    result = json_module.loads(await response.aread())
                    if _agent_error(result):
                        raise AgentTaskError("DSH agent task failed")
                    if not isinstance(result, dict) or result.get("error") is not None:
                        raise ValueError
                    text = result["choices"][0]["message"]["content"]
                    if not isinstance(text, str) or (not text.strip() and not allow_empty):
                        raise ValueError
                except (ValueError, KeyError, IndexError, TypeError):
                    raise BridgeUnavailable("DSH bridge response invalid or empty") from None
                if text.strip():
                    yield text
                return

            spoken = False
            event, data = "", []
            async for line in response.aiter_lines():
                if line:
                    field, _, value = line.partition(":")
                    value = value.removeprefix(" ")
                    if field == "event":
                        event = value
                    elif field == "data":
                        data.append(value)
                    continue
                if event == "error":
                    try:
                        error_payload = json_module.loads("\n".join(data))
                    except (ValueError, TypeError):
                        error_payload = None
                    if _agent_error(error_payload):
                        raise AgentTaskError("DSH agent task failed")
                    raise BridgeUnavailable("DSH bridge generation failed")
                if not data:
                    event = ""
                    continue
                payload = "\n".join(data)
                event, data = "", []
                if payload.strip() == "[DONE]":
                    if not spoken and not allow_empty:
                        raise BridgeUnavailable("DSH bridge response empty")
                    return
                try:
                    chunk = json_module.loads(payload)
                    if _agent_error(chunk):
                        raise AgentTaskError("DSH agent task failed")
                    if not isinstance(chunk, dict) or chunk.get("error") is not None:
                        raise ValueError
                    choices = chunk.get("choices")
                    if not isinstance(choices, list):
                        raise ValueError
                    for choice in choices:
                        if not isinstance(choice, dict) or choice.get("finish_reason") in {"error", "content_filter"}:
                            raise ValueError
                        delta = choice.get("delta", {})
                        if not isinstance(delta, dict):
                            raise ValueError
                        text = delta.get("content")
                        if text is not None and not isinstance(text, str):
                            raise ValueError
                        if text and (not allow_empty or spoken or text.strip()):
                            spoken = spoken or bool(text.strip())
                            yield text
                except (ValueError, TypeError):
                    raise BridgeUnavailable("DSH bridge generation failed") from None
            # EOF is not a successful finish, even after text or a finish_reason.
            raise BridgeUnavailable("DSH bridge stream ended before DONE")


class ProjectionStore:
    """Ephemeral, connection-scoped playback projection; never writes history to disk."""
    is_dsh_projection = True

    def __init__(self, settings_store, session_id, messages, bridge, model="dsh", temperature_supported=False):
        import uuid
        self.settings_store = settings_store
        self.session_id = session_id
        self.bridge = bridge
        self.model = model
        self.temperature_supported = temperature_supported
        self.rows = [{"id": str(row.get("id") or uuid.uuid4().hex), "role": row["role"],
                      "content": row["content"]} for row in messages
                     if isinstance(row, dict) and row.get("role") in {"user", "assistant"}
                     and isinstance(row.get("content"), str)]
        self._queue = None
        self._worker = None
        self._close_task = None
        self._closing = False
        self._native_user_ids = set()

    def observe_native_user(self, message_id, text, local_id=None):
        """Reconcile a native public message into acoustic context, not history storage."""
        if message_id in self._native_user_ids:
            return False
        self._native_user_ids.add(message_id)
        if len(self._native_user_ids) > 512:
            self._native_user_ids = {row.get("native_id", row["id"]) for row in self.rows[-160:]}
            self._native_user_ids.add(message_id)
        for row in self.rows:
            if row["id"] == local_id and row["role"] == "user":
                row["native_id"] = message_id
                return False
        self.rows.append({"id": message_id, "native_id": message_id, "role": "user", "content": text})
        self.rows = self.rows[-160:]
        return True

    def settings(self, *, private=False):
        return self.settings_store.settings(private=private)

    def memories(self):
        return []

    def messages(self, session_id):
        return [dict(row) for row in self.rows if row["content"]]

    def add_message(self, session_id, role, content, interrupted=False):
        import uuid
        row = {"id": uuid.uuid4().hex, "role": role, "content": content}
        self.rows.append(row)
        self.rows = self.rows[-160:]
        return row["id"]

    def update_message(self, message_id, session_id, content):
        for row in self.rows:
            if row["id"] == message_id:
                row["content"] = content
                return True
        return False

    revise_user_message = update_message

    def delete_empty_assistant(self, message_id, session_id):
        self.rows[:] = [row for row in self.rows if not (row["id"] == message_id and not row["content"])]

    def enqueue_playback(self, generation_id, text, interrupted=False):
        if self._closing:
            return
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._worker = asyncio.create_task(self._flush())
        self._queue.put_nowait((generation_id, text, interrupted))

    async def _flush(self):
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                try:
                    await self.bridge.playback(self.session_id, *item)
                except BridgeUnavailable:
                    # No retry: the host may already have applied this projection.
                    pass
            finally:
                self._queue.task_done()

    async def close(self):
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        if self._worker:
            self._queue.put_nowait(None)
            try:
                await asyncio.wait_for(self._worker, 5)
            except asyncio.TimeoutError:
                self._worker.cancel()
                await asyncio.gather(self._worker, return_exceptions=True)


def chat_body(session_id, request_id, kind, persona, confirmed_messages, messages, *, model="", temperature=0.7, stream=True):
    body = {"model": model, "messages": messages, "stream": stream,
            "dafeiyu": {"session_id": session_id, "request_id": request_id, "kind": kind,
                        "persona": persona, "confirmed_messages": confirmed_messages}}
    if temperature is not None:
        body["temperature"] = temperature
    return body


async def completion_text(bridge, body):
    async with aclosing(bridge.chat_text(body)) as chunks:
        return "".join([text async for text in chunks])
