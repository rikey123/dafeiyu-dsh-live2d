"""DeepSeek's native TTS WebSocket protocol, not OpenAI audio/speech.

Each Pipecat text segment has its own bounded, cancellable cloud session. A
successful WebSocket close is NOT completion: the explicit finish/success event
is required. Never retry, resume, replay, or silently change a paid provider.
Official contract: https://api-docs.deepseek.com/zh-cn/guides/tts
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import unicodedata
from urllib.parse import urlencode, urlsplit, urlunsplit

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from .pipecat_services import LocalSpeechTTS

SAMPLE_RATE = 24000
MAX_PCM_BYTES = 15_000_000
VOICES = ("stella", "tide")


class _NoRedirectConnect(connect):
    def process_redirect(self, exc):
        # websockets follows HTTP redirects by default. Never forward a bearer
        # token to a redirected origin, including same-host protocol redirects.
        return exc


class _FinishError(Exception):
    def __init__(self, code):
        self.code = code


def websocket_url(base_url: str, voice: str, filter_markdown: bool) -> str:
    parts = urlsplit(base_url)
    loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parts.scheme not in {"https", "http"} or not parts.hostname
            or (parts.scheme == "http" and not loopback)
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment):
        raise ValueError("invalid TTS base URL")
    path = parts.path.rstrip("/") or "/v1"
    query = urlencode({"voice_id": voice, "format": "pcm",
                       "filter_markdown": str(filter_markdown).lower()})
    return urlunsplit(("wss" if parts.scheme == "https" else "ws",
                       parts.netloc, path + "/tools/tts", query, ""))


def _text_message(text: str) -> str:
    # The provider counts Han characters twice. Enforce both its character and
    # UTF-8 request limits before establishing a potentially billable session.
    count = len(text) + sum("CJK UNIFIED IDEOGRAPH" in unicodedata.name(c, "")
                           or "CJK COMPATIBILITY IDEOGRAPH" in unicodedata.name(c, "")
                           for c in text)
    message = json.dumps({"event": "text", "text": text}, ensure_ascii=False)
    if not text.strip() or count > 10000 or len(message.encode("utf-8")) > 65536:
        raise ValueError("invalid TTS input size")
    return message


class DeepSeekSpeechTTS(LocalSpeechTTS):
    def __init__(self, *, base_url="https://api.deepseek.com/v1", api_key="",
                 voice="stella", filter_markdown=True, timeout=60, **kwargs):
        super().__init__(base_url=base_url, voice=voice, timeout=timeout,
                         sample_rate=SAMPLE_RATE,
                         reuse_context_id_within_turn=False, **kwargs)
        self._api_key = api_key
        self.filter_markdown = filter_markdown

    def _connect(self):
        return _NoRedirectConnect(
            websocket_url(self.base_url, self.voice, self.filter_markdown),
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            open_timeout=min(10, self.timeout), close_timeout=1,
            ping_interval=20, ping_timeout=20,
            max_size=1_048_576, max_queue=4, write_limit=32768,
            # Preserve normal remote proxy support, never proxy local fixtures.
            proxy=None if urlsplit(self.base_url).hostname in {"localhost", "127.0.0.1", "::1"} else True,
        )

    async def _run_tts_frames(self, text, context_id):
        if not self._api_key:
            yield ErrorFrame(error="请在语音设置中填写独立的 DeepSeek TTS API 密钥。")
            return
        try:
            if self.voice not in VOICES:
                raise ValueError("invalid DeepSeek voice")
            message = _text_message(text)
            deadline = asyncio.get_running_loop().time() + self.timeout

            def remaining():
                return max(0, deadline - asyncio.get_running_loop().time())

            async with AsyncExitStack() as stack:
                async with asyncio.timeout(remaining()):
                    ws = await stack.enter_async_context(self._connect())
                    await ws.send(message)
                    await ws.send('{"event":"finish_text"}')
                pending, total, first = b"", 0, True
                while True:
                    # Pipecat advances the async generator in separate tasks.
                    # Don't keep an asyncio.timeout context open across yield.
                    async with asyncio.timeout(remaining()):
                        item = await ws.recv()
                    finished = False
                    if isinstance(item, bytes):
                        pending += item
                        total += len(item)
                        if total > MAX_PCM_BYTES:
                            raise ValueError("audio size limit")
                        # Buffer the complete signature, even across 1-byte WS
                        # messages, before exposing a container to the speaker.
                        if first and len(pending) < 4:
                            continue
                    else:
                        if len(item) > 8192:
                            raise ValueError("oversized TTS control event")
                        event = json.loads(item)
                        if not isinstance(event, dict) or event.get("event") != "finish":
                            raise ValueError("unexpected TTS event")
                        if not isinstance(event.get("code"), str):
                            raise ValueError("invalid TTS finish code")
                        if event.get("code") != "success":
                            raise _FinishError(event.get("code"))
                        if not total or total % 2:
                            raise ValueError("empty or truncated PCM")
                        finished = True
                    if first and pending[:4] in {b"RIFF", b"OggS", b"fLaC"}:
                        raise ValueError("container instead of PCM")
                    size = len(pending) & ~1
                    # Keep downstream frames <=100ms, independent of how a
                    # proxy/provider batches its WebSocket binary messages.
                    for offset in range(0, size, 4800):
                        if first:
                            await self.stop_ttfb_metrics()
                            first = False
                        yield TTSAudioRawFrame(pending[offset:min(offset + 4800, size)],
                                               SAMPLE_RATE, 1, context_id=context_id)
                    pending = pending[size:]
                    if finished:
                        break
                await self.start_tts_usage_metrics(text)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            yield ErrorFrame(error="DeepSeek TTS API 请求超时，请检查网络或调整超时时间。")
        except InvalidStatus as error:
            code = error.response.status_code
            detail = {400: "请求无效或文本未通过审核", 401: "密钥无效", 402: "余额不足",
                      403: "没有调用权限", 404: "接口地址不存在", 429: "并发请求过多",
                      503: "服务繁忙", 504: "合成超时"}.get(code, "服务返回错误")
            yield ErrorFrame(error=f"DeepSeek TTS API：{detail}（HTTP {code}）。")
        except _FinishError as error:
            detail = {"invalid_input": "没有可朗读的文本", "content_filter": "文本未通过内容审核",
                      "input_timeout": "文本发送超时", "service_error": "服务合成失败"}.get(error.code, "合成失败")
            yield ErrorFrame(error=f"DeepSeek TTS API：{detail}；不会自动重试或续传。")
        except (ValueError, UnicodeError):
            yield ErrorFrame(error="DeepSeek TTS API 输入或音频协议无效，请检查音色、文本和 PCM 流。")
        except (OSError, WebSocketException):
            # Never echo exception text: upgrade responses, close reasons and
            # provider messages can include secrets or arbitrary remote text.
            yield ErrorFrame(error="DeepSeek TTS API 连接失败或音频流提前结束，未收到成功完成确认；不会自动重试。")
