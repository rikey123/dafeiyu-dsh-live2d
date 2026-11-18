"""OpenAI-compatible streaming PCM through the maintained SDK and Pipecat.

Reuse local TTS context retirement and interruption cancellation. Never retry a
billable request or replay a partially spoken response on a different provider.
Providers must implement POST /audio/speech with 24 kHz mono PCM16 output.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from urllib.parse import urlsplit
import httpx
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, OpenAIError
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

from .pipecat_services import LocalSpeechTTS


class APISpeechTTS(LocalSpeechTTS):
    def __init__(self, *, base_url, api_key, model, voice, speed=1.0, timeout=60, **kwargs):
        super().__init__(base_url=base_url, voice=voice, timeout=timeout,
                         sample_rate=24000, reuse_context_id_within_turn=False, **kwargs)
        self.model = model
        self.speed = speed
        self._api_key = api_key
        self._api_client = None

    def _sdk(self):
        if self._api_client is None:
            self._api_client = AsyncOpenAI(
                api_key=self._api_key, base_url=self.base_url, max_retries=0,
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                http_client=httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=5.0), follow_redirects=False,
                    limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
                    trust_env=urlsplit(self.base_url).hostname not in {"localhost", "127.0.0.1", "::1"},
                ),
            )
        return self._api_client

    async def cleanup(self):
        try:
            await super().cleanup()
        finally:
            if self._api_client is not None:
                await self._api_client.close()
                self._api_client = None

    async def _run_tts_frames(self, text, context_id):
        if not self._api_key:
            yield ErrorFrame(error="请在语音设置中填写独立的 TTS API 密钥。")
            return
        try:
            deadline = asyncio.get_running_loop().time() + self.timeout
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(self.timeout):
                    response = await stack.enter_async_context(self._sdk().audio.speech.with_streaming_response.create(
                        input=text, model=self.model, voice=self.voice,
                        response_format="pcm", speed=self.speed,
                    ))
                # Reject containers and JSON errors before they reach the speaker.
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"application/octet-stream", "audio/pcm", "audio/raw", "audio/l16"}:
                    raise ValueError("unexpected audio content type")
                if content_type == "audio/l16":
                    # audio/L16 specifies big-endian; contract requires little-endian.
                    raise ValueError("unsupported big-endian PCM")
                pending, total, first = b"", 0, True
                chunks = response.iter_bytes(4800).__aiter__()
                while True:
                    try:
                        remaining = max(0, deadline - asyncio.get_running_loop().time())
                        async with asyncio.timeout(remaining):
                            chunk = await anext(chunks)
                    except StopAsyncIteration:
                        break
                    pending += chunk
                    total += len(chunk)
                    if total > 15_000_000:
                        raise ValueError("audio exceeds size limit")
                    if first and pending[:4] in {b"RIFF", b"OggS", b"fLaC"}:
                        raise ValueError("container instead of PCM")
                    size = len(pending) & ~1
                    if size:
                        if first:
                            await self.stop_ttfb_metrics()
                            first = False
                        yield TTSAudioRawFrame(pending[:size], 24000, 1, context_id=context_id)
                        pending = pending[size:]
                if pending or first:
                    raise ValueError("empty or truncated PCM")
                await self.start_tts_usage_metrics(text)
        except (TimeoutError, APITimeoutError):
            yield ErrorFrame(error="TTS API 请求超时，请检查网络或调整超时时间。")
        except APIStatusError as error:
            # Do not expose response bodies, request headers or provider-supplied text.
            code = error.status_code
            detail = {401: "密钥无效", 403: "没有调用权限", 404: "地址或模型不存在",
                      429: "额度不足或请求过于频繁"}.get(code, "服务返回错误")
            yield ErrorFrame(error=f"TTS API：{detail}（HTTP {code}）。")
        except APIConnectionError:
            yield ErrorFrame(error="无法连接 TTS API，请检查地址和网络。")
        except (ValueError, httpx.HTTPError):
            yield ErrorFrame(error="TTS API 音频不符合 24kHz 单声道 PCM16 接口约定。")
        except OpenAIError:
            yield ErrorFrame(error="TTS API 返回了无法处理的响应，请检查兼容接口配置。")
