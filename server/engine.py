from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import re
import time
import wave
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx
from fastapi import WebSocket

from .storage import Store

MAX_TEXT = 4000
MAX_PCM = 16000 * 2 * 30
MAX_UNACKNOWLEDGED_AUDIO = 4
SENTENCE = re.compile(r"[。！？!?；;\n]")


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def wav_from_pcm(payload: str, sample_rate: int) -> bytes:
    if sample_rate != 16000 or not isinstance(payload, str) or len(payload) > (MAX_PCM * 4 // 3 + 8):
        raise ServiceError("invalid_audio", "音频必须为 16kHz 单声道 PCM16，最长 30 秒。")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        raise ServiceError("invalid_audio", "音频数据格式无效。") from None
    if not raw or len(raw) % 2 or len(raw) > MAX_PCM:
        raise ServiceError("invalid_audio", "音频长度无效。")
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(raw)
    return result.getvalue()


class SentenceChunker:
    """Emit whole natural phrases while bounding latency for unpunctuated responses."""

    def __init__(self):
        self.pending = ""

    def push(self, text: str, *, final: bool = False) -> list[str]:
        self.pending += text
        chunks = []
        while self.pending:
            match = SENTENCE.search(self.pending, 0, 60)
            if match:
                end = match.end()
            elif len(self.pending) >= 60:
                end = max(self.pending.rfind("，", 15, 60), self.pending.rfind(",", 15, 60),
                          self.pending.rfind(" ", 15, 60)) + 1
                if end <= 0:
                    end = 60
            elif final:
                end = len(self.pending)
            else:
                break
            chunk, self.pending = self.pending[:end], self.pending[end:]
            if chunk.strip():
                chunks.append(chunk)
        return chunks


def emotion_for(text: str) -> str:
    if any(word in text for word in ("抱歉", "难过", "伤心", "遗憾")):
        return "sad"
    if any(word in text for word in ("开心", "太棒", "哈哈", "喜欢", "恭喜")):
        return "happy"
    if any(word in text for word in ("真的吗", "居然", "竟然", "惊讶")):
        return "surprised"
    if "？" in text or "?" in text:
        return "curious"
    return "neutral"


def context_messages(settings: dict, memories: list[dict], history: list[dict]) -> list[dict]:
    """Bound provider context independently from the full persisted transcript."""
    system = settings["system_prompt"]
    memory_text = "\n".join("- " + item["content"] for item in memories[:30])[:3000]
    if memory_text:
        system += "\n用户希望你记住的信息：\n" + memory_text
    remaining = 20000 - len(system)
    selected = []
    for row in reversed(history[-30:]):
        if len(row["content"]) > remaining:
            break
        selected.append({"role": row["role"], "content": row["content"]})
        remaining -= len(row["content"])
    selected.reverse()
    while selected and selected[0]["role"] == "assistant":
        selected.pop(0)
    return [{"role": "system", "content": system}, *selected]


async def llm_tokens(client: httpx.AsyncClient, settings: dict, messages: list[dict]) -> AsyncIterator[str]:
    url = settings["llm_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Accept": "text/event-stream"}
    if settings["llm_api_key"]:
        headers["Authorization"] = "Bearer " + settings["llm_api_key"]
    body = {"model": settings["llm_model"], "messages": messages, "stream": True,
            "temperature": settings["temperature"]}
    try:
        async with client.stream("POST", url, headers=headers, json=body, timeout=httpx.Timeout(90, connect=8)) as response:
            if response.status_code >= 400:
                raise ServiceError("llm_http", f"对话模型请求失败（HTTP {response.status_code}），请检查地址、模型和密钥。")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    event = json.loads(data)
                    if event.get("error"):
                        raise ServiceError("llm_stream", "模型返回错误，请检查服务配置。")
                    choices = event.get("choices") or []
                    content = choices[0].get("delta", {}).get("content") if choices else None
                    if isinstance(content, str) and content:
                        yield content
                except (ValueError, TypeError, KeyError, IndexError):
                    raise ServiceError("llm_stream", "模型返回了无法识别的流式数据。") from None
    except httpx.TimeoutException:
        raise ServiceError("llm_timeout", "对话模型连接或响应超时。") from None
    except httpx.HTTPError:
        raise ServiceError("llm_connection", "无法连接对话模型服务，请检查地址和网络。") from None


async def transcribe(client: httpx.AsyncClient, settings: dict, wav: bytes) -> str:
    try:
        response = await client.post(settings["speech_base_url"].rstrip("/") + "/v1/audio/transcriptions",
                                     files={"file": ("input.wav", wav, "audio/wav")}, timeout=90)
        if response.is_error:
            raise ServiceError("asr_http", f"语音识别失败（HTTP {response.status_code}），请检查语音服务状态。")
        text = response.json().get("text", "")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ServiceError("asr_response", "语音识别返回了无效文本。")
        return text.strip()
    except (httpx.HTTPError, ValueError):
        raise ServiceError("asr_connection", "无法连接本地语音识别服务。") from None


async def synthesize(client: httpx.AsyncClient, settings: dict, text: str) -> bytes:
    try:
        response = await client.post(settings["speech_base_url"].rstrip("/") + "/v1/audio/speech",
                                     json={"input": text, "voice": settings["voice"], "response_format": "wav"}, timeout=120)
        if response.is_error:
            raise ServiceError("tts_http", f"语音合成失败（HTTP {response.status_code}），请检查语音服务状态。")
        audio = response.content
        if len(audio) > 15_000_000 or not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
            raise ServiceError("tts_response", "语音服务未返回有效 WAV 音频。")
        return audio
    except httpx.HTTPError:
        raise ServiceError("tts_connection", "无法连接本地语音合成服务。") from None


@dataclass
class Turn:
    epoch: int
    segments: dict[int, str] = field(default_factory=dict)
    acknowledged: set[int] = field(default_factory=set)
    text: str = ""
    done: bool = False
    saved: bool = False
    text_only: bool = False
    failed: bool = False
    capacity: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        self.capacity.set()

    def spoken_text(self) -> str:
        # Only contiguous acknowledgements can establish what was actually heard.
        spoken = []
        for number, text in sorted(self.segments.items()):
            if number not in self.acknowledged:
                break
            spoken.append(text)
        return "".join(spoken).strip()


class Conversation:
    def __init__(self, websocket: WebSocket, store: Store, client: httpx.AsyncClient, session_id: str):
        self.ws, self.store, self.client, self.session_id = websocket, store, client, session_id
        self.epoch = 0
        self.task: asyncio.Task | None = None
        self.turn: Turn | None = None
        self.lock = asyncio.Lock()

    async def emit(self, data: dict, epoch: int | None = None):
        async with self.lock:
            if epoch is not None and epoch != self.epoch:
                return
            if epoch is not None:
                data["epoch"] = epoch
            await self.ws.send_json(data)

    def save_turn(self, interrupted: bool):
        turn = self.turn
        if not turn or turn.saved:
            return
        spoken = turn.spoken_text()
        if turn.text_only and not interrupted:
            spoken = turn.text.strip()
        if spoken:
            self.store.add_message(self.session_id, "assistant", spoken,
                                   interrupted=interrupted or (bool(turn.text) and spoken != turn.text.strip()))
        turn.saved = True

    async def interrupt(self):
        self.epoch += 1
        await self.emit({"type": "audio.clear"}, self.epoch)
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.save_turn(interrupted=True)
        self.task = None
        self.turn = None

    async def start(self, event: dict):
        await self.interrupt()
        epoch = self.epoch
        self.turn = Turn(epoch)
        self.task = asyncio.create_task(self.run(event, self.turn))

    async def ack(self, epoch, segment_id):
        turn = self.turn
        if not turn or epoch != self.epoch or not isinstance(segment_id, int) or segment_id not in turn.segments:
            return
        turn.acknowledged.add(segment_id)
        if turn.done and len(turn.acknowledged) == len(turn.segments):
            self.save_turn(interrupted=turn.failed)
            await self.emit({"type": "state", "state": "listening"}, self.epoch)
        turn.capacity.set()

    async def playback_failed(self, epoch, segment_id):
        turn = self.turn
        if not turn or epoch != self.epoch or not isinstance(segment_id, int) or segment_id not in turn.segments:
            return
        await self.interrupt()
        await self.emit({"type": "error", "code": "playback_failed", "message": "音频播放失败，本次回复已停止。"}, self.epoch)
        await self.emit({"type": "state", "state": "listening"}, self.epoch)

    async def run(self, event: dict, turn: Turn):
        epoch = turn.epoch
        started = time.monotonic()
        ttft = None
        first_audio = None
        settings = self.store.settings(private=True)
        try:
            if event["type"] == "audio":
                wav = wav_from_pcm(event.get("audio"), event.get("sample_rate"))
                await self.emit({"type": "state", "state": "transcribing"}, epoch)
                text = await transcribe(self.client, settings, wav)
                if not text:
                    await self.emit({"type": "state", "state": "listening"}, epoch)
                    return
                await self.emit({"type": "transcript", "text": text}, epoch)
            else:
                text = event.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                    raise ServiceError("invalid_text", "请输入 1 至 4000 字的内容。")
                text = text.strip()
            self.store.add_message(self.session_id, "user", text)
            messages = context_messages(settings, self.store.memories(), self.store.messages(self.session_id))
            await self.emit({"type": "response.start"}, epoch)
            await self.emit({"type": "state", "state": "thinking"}, epoch)
            queue: asyncio.Queue = asyncio.Queue(maxsize=4)
            tts_failed = False

            async def speak():
                nonlocal first_audio, tts_failed
                segment_id = 0
                while True:
                    sentence = await queue.get()
                    if sentence is None:
                        return
                    if tts_failed:
                        continue
                    while len(turn.segments) - len(turn.acknowledged) >= MAX_UNACKNOWLEDGED_AUDIO:
                        turn.capacity.clear()
                        await turn.capacity.wait()
                    try:
                        audio = await synthesize(self.client, settings, sentence)
                    except ServiceError as error:
                        tts_failed = True
                        await self.emit({"type": "error", "code": error.code, "message": error.message}, epoch)
                        continue
                    if first_audio is None:
                        first_audio = round((time.monotonic() - started) * 1000)
                    turn.segments[segment_id] = sentence
                    await self.emit({"type": "state", "state": "speaking"}, epoch)
                    await self.emit({"type": "audio", "audio": base64.b64encode(audio).decode("ascii"),
                                     "format": "wav", "text": sentence, "segment_id": segment_id,
                                     "emotion": emotion_for(sentence)}, epoch)
                    segment_id += 1

            speaker = asyncio.create_task(speak())
            chunker = SentenceChunker()
            try:
                async for token in llm_tokens(self.client, settings, messages):
                    if ttft is None:
                        ttft = round((time.monotonic() - started) * 1000)
                    if len(turn.text) + len(token) > 8000:
                        token = token[:max(0, 8000 - len(turn.text))]
                    turn.text += token
                    if token:
                        await self.emit({"type": "text.delta", "text": token}, epoch)
                        for sentence in chunker.push(token):
                            await queue.put(sentence)
                    if len(turn.text) >= 8000:
                        break
                for sentence in chunker.push("", final=True):
                    await queue.put(sentence)
                await queue.put(None)
                await speaker
            finally:
                if not speaker.done():
                    speaker.cancel()
                    await asyncio.gather(speaker, return_exceptions=True)
            if not turn.text:
                raise ServiceError("empty_response", "对话模型没有返回可显示的内容。")
            turn.done = True
            turn.text_only = not bool(turn.segments)
            await self.emit({"type": "response.done", "text": turn.text}, epoch)
            await self.emit({"type": "metrics", "ttft_ms": ttft, "first_audio_ms": first_audio}, epoch)
            if not turn.segments or len(turn.acknowledged) == len(turn.segments):
                self.save_turn(interrupted=False)
                await self.emit({"type": "state", "state": "listening"}, epoch)
        except asyncio.CancelledError:
            raise
        except ServiceError as error:
            turn.failed = True
            turn.done = True
            if turn.segments and len(turn.acknowledged) == len(turn.segments):
                self.save_turn(interrupted=True)
            await self.emit({"type": "error", "code": error.code, "message": error.message}, epoch)
            if len(turn.acknowledged) == len(turn.segments):
                await self.emit({"type": "state", "state": "listening"}, epoch)
        except Exception:
            turn.failed = True
            turn.done = True
            if turn.segments and len(turn.acknowledged) == len(turn.segments):
                self.save_turn(interrupted=True)
            await self.emit({"type": "error", "code": "internal", "message": "对话处理失败，请检查本地服务日志。"}, epoch)
            if len(turn.acknowledged) == len(turn.segments):
                await self.emit({"type": "state", "state": "listening"}, epoch)
