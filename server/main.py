from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from urllib.parse import urlsplit
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storage import ROOT, Store
from .tts_policy import resolve_tts_mode, api_configured
from . import dsh

def dsh_origin():
    origin = os.environ.get("DAFEIYU_DSH_ORIGIN", "http://127.0.0.1:3080")
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and parsed.port and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment):
            return origin
    except ValueError:
        pass
    return None


log = logging.getLogger("dafeiyu")
app = FastAPI(title="Dafeiyu", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"] + ([dsh_origin()] if dsh.enabled() and dsh_origin() else []),
                   allow_methods=["GET", "PUT", "POST", "DELETE"], allow_headers=["Content-Type", "X-Dafeiyu-Plugin-Token"])
store = Store()
active_sessions: set[str] = set()
active_voice_sockets: dict[str, WebSocket] = {}
voice_policy_lock = asyncio.Lock()
VOICE_CLOSE_TIMEOUT = 2.0


async def close_voice_socket(socket: WebSocket, *, code: int, reason: str):
    # A peer that never completes its close handshake must not hold the policy
    # lock or prevent other sessions from connecting. The close frame is sent
    # by the task, which may finish after this bounded wait (as in Pipecat).
    async def close():
        try:
            await socket.close(code=code, reason=reason)
        except (RuntimeError, OSError):
            pass

    task = asyncio.create_task(close(), name="voice-websocket-close")
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    done, _ = await asyncio.wait({task}, timeout=VOICE_CLOSE_TIMEOUT)
    if not done:
        log.warning("Voice WebSocket close exceeded %.1fs (code=%s)", VOICE_CLOSE_TIMEOUT, code)


async def close_old_voice_sessions():
    await asyncio.gather(*(close_voice_socket(socket, code=4001, reason="语音策略已更改，请重新连接。")
                           for socket in list(active_voice_sockets.values())))


def trusted_origin(origin: str | None) -> bool:
    if not origin:
        return True
    if dsh.enabled() and origin == dsh_origin():
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port in {5173, 8765}
    except ValueError:
        return False


class PluginAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if dsh.enabled() and scope["type"] in {"http", "websocket"}:
            headers = dict(scope.get("headers", []))
            expected = os.environ.get("DAFEIYU_PLUGIN_TOKEN", "")
            supplied = headers.get(b"x-dafeiyu-plugin-token", b"")
            if not expected or not secrets.compare_digest(supplied, expected.encode("utf-8")):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
                return
            path = scope.get("path", "")
            if scope["type"] == "http" and (path == "/api/memories" or path.startswith("/api/memories/")):
                await JSONResponse({"detail": "Memory is managed by DSH"}, status_code=410)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(PluginAuth)


@app.exception_handler(dsh.BridgeUnavailable)
async def bridge_error(_request, exc):
    return JSONResponse({"detail": "DSH bridge request failed"}, status_code=exc.status_code)


@app.middleware("http")
async def local_origin_only(request: Request, call_next):
    if not trusted_origin(request.headers.get("origin")):
        return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # Validation errors may contain keys or credential-bearing URLs as input.
    return JSONResponse({"detail": [{key: item[key] for key in ("loc", "msg", "type") if key in item}
                                    for item in exc.errors()]}, status_code=422)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    harness_provider: str | None = None
    memory_owner: str | None = None
    llm_temperature_managed: bool | None = None
    api_key_set: bool | None = None
    llm_base_url: str | None = Field(default=None, max_length=2048)
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_api_key: str | None = Field(default=None, max_length=4096)
    system_prompt: str | None = Field(default=None, max_length=8000)
    speech_base_url: str | None = Field(default=None, max_length=2048)
    voice: str | None = Field(default=None, max_length=200)
    owner_voice_only: bool | None = None
    streaming_asr_preview: bool | None = None
    systemone_enabled: bool | None = None
    systemone_provider: Literal["ark", "tokentosea"] | None = None
    systemone_ark_model: str | None = Field(default=None, min_length=1, max_length=128)
    systemone_ark_api_key: str | None = Field(default=None, max_length=4096)
    clear_systemone_ark_api_key: bool = False
    systemone_api_key: str | None = Field(default=None, max_length=4096)
    clear_systemone_api_key: bool = False
    systemone_audio_enabled: bool | None = None
    systemone_timeout_ms: int | None = Field(default=None, ge=200, le=5000)
    systemone_interrupt_threshold: float | None = Field(default=None, ge=0.5, le=0.99)
    systemone_confidence: float | None = Field(default=None, ge=0.5, le=0.99)
    screen_companion_mode: Literal["systemone", "direct"] | None = None
    companion_interests: str | None = Field(default=None, max_length=2000, strict=True)
    idle_companion_enabled: bool | None = Field(default=None, strict=True)
    idle_companion_after_s: int | None = Field(default=None, ge=30, le=3600, strict=True)
    idle_companion_cooldown_s: int | None = Field(default=None, ge=30, le=3600, strict=True)
    idle_companion_max_per_hour: int | None = Field(default=None, ge=1, le=60, strict=True)
    idle_companion_include_screen: bool | None = Field(default=None, strict=True)
    idle_companion_max_reply_chars: int | None = Field(default=None, ge=8, le=240, strict=True)
    screen_companion_enabled: bool | None = Field(default=None, strict=True)
    screen_companion_style: Literal["quiet", "balanced", "lively"] | None = None
    screen_companion_interval_ms: int | None = Field(default=None, ge=1000, le=10000, strict=True)
    screen_companion_change_threshold: float | None = Field(default=None, ge=0.01, le=0.5, strict=True)
    screen_companion_cooldown_s: int | None = Field(default=None, ge=10, le=300, strict=True)
    screen_companion_max_judgments_per_hour: int | None = Field(default=None, ge=1, le=240, strict=True)
    screen_companion_max_replies_per_hour: int | None = Field(default=None, ge=1, le=60, strict=True)
    screen_companion_speak_threshold: float | None = Field(default=None, ge=0.5, le=0.99, strict=True)
    screen_companion_wait_threshold: float | None = Field(default=None, ge=0, le=0.5, strict=True)
    screen_companion_max_reply_chars: int | None = Field(default=None, ge=8, le=120, strict=True)
    screen_companion_timeout_ms: int | None = Field(default=None, ge=500, le=10000, strict=True)
    screen_companion_refresh_ms: int | None = Field(default=None, ge=5000, le=120000, strict=True)
    screen_request_enabled: bool | None = Field(default=None, strict=True)
    screen_request_threshold: float | None = Field(default=None, ge=0.5, le=0.99, strict=True)
    screen_request_timeout_ms: int | None = Field(default=None, ge=500, le=5000, strict=True)
    systemone_initiative_enabled: bool | None = None
    systemone_initiative_threshold: float | None = Field(default=None, ge=0.8, le=0.99)
    systemone_initiative_min_speech_ms: int | None = Field(default=None, ge=1500, le=15000)
    systemone_initiative_cooldown_s: int | None = Field(default=None, ge=10, le=120)
    systemone_initiative_wait_threshold: float | None = Field(default=None, ge=0, le=0.5)
    systemone_initiative_max_reply_chars: int | None = Field(default=None, ge=8, le=80)
    systemone_initiative_probe_interval_ms: int | None = Field(default=None, ge=1500, le=10000)
    systemone_initiative_max_probes: int | None = Field(default=None, ge=1, le=6)
    tts_engine: Literal["local", "cosyvoice"] | None = None
    tts_mode: Literal["legacy", "auto", "cpu", "gpu", "api"] | None = None
    gpu_tts_model: Literal["index_tts", "gpt_sovits"] | None = None
    conversation_mode: Literal["pipeline", "duplex", "moss_live"] | None = None
    moss_live_api_key: str | None = Field(default=None, max_length=4096)
    clear_moss_live_api_key: bool = False
    moss_live_voice: str | None = Field(default=None, max_length=200)
    moss_live_model: Literal["moss-live-1.0", "moss-live-1.0-2026-11-02"] | None = None
    index_tts_url: str | None = Field(default=None, max_length=2048)
    moss_tts_url: str | None = Field(default=None, max_length=2048)
    tts_api_provider: Literal["deepseek", "openai_compatible"] | None = None
    tts_api_filter_markdown: bool | None = None
    tts_api_base_url: str | None = Field(default=None, max_length=2048)
    tts_api_model: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    tts_api_voice: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    tts_api_key: str | None = Field(default=None, max_length=4096)
    clear_tts_api_key: bool = False
    tts_api_speed: float | None = Field(default=None, ge=0.25, le=4)
    tts_api_timeout: float | None = Field(default=None, ge=5, le=180)
    cosyvoice_url: str | None = Field(default=None, max_length=2048)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @field_validator("llm_base_url", "speech_base_url", "cosyvoice_url", "tts_api_base_url", "index_tts_url", "moss_tts_url")
    @classmethod
    def valid_url(cls, value, info):
        if value is None or (dsh.enabled() and info.field_name == "llm_base_url" and value == "dsh://active"):
            return value
        try:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError
            _ = url.port
        except ValueError:
            raise ValueError("请输入不含密钥、查询参数或片段的 HTTP(S) 地址") from None
        return value.rstrip("/")

    @field_validator("tts_api_key", "moss_live_api_key", "systemone_api_key", "systemone_ark_api_key")
    @classmethod
    def valid_tts_key(cls, value):
        if value is not None and any(c in value for c in "\r\n"):
            raise ValueError("API 密钥不能包含换行")
        return value.strip() if value else value

    @field_validator("systemone_api_key", "systemone_ark_api_key")
    @classmethod
    def valid_systemone_key(cls, value):
        if value and any(not 33 <= ord(char) <= 126 for char in value):
            raise ValueError("判断模型密钥应为不含空白的 ASCII 字符")
        return value

    @field_validator("systemone_ark_model")
    @classmethod
    def valid_ark_model(cls, value):
        import re
        from .systemone_providers import ARK_MODEL
        if value is None:
            return value
        value = value.strip()
        if value != ARK_MODEL and not re.fullmatch(r"ep-[A-Za-z0-9][A-Za-z0-9-]{0,119}", value):
            raise ValueError("请填写 doubao-seed-2-1-lite-260915 或该模型的 ep- 推理接入点 ID")
        return value

    @field_validator("tts_api_base_url")
    @classmethod
    def secure_tts_url(cls, value):
        if value and urlsplit(value).scheme != "https" and urlsplit(value).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("远程 TTS API 必须使用 HTTPS；本机回环地址可使用 HTTP")
        return value

    @field_validator("cosyvoice_url", "index_tts_url", "moss_tts_url")
    @classmethod
    def local_cosyvoice_url(cls, value):
        if value and urlsplit(value).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("本地模型服务地址必须为本机回环地址")
        return value


class SessionCreate(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)


class ScreenSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(strict=True, min_length=1, max_length=200)


@app.post("/api/voice/screen/snapshot")
async def voice_screen_snapshot(value: ScreenSnapshotInput):
    if not dsh.enabled():
        return {"available": False, "reason": "unsupported_mode"}
    from .screen_registry import providers
    provider = providers.get(value.session_id)
    if provider is None:
        return {"available": False, "reason": "no_connection"}
    return await provider.snapshot()


class MemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/voice/config")
def voice_config():
    settings = store.settings(private=True)
    native = settings["conversation_mode"] == "moss_live"
    return {"conversation_mode": settings["conversation_mode"], "speech_architecture": "moss-live-deepseek-delegation" if native else "asr-llm-tts",
            "duplex_capable": True, "speech_to_speech_model": settings["moss_live_model"] if native else None,"engine": "pipecat", "version": "1.15.0", "transport": "protobuf-websocket",
            "endpoint": "/ws/voice", "input_sample_rate": 16000, "output_sample_rate": 24000,
            "turn_policy": "silero-smart-turn-chinese-transcription", "history": "playback-confirmed-contiguous-tts-context-prefix"}


@app.get("/api/settings")
async def get_settings():
    result = store.settings()
    if dsh.enabled():
        status = await dsh.BridgeClient().status()
        result.update(harness_provider="dsh", memory_owner="dsh", llm_model=status.get("model", ""),
                      llm_base_url="dsh://active", api_key_set=bool(status.get("configured")),
                        screen_model_ready=status.get("screen_ready") is True,
                      llm_temperature_managed=status.get("temperature_supported") is not True)
    return result


@app.get("/api/tts/voices")
async def tts_voices():
    """Read presets even while GPU mode has stopped the managed CPU service."""
    from .tts_voices import installed_catalog, service_catalog, VoiceCatalogUnavailable, MAX_CATALOG_BYTES
    address = store.settings(private=True)["moss_tts_url"].rstrip("/")
    # The same loopback-only validator as saved settings; do not follow redirects.
    SettingsUpdate(moss_tts_url=address)
    managed = address in {"http://127.0.0.1:8772", "http://localhost:8772"}
    try:
        async with asyncio.timeout(3), httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", address + "/v1/audio/voices") as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_CATALOG_BYTES:
                        raise VoiceCatalogUnavailable("MOSS 音色服务响应过大")
        import json
        return service_catalog(json.loads(raw))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        if managed:
            try:
                return await asyncio.to_thread(installed_catalog)
            except VoiceCatalogUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
        raise HTTPException(503, "无法连接所保存的 MOSS 服务，不能使用其他模型的音色清单") from None
    except (httpx.HTTPError, ValueError, TimeoutError):
        raise HTTPException(503, "MOSS 服务未提供有效音色清单，请更新服务后重试") from None


@app.put("/api/settings")
async def put_settings(value: SettingsUpdate):
    if dsh.enabled():
        bridge_status = await dsh.BridgeClient().status()
        # Presentation markers may be echoed by the UI; credentials are never saved.
        ignored = {"llm_base_url": None, "llm_model": None, "llm_api_key": None,
                   "harness_provider": None, "memory_owner": None, "api_key_set": None,
                   "llm_temperature_managed": None}
        if bridge_status.get("temperature_supported") is not True:
            ignored["temperature"] = None
        value = value.model_copy(update=ignored)
    async with voice_policy_lock:
        current = store.settings(private=True)
        owner_only = value.owner_voice_only if value.owner_voice_only is not None else current["owner_voice_only"]
        if value.clear_moss_live_api_key and value.moss_live_api_key:
            raise HTTPException(422, "清除密钥和设置新密钥不能同时提交。")
        conversation = value.conversation_mode or current["conversation_mode"]
        enabled = value.systemone_enabled if value.systemone_enabled is not None else current["systemone_enabled"]
        screen_enabled = value.screen_companion_enabled if value.screen_companion_enabled is not None else current["screen_companion_enabled"]
        idle_enabled = value.idle_companion_enabled if value.idle_companion_enabled is not None else current["idle_companion_enabled"]
        if value.idle_companion_enabled is True and not current['idle_companion_enabled'] and not dsh.enabled():
            raise HTTPException(409, "闲聊陪伴需要 DSH 原生语音模式。")
        if idle_enabled and conversation == "moss_live":
            raise HTTPException(409, "闲聊陪伴暂不支持 MOSS-Live 模式，请先关闭闲聊陪伴。")
        if screen_enabled and (conversation == "moss_live" or (not enabled and not dsh.enabled() and (value.screen_companion_mode or current["screen_companion_mode"]) == "systemone")):
            raise HTTPException(409, "屏幕陪玩需要启用 System One，且不支持 MOSS-Live 模式。")
        from .systemone_providers import provider_for
        effective = {**current, **value.model_dump(exclude_none=True, exclude_unset=True)}
        for key_name in ("systemone_api_key", "systemone_ark_api_key"):
            clearing = getattr(value, f"clear_{key_name}")
            replacement = getattr(value, key_name)
            if clearing and replacement:
                raise HTTPException(422, "清除密钥和设置新密钥不能同时提交。")
            effective[key_name] = replacement or ("" if clearing else current[key_name])
        provider = provider_for(effective)
        key = provider.key
        if enabled and not key:
            name = "方舟 API Key" if provider.name == "ark" else "TokenToSea API Key"
            raise HTTPException(409, f"启用判断层前请填写当前供应商的{name}。清除当前密钥时请同时关闭功能。")
        if enabled and conversation == "moss_live":
            raise HTTPException(409, "System One 判断层适用于 DeepSeek + 本地/API TTS；MOSS-Live 已自行控制轮次，请关闭其中一个。")
        if conversation == "moss_live" and owner_only:
            raise HTTPException(409, "MOSS-Live 云端语音模式暂不支持本地本人声纹筛选，请先关闭该选项。")
        if owner_only and (value.owner_voice_only is True or value.speech_base_url):
            address = value.speech_base_url or current["speech_base_url"]
            owner = await get_owner_status(address)
            if not owner.get("enabled") or not owner.get("ready") or not owner.get("enrolled"):
                raise HTTPException(409, "请先准备声纹模型并完成录入。")
        if value.clear_tts_api_key and value.tts_api_key:
            raise HTTPException(422, "清除密钥和设置新密钥不能同时提交。")
        if (value.tts_api_base_url and value.tts_api_base_url != current["tts_api_base_url"]
                and current["tts_api_key"] and not value.tts_api_key and not value.clear_tts_api_key):
            raise HTTPException(409, "更换 TTS API 地址时，请填写新密钥或勾选清除密钥。")
        api_provider = value.tts_api_provider or current["tts_api_provider"]
        api_voice = value.tts_api_voice if value.tts_api_voice is not None else current["tts_api_voice"]
        if api_provider == "deepseek" and api_voice not in {"stella", "tide"}:
            raise HTTPException(422, "DeepSeek TTS 音色必须为 stella（海星女声）或 tide（暗潮男声）。")
        voice_keys = ("gpu_tts_model", "moss_live_api_key", "moss_live_voice", "moss_live_model", "conversation_mode", "index_tts_url", "moss_tts_url", "speech_base_url", "voice", "tts_engine", "tts_mode", "cosyvoice_url",
                      "streaming_asr_preview", "tts_api_provider", "tts_api_filter_markdown", "tts_api_base_url", "tts_api_model", "tts_api_voice",
                      "tts_api_key", "tts_api_speed", "tts_api_timeout", "systemone_enabled", "systemone_api_key",
                      "systemone_provider", "systemone_ark_model", "systemone_ark_api_key",
                      "systemone_audio_enabled", "systemone_timeout_ms", "systemone_interrupt_threshold", "systemone_confidence",
                      "screen_companion_mode", "companion_interests", "idle_companion_enabled", "idle_companion_after_s",
                      "idle_companion_cooldown_s", "idle_companion_max_per_hour", "idle_companion_include_screen", "idle_companion_max_reply_chars",
                      "screen_companion_enabled", "screen_companion_style", "screen_companion_interval_ms", "screen_companion_change_threshold",
                      "screen_companion_cooldown_s", "screen_companion_max_judgments_per_hour", "screen_companion_max_replies_per_hour",
                      "screen_companion_speak_threshold", "screen_companion_wait_threshold", "screen_companion_max_reply_chars", "screen_companion_timeout_ms",
                      "screen_companion_refresh_ms", "screen_request_enabled", "screen_request_threshold", "screen_request_timeout_ms",
                      "systemone_initiative_enabled", "systemone_initiative_threshold",
                      "systemone_initiative_min_speech_ms", "systemone_initiative_cooldown_s",
                      "systemone_initiative_wait_threshold", "systemone_initiative_max_reply_chars",
                      "systemone_initiative_probe_interval_ms", "systemone_initiative_max_probes")
        changed = value.clear_tts_api_key or value.clear_moss_live_api_key or value.clear_systemone_api_key or value.clear_systemone_ark_api_key or owner_only != current["owner_voice_only"] or any(
            getattr(value, key) is not None and getattr(value, key) != current[key]
            and not (key in {"tts_api_key", "moss_live_api_key", "systemone_api_key", "systemone_ark_api_key"} and getattr(value, key) == "") for key in voice_keys)

        if dsh.enabled():
            changed = changed or any(getattr(value, key) is not None and getattr(value, key) != current[key]
                                     for key in ("system_prompt", "temperature"))
        result = store.update_settings(value.model_dump(exclude_unset=True))
        if changed:
            await close_old_voice_sessions()
        return await get_settings() if dsh.enabled() else result


@app.post("/api/systemone/test")
async def test_systemone():
    from .systemone import SystemOneClient
    from .systemone_providers import provider_for
    settings = store.settings(private=True)
    if not provider_for(settings).key:
        raise HTTPException(409, "请先保存当前判断供应商的 API Key。")
    client = SystemOneClient(settings)
    started = time.monotonic()
    try:
        result = await client.affect("很高兴见到你，我们开始吧。", [])
        return {"ok": result is not None, "provider": client.provider.name, "model": client.model, "reason": client.last_reason,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "behavior": result, "verified_input": "text" if result else None}
    finally:
        await client.close()


async def get_owner_status(address: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(address.rstrip("/") + "/v1/speaker/status")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid speaker status")
            return payload
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "无法连接本地声纹服务。") from None


@app.get("/api/voice/owner/status")
async def owner_status():
    settings = store.settings(private=True)
    status = await get_owner_status(settings["speech_base_url"])
    return {**status, "service_enabled": status.get("enabled", False), "enabled": settings["owner_voice_only"]}


@app.post("/api/voice/owner/enroll")
async def owner_enroll(files: list[UploadFile] = File(...)):
    if not 2 <= len(files) <= 5:
        raise HTTPException(422, "请提供 2 至 5 条录音。")
    uploads = []
    for item in files:
        data = await item.read(2_000_001)
        if len(data) > 2_000_000:
            raise HTTPException(413, "录音文件过大。")
        uploads.append(("files", ("enrollment.wav", data, "audio/wav")))
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(store.settings(private=True)["speech_base_url"].rstrip("/") + "/v1/speaker/enroll", files=uploads)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        raise HTTPException(error.response.status_code, "声纹录入失败，请检查录音和服务状态。") from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "无法连接本地声纹服务。") from None


@app.delete("/api/voice/owner/enrollment")
async def owner_delete():
    async with voice_policy_lock:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.delete(store.settings(private=True)["speech_base_url"].rstrip("/") + "/v1/speaker/enrollment")
                response.raise_for_status()
                payload = response.json()
                store.update_settings({"owner_voice_only": False})
                await close_old_voice_sessions()
                return payload
        except httpx.HTTPStatusError as error:
            raise HTTPException(error.response.status_code, "声纹删除失败。") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "无法连接本地声纹服务。") from None


@app.get("/api/voice/metrics/{session_id}")
def voice_metrics(session_id: str):
    from .voice_metrics import registry
    if not dsh.enabled() and not store.has_session(session_id):
        raise HTTPException(404, "会话不存在。")
    metrics = registry.get(session_id)
    if metrics is None:
        raise HTTPException(404, "没有该会话的语音指标。")
    return metrics.snapshot()


@app.get("/api/status")
async def status():
    settings = store.settings(private=True)
    llm = {"ready": False, "detail": "尚未连接"}
    speech = {"ready": False, "detail": "尚未连接"}
    optional = {"moss_tts": {"ready": False, "detail": "未连接"}, "index_tts": {"ready": False, "detail": "未连接"}}
    mode = resolve_tts_mode(settings)
    async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as client:
        async def probe(address, headers=None):
            try:
                async with asyncio.timeout(4):
                    return await client.get(address, headers=headers)
            except (httpx.HTTPError, TimeoutError):
                return None
        headers = {"Authorization": "Bearer " + settings["llm_api_key"]} if not dsh.enabled() and settings["llm_api_key"] else {}
        async def model_probe():
            if dsh.enabled():
                return None
            return await probe(settings["llm_base_url"].rstrip("/") + "/models", headers)
        model_response, speech_response, index_response, moss_response = await asyncio.gather(
            model_probe(),
            probe(settings["speech_base_url"].rstrip("/") + "/health"),
            probe(settings["index_tts_url"].rstrip("/") + "/health"),
            probe(settings["moss_tts_url"].rstrip("/") + "/health"),
        )
    if dsh.enabled():
        try:
            bridge_status = await dsh.BridgeClient().status()
            llm = {"ready": bridge_status.get("ready") is True, "configured": bridge_status.get("configured") is True,
                   "provider": "dsh", "model": bridge_status.get("model", ""), "detail": "DSH"}
        except dsh.BridgeUnavailable:
            llm = {"ready": False, "configured": False, "provider": "dsh", "detail": "DSH bridge unavailable"}
    elif model_response is None:
        llm["detail"] = "无法连接模型服务"
    elif model_response.is_success:
        llm = {"ready": True, "detail": "模型服务已连接", "model": settings["llm_model"]}
    elif model_response.status_code == 401:
        llm.update(detail="模型服务需要有效 API 密钥，请在设置中填写并保存。", needs_api_key=True)
    else:
        llm["detail"] = f"模型列表请求返回 HTTP {model_response.status_code}；部分服务不提供此接口"
    try:
        if speech_response is None:
            raise ValueError("not connected")
        if speech_response.is_success:
            payload = speech_response.json()
            asr, local_tts = payload.get("asr", {}), payload.get("tts", {})
            ready = asr.get("ready") is True
            speech = {**payload, "ready": ready,
                      "detail": ("本地识别可用" if mode in {"gpu", "api"} else "本地语音可用") if ready else "请检查本地语音模型"}
        else:
            speech["detail"] = f"语音服务返回 HTTP {speech_response.status_code}"
    except (ValueError, AttributeError):
        speech["detail"] = "无法连接本地语音服务"
    for name, response in (("index_tts", index_response), ("moss_tts", moss_response)):
        try:
            if response is not None and response.is_success:
                payload = response.json()
                if isinstance(payload, dict):
                    optional[name] = {k: payload[k] for k in (
                        "ready", "configured", "device", "device_requested", "effective_device", "gpu_eligible",
                        "hardware", "detail", "busy", "backend", "runtime", "verification", "model_name", "model_version", "precision_requested", "precision", "ar_backend", "cuda_graph_active", "delivery", "state", "preload", "resident", "warmed_up", "preparation_seconds") if k in payload}
        except ValueError:
            pass
    index = optional["index_tts"]
    from .tts_policy import gpu_model_name
    expected_gpu = gpu_model_name(settings)
    if mode == "auto":
        gpu = index.get("configured") is True and index.get("model_name") == expected_gpu and index.get("busy") is False and index.get("gpu_eligible") is True
        reason = "gpu_eligible" if gpu else "gpu_busy" if index.get("busy") else "gpu_unavailable"
        selected = "gpu" if gpu else "cpu"
    else:
        selected, reason = mode, "explicit_mode"
    if selected == "api":
        configured = api_configured(settings)
        deepseek = settings["tts_api_provider"] == "deepseek"
        tts = {"mode": "api", "provider": "DeepSeek TTS" if deepseek else "OpenAI-compatible", "device": "remote",
               "ready": False, "configured": configured, "verification": "not_probed",
               "detail": "已配置，首次合成时验证连接（可能产生费用）" if configured else "请选择音色并填写独立 DeepSeek TTS API 密钥" if deepseek else "请填写 API 地址、模型、音色和独立 TTS 密钥"}
    elif selected == "gpu":
        tts = {**index, "mode": "gpu", "provider": expected_gpu, "configured": index.get("configured", False) and index.get("model_name") == expected_gpu,
               "ready": index.get("ready") is True and index.get("device") == "cuda" and index.get("model_name") == expected_gpu,
               "detail": index.get("detail", "GPU 服务未启动；启动器会在保存后同步本地服务")}
        if index.get("model_name") and index["model_name"] != expected_gpu:
            tts["detail"] = "GPU 服务模型与保存选择不一致；启动器正在切换，请稍后重连"
    else:
        local = optional["moss_tts"]
        tts = {**local, "mode": "cpu", "provider": "MOSS-TTS-Nano ONNX", "ready": local.get("ready") is True and local.get("device") == "cpu" and local.get("backend") == "onnx",
               "detail": local.get("detail", "本地语音服务未连接")}
    native = settings["conversation_mode"] == "moss_live"
    if native:
        from .moss_live import configuration_status
        tts = {**configuration_status(settings), "mode": "moss_live"}
        speech = {"ready": False, "configured": tts["configured"], "detail": tts["detail"], "verification": "not_probed"}
        selected, reason = "moss_live", "explicit_conversation_mode"
    if dsh.enabled():
        settings["llm_model"] = llm.get("model", "")
        settings["llm_base_url"] = "dsh://active"
    return {"llm": llm, "speech": speech, "optional": optional, "tts": tts,
            "conversation": {"mode": settings["conversation_mode"], "duplex_capable": True,
                             "speech_to_speech_model": settings["moss_live_model"] if native else None, "llm_model": settings["llm_model"],
                             "llm_provider": "dsh" if dsh.enabled() else "DeepSeek" if "deepseek.com" in settings["llm_base_url"] else "OpenAI-compatible",
                             "audio_transport": "protobuf-websocket", "verification": "session_required"},
            "voice_policy": {"requested": mode, "saved_mode": settings["tts_mode"],
                             "predicted": selected, "reason": reason, "prediction_only": True}}


@app.post("/api/tts/load", status_code=202)
async def load_gpu_tts():
    settings = store.settings(private=True)
    if settings["conversation_mode"] == "moss_live" or resolve_tts_mode(settings) != "gpu":
        raise HTTPException(409, "仅显式 GPU 模式支持预加载；请先保存 GPU 模式")
    from .tts_policy import gpu_model_name
    address = settings["index_tts_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            health = await client.get(address + "/health")
            health.raise_for_status()
            if health.json().get("model_name") != gpu_model_name(settings):
                raise HTTPException(409, "模型服务正在切换，请稍后重试")
            if health.json().get("preload") is not True:
                raise HTTPException(409, "服务尚未切换为预加载模式，请等待启动器同步或重启项目")
            response = await client.post(address + "/v1/model/load")
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "无法准备 GPU 模型，请检查模型文件与本地服务日志") from None
    return {"accepted": True, "detail": "GPU 模型正在准备，请查看模型状态"}


@app.get("/api/sessions")
async def sessions():
    return await dsh.BridgeClient().sessions() if dsh.enabled() else store.sessions()


@app.post("/api/sessions", status_code=201)
async def create_session(value: SessionCreate | None = None):
    return await dsh.BridgeClient().create_session(value.session_id if value else None) if dsh.enabled() else {"id": store.session()}


@app.get("/api/sessions/{session_id}/messages")
async def messages(session_id: str):
    if dsh.enabled():
        return await dsh.BridgeClient().messages(session_id)
    if not store.has_session(session_id):
        raise HTTPException(404, "对话不存在")
    return store.messages(session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if dsh.enabled():
        result = await dsh.BridgeClient().delete_session(session_id)
        from .screen_registry import providers
        provider = providers.pop(session_id, None)
        if provider:
            await provider.close()
        return result
    if not store.delete_session(session_id):
        raise HTTPException(404, "对话不存在")
    return {"deleted": True}


@app.get("/api/memories")
def memories():
    if dsh.enabled():
        raise HTTPException(410, "Memory is managed by DSH")
    return store.memories()


@app.post("/api/memories", status_code=201)
def add_memory(value: MemoryInput):
    if dsh.enabled():
        raise HTTPException(410, "Memory is managed by DSH")
    if not value.content.strip():
        raise HTTPException(422, "记忆不能为空")
    return store.add_memory(value.content.strip())


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str):
    if dsh.enabled():
        raise HTTPException(410, "Memory is managed by DSH")
    if not store.delete_memory(memory_id):
        raise HTTPException(404, "记忆不存在")
    return {"deleted": True}


@app.websocket("/ws/chat")
async def retired_chat(websocket: WebSocket):
    await websocket.close(code=1008, reason="旧协议已停用，请使用 /ws/voice")


@app.websocket("/ws/voice")
async def voice(websocket: WebSocket, session_id: str | None = None):
    if not trusted_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    if dsh.enabled():
        try:
            bridge = dsh.BridgeClient()
            if not session_id:
                session_id = (await bridge.create_session())["id"]
            rows = await bridge.messages(session_id)
            bridge_status = await bridge.status()
            model = bridge_status.get("model")
            if not isinstance(model, str) or not model:
                raise dsh.BridgeUnavailable("DSH model unavailable")
            from .dsh import ProjectionStore
            voice_store = ProjectionStore(store, session_id, rows, bridge, model,
                                          bridge_status.get("temperature_supported") is True)
            voice_store.screen_model_ready = bridge_status.get("screen_ready") is True
        except (dsh.BridgeUnavailable, KeyError, TypeError):
            await websocket.close(code=1011, reason="DSH bridge unavailable")
            return
    else:
        session_id = store.session(session_id)
        voice_store = store
    async with voice_policy_lock:
        occupied = session_id in active_sessions
        if not occupied:
            active_sessions.add(session_id)
            active_voice_sockets[session_id] = websocket
    if occupied:
        await close_voice_socket(websocket, code=1008, reason="该会话已在另一个窗口使用，请关闭原窗口后重试")
        if getattr(voice_store, "is_dsh_projection", False):
            await voice_store.close()
        return
    try:
        if store.settings(private=True)["conversation_mode"] == "moss_live":
            from .moss_live import run_moss_voice
            await run_moss_voice(websocket, voice_store, session_id)
        else:
            from .pipecat_voice import run_voice
            await run_voice(websocket, voice_store, session_id)
    except Exception:
        log.exception("Pipecat voice pipeline failed")
        try:
            await websocket.close(code=1011, reason="语音服务启动失败，请查看本地日志")
        except RuntimeError:
            pass
    finally:
        active_sessions.discard(session_id)
        if active_voice_sockets.get(session_id) is websocket:
            active_voice_sockets.pop(session_id, None)
        if getattr(voice_store, "is_dsh_projection", False):
            await voice_store.close()


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    dist = ROOT / "web" / "dist"
    candidate = (dist / path).resolve()
    if not candidate.is_relative_to(dist.resolve()):
        raise HTTPException(404)
    if candidate.is_file():
        return FileResponse(candidate)
    index = dist / "index.html"
    if index.is_file() and not path.startswith("api/"):
        return FileResponse(index)
    raise HTTPException(404, "前端尚未构建。")
