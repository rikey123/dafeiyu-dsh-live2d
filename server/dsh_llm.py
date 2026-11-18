"""Pipecat adapter for a DSH-owned streaming generation."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import aclosing

import anyio

from pipecat.frames.frames import (LLMContextFrame, LLMFullResponseStartFrame,
                                  LLMFullResponseEndFrame, LLMTextFrame, InterruptionFrame, StartFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .dsh import AgentTaskError, BridgeUnavailable, chat_body


class DSHLLMService(FrameProcessor):
    def __init__(self, store, session_id, settings, initiative=lambda: False, notify=None):
        super().__init__()
        self.store, self.session_id, self.settings, self.initiative = store, session_id, settings, initiative
        self.connection_id = uuid.uuid4().hex
        self._listener = None
        self._cursor = None
        self._generation = None
        self._suppressed = set()
        self._microphone = False
        self._ready = asyncio.Event()
        self._pipeline_started = asyncio.Event()
        self._notify = notify
        self._pending_users = {}
        self._active_requests = set()
        self._suppressed_requests = set()
        self._preview_generations = set()

    def is_preview(self, generation):
        return generation in self._preview_generations

    async def start_listening(self):
        await self.store.bridge.voice_state(self.session_id, self.connection_id, True, False)
        self._listener = asyncio.create_task(self._listen())
        try:
            await asyncio.wait_for(self._ready.wait(), 10)
        except BaseException:
            await self.close_listening()
            raise

    async def set_microphone(self, active):
        self._microphone = active
        await self.store.bridge.voice_state(self.session_id, self.connection_id, True, active)

    async def close_listening(self):
        # The websocket's cancellation scope must not interrupt inactive cleanup.
        with anyio.move_on_after(5, shield=True):
            self._ready.clear()
            if self._listener:
                self._listener.cancel()
                await asyncio.gather(self._listener, return_exceptions=True)
                self._listener = None
            try:
                await self.store.bridge.voice_state(self.session_id, self.connection_id, False, False)
            except BridgeUnavailable:
                pass

    async def _listen(self):
        delay = 0.25
        while True:
            try:
                async for cursor, event in self.store.bridge.voice_events(self.session_id, self._cursor):
                    if event.get("type") == "ready":
                        if self._cursor is None:
                            self._cursor = cursor
                        self._ready.set()
                    else:
                        await self._pipeline_started.wait()
                        await self._event(event)
                        self._cursor = cursor
                    delay = 0.25
            except BridgeUnavailable:
                pass
            finally:
                self._ready.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)

    async def _event(self, event):
        request_id = event.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or not request_id or len(request_id) > 256):
            return
        if event.get("type") == "conversation.user":
            message_id, text, request_id = event.get("message_id"), event.get("text"), event.get("request_id")
            if isinstance(request_id, str) and request_id:
                self._active_requests.add(request_id)
            if isinstance(message_id, str) and message_id and len(message_id) <= 256 and isinstance(text, str) and 0 < len(text) <= 50000:
                added = self.store.observe_native_user(message_id, text, self._pending_users.pop(request_id, None))
                if added and self._notify:
                    await self._notify({"type":"voice.native.user", "text":text, "message_id":message_id})
            return
        if event.get("type") == "turn.end":
            request_id = event.get("request_id")
            self._active_requests.discard(request_id)
            self._suppressed_requests.discard(request_id)
            self._pending_users.pop(request_id, None)
            return
        if event.get("type") == "reset":
            generation = self._generation
            self._generation = None
            self._suppressed.clear()
            self._active_requests.clear()
            self._suppressed_requests.clear()
            self._pending_users.clear()
            if generation:
                await self.push_error(error_msg="DSH voice event history unavailable")
                frame = LLMFullResponseEndFrame()
                frame.metadata["generation_id"] = generation
                await self.push_frame(frame)
            return
        kind, generation, typ = event.get("kind"), event.get("generation_id"), event.get("type")
        if not isinstance(generation, str) or not generation or len(generation) > 256 or not isinstance(kind, str) or not kind or len(kind) > 128:
            return
        if typ == "response.start":
            self._generation = generation
            if event.get("request_id") in self._suppressed_requests:
                self._suppressed.add(generation)
                return
            self._suppressed.discard(generation)
            frame = LLMFullResponseStartFrame()
            frame.metadata.update(generation_id=generation, dsh_request_id=generation, kind=kind)
            await self.push_frame(frame)
        elif typ == "response.text" and generation == self._generation and generation not in self._suppressed:
            text = event.get("text")
            if isinstance(text, str) and text:
                frame = LLMTextFrame(text)
                frame.metadata["generation_id"] = generation
                await self.push_frame(frame)
        elif typ in {"response.end", "response.error"}:
            if generation == self._generation:
                if generation not in self._suppressed:
                    if typ == "response.error" and event.get("code") == "VOICE_STREAM_GAP":
                        await self.push_error(error_msg="DSH voice stream has missing or out-of-order text")
                    frame = LLMFullResponseEndFrame()
                    frame.metadata["generation_id"] = generation
                    await self.push_frame(frame)
                self._generation = None
            self._suppressed.discard(generation)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            if self._generation:
                self._suppressed.add(self._generation)
            self._suppressed_requests.update(self._active_requests)
            self._suppressed_requests.update(self._pending_users)
        if direction != FrameDirection.DOWNSTREAM or not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM and isinstance(frame, StartFrame):
                self._pipeline_started.set()
            return
        messages = [dict(m) for m in frame.context.messages if isinstance(m, dict)]
        if not messages or messages[-1].get("role") != "user":
            await self.push_error(error_msg="DSH request requires a user message")
            return
        screen = frame.metadata.get("dafeiyu_screen")
        idle = frame.metadata.get("dafeiyu_idle")
        if screen and not frame.metadata.get("dafeiyu_screen_valid", lambda: False)():
            frame.metadata.get("dafeiyu_screen_rejected", lambda: None)()
            return
        if idle and not frame.metadata.get("dafeiyu_idle_valid", lambda: False)():
            frame.metadata.get("dafeiyu_idle_rejected", lambda: None)()
            return
        if not screen and not idle and not frame.metadata.get("dafeiyu_request_current", lambda: True)():
            return
        kind = "screen" if screen else "idle" if idle else "initiative" if self.initiative() else "normal"
        history = [{"role": row["role"], "content": row["content"]} for row in self.store.messages(self.session_id)
                   if row["role"] in {"user", "assistant"} and row["content"]]
        # Ordinary snapshot already contains the current user, whereas an
        # initiative partial is never saved into the projection.
        if kind == "normal" and history and history[-1] == messages[-1]:
            history.pop()
        request_id = uuid.uuid4().hex
        body = chat_body(self.session_id, request_id, kind, self.settings["system_prompt"], history, messages,
                         model=self.store.model, temperature=self.settings["temperature"] if self.store.temperature_supported else None)
        if kind == "initiative":
            body["dafeiyu"]["max_reply_chars"] = self.settings.get("systemone_initiative_max_reply_chars", 48)
        elif kind == "screen":
            body["dafeiyu"]["images"] = [screen["image"]]
            body["dafeiyu"]["screen_mode"] = screen.get("screen_mode", "systemone")
            body["dafeiyu"]["companion_interests"] = self.settings.get("companion_interests", "")[:2000]
            if body["dafeiyu"]["screen_mode"] != "direct":
                body["dafeiyu"]["max_reply_chars"] = screen["max_reply_chars"]
        elif kind == "idle":
            if idle.get("image"):
                body["dafeiyu"]["images"] = [idle["image"]]
            body["dafeiyu"]["max_reply_chars"] = min(240, idle["max_reply_chars"])
            body["dafeiyu"]["companion_interests"] = self.settings.get("companion_interests", "")[:2000]
        elif kind == "normal":
            image = frame.metadata.get("dafeiyu_requested_screen")
            state = frame.metadata.get("dafeiyu_screen_state", "not_shared")
            if image and frame.metadata.get("dafeiyu_requested_screen_valid", lambda: False)():
                body["dafeiyu"]["images"] = [image]
                state = "attached"
            elif image:
                state = "not_shared"
            body["dafeiyu"]["screen_state"] = state
        if kind != "normal":
            self._preview_generations.add(request_id)
            if len(self._preview_generations) > 256:
                self._preview_generations = {request_id}
            started = False
            if kind == 'initiative' or (screen and screen.get('screen_mode', 'systemone') != 'direct'):
                start = LLMFullResponseStartFrame()
                start.metadata.update(generation_id=request_id, dsh_request_id=request_id, kind=kind)
                await self.push_frame(start)
                started = True
            try:
                async with aclosing(self.store.bridge.chat_text(body)) as chunks:
                    async for text in chunks:
                        name = 'idle' if idle else 'screen'
                        # Freshness was checked before this native request was
                        # submitted. The screen decision timeout is NOT a DSH
                        # generation/first-token timeout: reusing it here would
                        # silently discard perfectly valid slower model replies.
                        # Ongoing speech still honors actual share/input/stop
                        # invalidation, with the bridge's own bounded timeout.
                        valid = frame.metadata.get(f'dafeiyu_{name}_current',
                            frame.metadata.get(f'dafeiyu_{name}_valid', lambda: True))
                        if not valid():
                            break
                        if not started:
                            start = LLMFullResponseStartFrame()
                            start.metadata.update(generation_id=request_id, dsh_request_id=request_id, kind=kind)
                            await self.push_frame(start)
                            started = True
                        output = LLMTextFrame(text)
                        output.metadata["generation_id"] = request_id
                        await self.push_frame(output)
            except AgentTaskError:
                pass  # The DSH agent owns the failure and any later public reply.
            except BridgeUnavailable:
                await self.push_error(error_msg="DSH bridge generation failed")
            finally:
                if started:
                    end = LLMFullResponseEndFrame()
                    end.metadata["generation_id"] = request_id
                    await self.push_frame(end)
                frame.metadata.get("dafeiyu_preview_finished", lambda: None)()
            return
        try:
            if self._listener is not None:
                await asyncio.wait_for(self._ready.wait(), 10)
            latest = self.store.messages(self.session_id)
            self._pending_users[request_id] = next((row["id"] for row in reversed(latest) if row["role"] == "user" and row["content"] == messages[-1]["content"]), None)
            if len(self._pending_users) > 128:
                self._pending_users.pop(next(iter(self._pending_users)))
            await self.store.bridge.voice_turn(body)
        except asyncio.TimeoutError:
            await self.push_error(error_msg="DSH voice event stream unavailable")
        except BridgeUnavailable:
            self._pending_users.pop(request_id, None)
            await self.push_error(error_msg="DSH voice admission failed")
