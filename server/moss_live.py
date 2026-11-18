"""Audio-only MOSS-Live foreground with an independent DeepSeek executor.

Official realtime protocol: verified 2026-11-12. No video, automatic reconnect,
paid health probe, local model fallback, or implicit execution of model tools.
"""
from __future__ import annotations

import asyncio
import hashlib

import anyio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import uuid
from urllib.parse import urlencode

from openai import AsyncOpenAI
from websockets.asyncio.client import connect
from pipecat.frames.frames import (InputAudioRawFrame, LLMTextFrame, LLMFullResponseStartFrame,
    LLMFullResponseEndFrame, StartFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame, TranscriptionFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame

from .context import context_messages
from . import dsh


def configuration_status(settings):
    configured = bool(settings["moss_live_api_key"] and (dsh.enabled() or settings["llm_api_key"]))
    return {"provider": "MOSS-Live + DSH" if dsh.enabled() else "MOSS-Live + DeepSeek", "model": settings["moss_live_model"],
            "configured": configured, "ready": False, "device": "remote", "verification": "not_probed",
            "detail": "已配置；连接语音时验证，可能产生费用" if configured else "请填写独立 MOSS-Live 密钥和后台 DeepSeek 密钥"}


@dataclass
class Reply:
    run_id: str
    turn_id: str
    pending: OrderedDict = field(default_factory=OrderedDict)
    playback_samples: dict = field(default_factory=dict)
    received: set = field(default_factory=set)
    audio_done: bool = False
    playback_done: bool = False
    interrupted: bool = False
    stop_reported: bool = False
    transcript_done: bool = False
    text: str = ""
    saved: bool = False
    group: str = ""
    generation_id: str | None = None
    projection_stopped: bool = False


class MossLiveBridge(FrameProcessor):
    def __init__(self, upstream, settings, store, session_id, ledger):
        super().__init__()
        self.upstream, self.settings, self.store, self.session_id = upstream, settings, store, session_id
        self.ledger = ledger
        self.rtvi = None
        self.send_lock = asyncio.Lock()
        self.replies = OrderedDict()
        self.context = None
        self.delegations = OrderedDict()
        self.delegation_requests = OrderedDict()
        self.user_turns = OrderedDict()
        self.reader = None
        self.start_reader = None
        self.closed = False
        self.cleanup_task = None
        self.native = bool(getattr(store, "is_dsh_projection", False))
        self.connection_id = uuid.uuid4().hex
        self.native_listener = None
        self.native_ready = asyncio.Event()
        self.native_context_ready = asyncio.Event()
        self.native_cursor = None
        self.native_attempts = {}
        self.native_seen_users = set()
        self.native_active = False

    async def send(self, action, **data):
        async with self.send_lock:
            await asyncio.wait_for(self.upstream.send(json.dumps({"action": action, **data}, ensure_ascii=False)), 5)

    async def expect(self, action):
        async with asyncio.timeout(10):
            for _ in range(16):
                message = await self.upstream.recv()
                if not isinstance(message, str):
                    raise RuntimeError("MOSS-Live 配置阶段收到意外音频")
                event = json.loads(message)
                if event.get("action") == "error":
                    raise RuntimeError("MOSS-Live 拒绝会话配置，请核对密钥、模型和音色")
                if event.get("action") == action:
                    data = event.get("data", {})
                    if data.get("error"):
                        raise RuntimeError("MOSS-Live 会话配置未生效")
                    return data
            raise RuntimeError("MOSS-Live 会话配置响应无效")

    def observation_id(self, role, identity, text):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return "moss-" + hashlib.sha256(
            json.dumps([self.connection_id, role, str(identity), digest], ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    async def observe(self, role, identity, text, revised=False):
        if not self.native:
            return
        try:
            async with asyncio.timeout(3):
                await self.store.bridge.voice_observation(self.session_id, self.observation_id(role, identity, text),
                                                          role, text, revised=revised)
        except (dsh.BridgeUnavailable, asyncio.TimeoutError):
            if self.rtvi:
                await self.rtvi.send_error("DSH voice observation unavailable")

    async def set_capture(self, active):
        await self.send("mic_state", enabled=active)
        if self.native:
            await self.store.bridge.voice_state(self.session_id, self.connection_id, True, active)

    async def native_events(self):
        delay = .25
        while True:
            try:
                async for cursor, event in self.store.bridge.voice_events(self.session_id, self.native_cursor):
                    if event.get("type") == "ready":
                        if self.native_cursor is None:
                            self.native_cursor = cursor
                        self.native_ready.set()
                    else:
                        await self.native_context_ready.wait()
                        await self.native_event(event)
                        self.native_cursor = cursor
                    delay = .25
            except dsh.BridgeUnavailable:
                pass
            finally:
                self.native_ready.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)

    async def native_event(self, event):
        typ = event.get("type")
        if typ == "reset":
            self.native_attempts.clear()
            if self.rtvi:
                await self.rtvi.send_error("DSH voice event history unavailable")
            return
        if typ == "conversation.user":
            message_id, text, request = event.get("message_id"), event.get("text"), event.get("request_id")
            if (not isinstance(message_id, str) or not message_id or len(message_id) > 256
                or not isinstance(text, str) or not text.strip() or len(text) > 50000
                or message_id in self.native_seen_users or request in self.delegation_requests.values()):
                return
            self.native_seen_users.add(message_id)
            if len(self.native_seen_users) > 1024:
                self.native_seen_users.clear()
                self.native_seen_users.add(message_id)
            await self.send("session.thinking.append", content="user: " + text[:8000], event_id=uuid.uuid4().hex)
            return
        generation = event.get("generation_id")
        if not isinstance(generation, str) or not generation or len(generation) > 256:
            return
        if typ == "response.start":
            request = event.get("request_id")
            self.native_attempts[generation] = (request, "")
            if len(self.native_attempts) > 128:
                self.native_attempts.pop(next(iter(self.native_attempts)))
        elif typ == "response.text" and generation in self.native_attempts:
            text = event.get("text")
            request, current = self.native_attempts[generation]
            if isinstance(text, str):
                self.native_attempts[generation] = (request, (current + text)[:20000])
        elif typ in {"response.end", "response.error"}:
            if typ == "response.error" and event.get("code") == "VOICE_STREAM_GAP" and generation in self.native_attempts and self.rtvi:
                await self.rtvi.send_error("DSH voice stream has missing or out-of-order text")
            request, text = self.native_attempts.pop(generation, (None, ""))
            # A live compat reader delivers its result via commentary. After
            # that reader is canceled/times out, the native task still runs;
            # its eventual public output must not be permanently filtered out.
            delegated = any(req == request and (task := self.delegations.get(identity)) is not None and not task.done()
                            for identity, req in self.delegation_requests.items())
            if typ == "response.end" and text and text.strip() and not delegated:
                await self.send("session.thinking.append", content="assistant: " + text, event_id=uuid.uuid4().hex)

    async def initialize(self):
        await self.send("attach_session", session_id=None, delegation={"type": "client"}, memory_scope="session")
        attached = await self.expect("session_attached")
        if attached.get("delegation") != "client":
            raise RuntimeError("MOSS-Live 后台模型委派未启用")
        if self.native:
            self.native_active = True
            await self.store.bridge.voice_state(self.session_id, self.connection_id, True, False)
            self.native_listener = asyncio.create_task(self.native_events())
            await asyncio.wait_for(self.native_ready.wait(), 10)
            native_context = await self.store.bridge.voice_context(self.session_id)
            if not isinstance(native_context, dict) or not isinstance(native_context.get("persona"), str) or not isinstance(native_context.get("messages"), list):
                raise RuntimeError("DSH voice context unavailable")
            environment = native_context.get("environment", "")
            if not isinstance(environment, str):
                raise RuntimeError("DSH voice context unavailable")
            messages = [{"role": "system", "content": "\n\n".join(
                part for part in (native_context["persona"], environment) if part
            )}]
            for row in native_context["messages"][-30:]:
                if isinstance(row, dict) and row.get("role") in {"user", "assistant"} and isinstance(row.get("content"), str):
                    messages.append({"role": row["role"], "content": row["content"]})
                    if row.get("role") == "user" and isinstance(row.get("id"), str):
                        self.native_seen_users.add(row["id"])
        else:
            messages = context_messages(self.settings, self.store.memories(), self.store.messages(self.session_id))
        backend = "DSH" if self.native else "DeepSeek"
        instructions = (f"只进行中文语音交流，不使用摄像头或屏幕。复杂推理和知识任务委派给后台 {backend}；"
                        "后台未返回时不要编造结果。\n" + messages[0]["content"])[:8000]
        await self.send("session.update", session={"instructions": instructions, "tools": []})
        await self.expect("session.updated")
        # Request the exact format used by the existing browser player.
        await self.send("media.configure", input_audio={"format": "pcm16", "sample_rate": 16000},
                        output_audio={"format": "pcm16", "sample_rate": 24000}, playback="client")
        media = await self.expect("media.configured")
        for key, rate in (("input_audio", 16000), ("output_audio", 24000)):
            actual = media.get(key, {})
            if actual.get("format") != "pcm16" or actual.get("sample_rate") != rate or actual.get("channels", 1) != 1:
                raise RuntimeError("MOSS-Live 音频格式协商不匹配")
        if media.get("playback") != "client":
            raise RuntimeError("MOSS-Live 必须使用实际播放确认")
        if self.settings["moss_live_voice"]:
            await self.send("change_voice", voice_name=self.settings["moss_live_voice"])
            await self.expect("voice_changed")
        history = "\n".join(f"{m['role']}: {m['content']}" for m in messages[1:])[-1900:]
        if history:
            await self.send("session.thinking.append", content="之前已确认的对话：\n"+history, event_id=uuid.uuid4().hex)
            await self.expect("session.thinking.appended")
        await self.send("mic_state", enabled=not self.native)
        if self.native:
            self.native_context_ready.set()

    def reply(self, data, *, allow_active=False):
        if allow_active and (not data.get("run_id") or not data.get("turn_id")):
            candidates = [r for r in self.replies.values() if not r.transcript_done and not r.interrupted
                          and (not data.get("run_id") or r.run_id == data["run_id"])
                          and (not data.get("turn_id") or r.turn_id == data["turn_id"])]
            if len(candidates) != 1:
                raise RuntimeError("MOSS-Live 字幕无法唯一关联回答")
            self.associate_generation(candidates[0], data)
            return candidates[0]
        key = (data.get("run_id"), data.get("turn_id"))
        if any(not isinstance(v, str) or not v or len(v) > 256 for v in key):
            raise RuntimeError("MOSS-Live 缺少有效的回答标识")
        if key not in self.replies:
            if len(self.replies) >= 16:
                oldest = next(iter(self.replies.values()))
                if oldest.pending:
                    raise RuntimeError("MOSS-Live 待确认回答过多")
                self.replies.popitem(last=False)
            self.replies[key] = Reply(*key)
            self.associate_generation(self.replies[key], data)
            self.ledger.begin_generation(self.replies[key].generation_id)
            self.replies[key].group = self.ledger.group
        else:
            self.associate_generation(self.replies[key], data)
        return self.replies[key]

    def associate_generation(self, reply, data):
        """Only an explicit correlation may project native audio into a DSH request."""
        if not getattr(self.store, "is_dsh_projection", False):
            return
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        delegation_id = data.get("delegation_id", metadata.get("delegation_id"))
        request_id = data.get("generation_id", metadata.get("generation_id")) or data.get("request_id")
        if delegation_id is not None:
            request_id = self.delegation_requests.get(delegation_id)
        if not isinstance(request_id, str) or request_id not in self.delegation_requests.values():
            return  # Foreground run/turn IDs are not DSH request IDs.
        if reply.generation_id and reply.generation_id != request_id:
            raise RuntimeError("MOSS-Live generation correlation changed")
        if not reply.generation_id and reply.group:
            if reply.pending or reply.received:
                raise RuntimeError("MOSS-Live generation correlation arrived after audio")
            self.ledger.begin_generation(request_id)
            reply.group = self.ledger.group
        reply.generation_id = request_id

    def audio_metadata(self, frame, reply):
        frame.metadata["playback_group_id"] = reply.group
        if reply.generation_id:
            frame.metadata["generation_id"] = reply.generation_id
        return frame

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, InputAudioRawFrame):
            if frame.sample_rate != 16000 or frame.num_channels != 1 or len(frame.audio) % 2:
                raise RuntimeError("MOSS-Live 输入必须为 16kHz 单声道 PCM16")
            async with self.send_lock:
                await asyncio.wait_for(self.upstream.send(frame.audio), 5)
            return
        if isinstance(frame, RTVISendTextFrame):
            await self.rtvi.send_error("MOSS-Live 模式仅支持语音，请打开麦克风；文字聊天可切回本地语音模式。")
            return
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame) and self.start_reader and self.reader is None:
            self.reader = asyncio.create_task(self.start_reader())

    async def receive(self):
        async for raw in self.upstream:
            if isinstance(raw, bytes):
                await self.audio(raw)
            else:
                event = json.loads(raw)
                if not isinstance(event, dict) or not isinstance(event.get("data", {}), dict):
                    raise RuntimeError("MOSS-Live 事件格式无效")
                await self.event(event.get("action"), event.get("data", {}))
        raise RuntimeError("MOSS-Live 连接已关闭，请手动重新连接")

    async def audio(self, pcm):
        data, self.context = self.context, None
        if data is None or len(pcm) % 2 or len(pcm) > 480000:
            raise RuntimeError("MOSS-Live 音频或关联上下文无效")
        reply = self.reply(data)
        if reply.interrupted:
            return
        chunk_id = data.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id or len(chunk_id) > 256 or chunk_id in reply.received:
            raise RuntimeError("MOSS-Live 音频分块标识无效或重复")
        if len(reply.received) >= 2048 or sum(len(r.pending) for r in self.replies.values()) >= 64:
            raise RuntimeError("MOSS-Live 音频积压超过上限")
        reply.received.add(chunk_id)
        if not pcm:
            await self.send("playback.chunk.completed", run_id=reply.run_id, turn_id=reply.turn_id, chunk_id=chunk_id)
            return
        epoch = uuid.uuid4().hex
        reply.pending[epoch] = (chunk_id, len(pcm)//2)
        await self.push_frame(self.audio_metadata(TTSStartedFrame(context_id=epoch), reply))
        for offset in range(0, len(pcm), 4800):
            await self.push_frame(self.audio_metadata(TTSAudioRawFrame(audio=pcm[offset:offset+4800], sample_rate=24000,
                                                 num_channels=1, context_id=epoch), reply))
        await self.push_frame(self.audio_metadata(TTSStoppedFrame(context_id=epoch), reply))

    async def acknowledge(self, data):
        epoch = data.get("epoch") if isinstance(data, dict) else None
        target = next((r for r in self.replies.values() if epoch in r.pending and not r.interrupted), None)
        if target is None or next(iter(target.pending)) != epoch or not self.ledger.acknowledge(data):
            return False
        for reply in self.replies.values():
            if epoch in reply.pending and not reply.interrupted:
                if next(iter(reply.pending)) != epoch:
                    raise RuntimeError("MOSS-Live 播放确认顺序无效")
                chunk_id, _samples = reply.pending.pop(epoch)
                await self.send("playback.chunk.completed", run_id=reply.run_id, turn_id=reply.turn_id, chunk_id=chunk_id)
                await self.finish(reply)
                return True
        return False

    async def finish(self, reply):
        if reply.audio_done and not reply.pending and not reply.interrupted and not reply.playback_done:
            await self.send("playback.completed", run_id=reply.run_id, turn_id=reply.turn_id)
            reply.playback_done = True
        if reply.playback_done and reply.transcript_done and reply.text and not reply.saved and not reply.interrupted:
            self.store.add_message(self.session_id, "assistant", reply.text)
            await self.observe("assistant", (reply.run_id, reply.turn_id), reply.text)
            if reply.generation_id:
                self.store.enqueue_playback(reply.generation_id, reply.text)
            reply.saved = True

    async def stop(self, reply=None):
        targets = [reply] if reply else [r for r in self.replies.values() if not r.playback_done]
        targets = [r for r in targets if not r.stop_reported]
        for current in targets:
            current.interrupted = True
            if current.generation_id and not current.projection_stopped:
                # Native chunks do not supply aligned text prefixes. Never infer
                # heard words from an audio duration or an unfinished transcript.
                self.store.enqueue_playback(current.generation_id, "", True)
                current.projection_stopped = True
            for epoch, (_chunk, native_samples) in current.pending.items():
                turn = self.ledger.turns.get(epoch)
                current.playback_samples[epoch] = max(native_samples, turn.samples if turn else 0)
            if not current.pending and not current.stop_reported:
                await self.send("playback.stopped", run_id=current.run_id, turn_id=current.turn_id, played_audio_ms=0)
                current.stop_reported = True
        self.ledger.interrupt()
        await self.rtvi.interrupt_bot()

    async def playback_stopped(self, data):
        # Only the actual unfinished head chunk contributes partial duration.
        items = data.get("chunks", []) if isinstance(data, dict) else []
        if not isinstance(items, list) or len(items) > 64:
            return False
        accepted = False
        for reply in self.replies.values():
            if reply.stop_reported or not reply.interrupted or not reply.pending:
                continue
            epoch = next(iter(reply.pending))
            item = next((v for v in items if isinstance(v, dict) and v.get("epoch") == epoch), None)
            samples = item.get("consumed_samples") if item else 0
            if type(samples) is not int or not 0 <= samples <= reply.playback_samples.get(epoch, reply.pending[epoch][1]):
                continue
            await self.send("playback.stopped", run_id=reply.run_id, turn_id=reply.turn_id, played_audio_ms=min(samples, reply.pending[epoch][1])/24)
            reply.stop_reported = True
            reply.interrupted = True
            reply.pending.clear()
            reply.playback_samples.clear()
            accepted = True
        return accepted

    async def event(self, action, data):
        if action == "error":
            raise RuntimeError("MOSS-Live 返回错误，请核对账户、模型、音色或连接状态")
        if action == "session.closing":
            raise RuntimeError("MOSS-Live 会话即将结束，请手动重新连接")
        if action == "response.audio.context":
            if self.context is not None:
                raise RuntimeError("MOSS-Live 音频上下文缺少对应分块")
            self.context = data
        elif action == "response.audio.started":
            reply = self.reply(data)
            await self.push_frame(self.audio_metadata(LLMFullResponseStartFrame(), reply))
        elif action == "response.audio.done":
            reply = self.reply(data)
            reply.audio_done = True
            await self.finish(reply)
        elif action in {"response.audio.stop", "response.interrupted"}:
            await self.stop(self.reply(data))
        elif action in {"output.transcript.updated", "output.transcript.done"}:
            reply = self.reply(data, allow_active=True)
            text = data.get("text", "")
            if not isinstance(text, str) or len(text) > 20000:
                raise RuntimeError("MOSS-Live 字幕超过上限")
            if not reply.interrupted and text.startswith(reply.text):
                delta = text[len(reply.text):]
                if delta:
                    await self.push_frame(LLMTextFrame(text=delta))
            reply.text = text
            reply.transcript_done = action.endswith(".done")
            await self.finish(reply)
        elif action in {"input.transcript.done", "input.transcript.revised"}:
            text, turn = data.get("text", ""), data.get("turn")
            if not isinstance(text, str) or len(text) > 8000:
                raise RuntimeError("MOSS-Live 识别文本无效")
            if not text.strip():
                return
            if turn is not None and (type(turn) not in (str, int) or len(str(turn)) > 256):
                raise RuntimeError("MOSS-Live 用户轮次标识无效")
            if turn is not None and turn in self.user_turns:
                self.store.revise_user_message(self.user_turns[turn], self.session_id, text)
                observation_turn = turn
            else:
                message_id = self.store.add_message(self.session_id, "user", text)
                observation_turn = turn if turn is not None else message_id
                if turn is not None:
                    self.user_turns[turn] = message_id
                    while len(self.user_turns) > 256:
                        self.user_turns.popitem(last=False)
                await self.push_frame(TranscriptionFrame(text=text, user_id="user", timestamp=datetime.now(timezone.utc).isoformat()))
            await self.observe("user", observation_turn, text, revised=action == "input.transcript.revised")
        elif action == "input.speech.started":
            await self.push_frame(UserStartedSpeakingFrame())
        elif action == "input.speech.stopped":
            await self.push_frame(UserStoppedSpeakingFrame())
        elif action == "response.ended":
            await self.push_frame(LLMFullResponseEndFrame())
        elif action == "session.delegation.created":
            await self.delegate(data)
        elif action == "session.delegation.cancelled":
            task = self.delegations.get(data.get("delegation_id"))
            if task and not task.done():
                task.cancel()

    async def delegate(self, data):
        delegation = data.get("delegation")
        if not isinstance(delegation, dict) or delegation.get("target") != "client" or delegation.get("type") != "delegation":
            raise RuntimeError("MOSS-Live 后台任务委派目标无效")
        identity = delegation.get("id")
        objective = data.get("objective")
        if not isinstance(identity, str) or not identity or len(identity) > 256 or not isinstance(objective, str) or not 0 < len(objective) <= 8000:
            raise RuntimeError("MOSS-Live 后台任务无效")
        if identity in self.delegations:
            return  # A repeated event must never charge for a second LLM request.
        if len(self.delegations) >= 256:
            raise RuntimeError("MOSS-Live 会话任务数已达上限，请重新连接")
        if sum(not t.done() for t in self.delegations.values()) >= 2:
            await self.send("session.commentary.append", delegation_id=identity, content="后台正在处理其他请求，请稍后再试。",
                            status="failed", event_id=uuid.uuid4().hex)
            return
        timeout = data.get("timeout_ms", 60000)
        if type(timeout) is not int or timeout <= 0:
            raise RuntimeError("MOSS-Live 后台任务时限无效")
        self.delegations[identity] = asyncio.create_task(self.execute(identity, objective, data.get("context", []), min(timeout / 1000, 60)))

    async def execute(self, identity, objective, excerpts, timeout=60):
        try:
            async with asyncio.timeout(timeout):
                if self.native:
                    request_id = self.delegation_requests.setdefault(identity, uuid.uuid4().hex)
                    body = dsh.chat_body(self.session_id, request_id, "delegation", "",
                                         [], [{"role":"user", "content":objective}], model=self.store.model,
                                         temperature=self.settings["temperature"] if self.store.temperature_supported else None, stream=False)
                    text = await dsh.completion_text(self.store.bridge, body)
                else:
                    messages = context_messages(self.settings, self.store.memories(), self.store.messages(self.session_id))
                    # External context is conversation data, never system instructions.
                    for row in excerpts[:6] if isinstance(excerpts, list) else []:
                        if isinstance(row, dict) and row.get("role") in {"user", "assistant"} and isinstance(row.get("content"), str):
                            messages.append({"role":row["role"], "content":row["content"][:600]})
                    messages.append({"role":"user", "content":objective + "\n请在600字以内给出可直接口述的结论，不输出思考过程。"})
                    async with AsyncOpenAI(api_key=self.settings["llm_api_key"], base_url=self.settings["llm_base_url"],
                                           max_retries=0, timeout=55) as llm:
                        result = await llm.chat.completions.create(model=self.settings["llm_model"], messages=messages,
                                                                  temperature=self.settings["temperature"], max_tokens=600)
                    text = result.choices[0].message.content
            if not text or not text.strip():
                raise RuntimeError("Empty background response")
            await self.send("session.commentary.append", delegation_id=identity, content=text[:2000],
                            status="completed", event_id=uuid.uuid4().hex)
        except dsh.AgentTaskError:
            pass  # The DSH agent may publish its own explanation later.
        except asyncio.CancelledError:
            # Closing the compat reader does not cancel a DSH native turn.
            raise
        except Exception:
            # Do not send provider responses/headers or credentials to the client.
            try:
                await self.send("session.commentary.append", delegation_id=identity, content="DeepSeek 后台请求失败，请检查后台模型配置后重试。",
                                status="failed", event_id=uuid.uuid4().hex)
            except Exception:
                pass  # The realtime connection may already have closed.

    async def cleanup(self):
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._cleanup(asyncio.current_task()))
        await asyncio.shield(self.cleanup_task)

    async def _cleanup(self, origin):
        if self.closed:
            return
        self.closed = True
        for reply in self.replies.values():
            if reply.generation_id and not reply.saved and not reply.projection_stopped:
                self.store.enqueue_playback(reply.generation_id, "", True)
                reply.projection_stopped = True
        tasks = [*self.delegations.values(), self.reader, self.native_listener]
        tasks = [task for task in tasks if task is not None and task is not origin]
        for task in tasks:
            if not task.done():
                task.cancel()
        with anyio.move_on_after(3, shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.native_active:
            with anyio.move_on_after(5, shield=True):
                try:
                    await self.store.bridge.voice_state(self.session_id, self.connection_id, False, False)
                except dsh.BridgeUnavailable:
                    pass
            self.native_active = False
        await super().cleanup()


async def run_moss_voice(websocket, store, session_id):
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker, PipelineParams
    from pipecat.workers.runner import WorkerRunner
    from pipecat.serializers.protobuf import ProtobufFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
    from .pipecat_voice import PriorityRTVIProcessor
    from .playback import PlaybackLedger, PlaybackStart, PlaybackBoundary
    settings = store.settings(private=True)
    if not configuration_status(settings)["configured"] or settings["owner_voice_only"]:
        await websocket.close(code=1008, reason="请配置 MOSS-Live 与 DeepSeek 密钥，并关闭本地声纹筛选")
        return
    url = "wss://api.mosi.cn/v1/realtime?" + urlencode({"model": settings["moss_live_model"]})
    try:
        upstream = await connect(url, additional_headers={"Authorization": "Bearer "+settings["moss_live_api_key"]},
                                 open_timeout=10, close_timeout=3, max_size=512000, max_queue=8, write_limit=32768)
    except Exception:
        raise RuntimeError("MOSS-Live 连接失败，请检查密钥和网络") from None
    bridge = None
    try:
        transport = FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(
            serializer=ProtobufFrameSerializer(), audio_in_enabled=True, audio_out_enabled=True,
            audio_in_sample_rate=16000, audio_out_sample_rate=24000, audio_out_end_silence_secs=0))
        ledger = PlaybackLedger(lambda *_: None)
        bridge = MossLiveBridge(upstream, settings, store, session_id, ledger)
        await bridge.initialize()
        boundary = PlaybackBoundary(ledger, None)
        pipeline = Pipeline([transport.input(), bridge, PlaybackStart(ledger), transport.output(), boundary])
        worker = PipelineWorker(pipeline, params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
                                idle_timeout_secs=None, conversation_id=session_id, rtvi_processor=PriorityRTVIProcessor())
        bridge.rtvi = boundary.rtvi = worker.rtvi
        runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        await runner.add_workers(worker)

        @worker.rtvi.event_handler("on_client_message")
        async def client_message(rtvi, message):
            accepted = False
            if message.type == "voice.playback":
                accepted = await bridge.acknowledge(message.data)
            elif message.type == "voice.playback.stopped":
                accepted = await bridge.playback_stopped(message.data)
            elif message.type == "voice.stop":
                await bridge.stop()
                accepted = True
            elif message.type == "voice.capture":
                try:
                    await bridge.set_capture(message.data["active"])
                    accepted = True
                except dsh.BridgeUnavailable:
                    await rtvi.send_error("DSH voice state unavailable")
            await rtvi.send_server_response(message, {"accepted": accepted})

        async def read():
            try:
                await bridge.receive()
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await bridge.rtvi.send_error("MOSS-Live 语音连接中断，请检查配置或重新连接。")
                finally:
                    # Schedule cancellation independently: pipeline cleanup joins this reader.
                    asyncio.create_task(runner.cancel())
        bridge.start_reader = read

        @transport.event_handler("on_client_disconnected")
        async def disconnected(_transport, _client):
            await runner.cancel()

        await runner.run()
    finally:
        try:
            if bridge:
                await bridge.cleanup()
        finally:
            await asyncio.shield(upstream.close())
