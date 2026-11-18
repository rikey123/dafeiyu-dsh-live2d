"""Pipecat token-mode adapter for the local CosyVoice sidecar."""

import asyncio
import json
from collections import deque
from collections.abc import AsyncGenerator

import websockets
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService, TextAggregationMode
from pipecat.transcriptions.language import Language


class CosyBistreamTTS(TTSService):
    def __init__(self, *, url="ws://127.0.0.1:8770/v1/tts/bistream", timeout=120, startup_timeout=300, require_cuda=False, **kwargs):
        super().__init__(sample_rate=24000, text_aggregation_mode=TextAggregationMode.TOKEN, push_start_frame=True, push_stop_frames=True, stop_frame_timeout_s=max(timeout, startup_timeout) + 1, settings=TTSSettings(model=None, voice=None, language=Language.ZH), **kwargs)
        self.require_cuda = require_cuda
        self.url = url
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self._socket = None
        self._reader = None
        self._context = None
        self._failed_contexts = deque(maxlen=128)
        self._ack_enabled = False
        self._ack_sequence = 0
        self._ack_waiter = None

    def can_generate_metrics(self):
        return True

    async def _close(self, cancel=False):
        if self._ack_waiter is not None and not self._ack_waiter.done():
            self._ack_waiter.cancel()
        socket, self._socket = self._socket, None
        reader, self._reader = self._reader, None
        self._context = None
        # Stop the reader before closing its socket: local cancellation is not
        # a provider failure and must not complete a retired context in silence.
        if cancel and reader and reader is not asyncio.current_task():
            reader.cancel()
        if socket:
            if cancel:
                try:
                    await socket.send(json.dumps({"type": "cancel"}))
                except websockets.WebSocketException:
                    pass
            await socket.close()
        if reader and reader is not asyncio.current_task():
            await asyncio.gather(reader, return_exceptions=True)

    async def _receive(self, socket, context_id, rate):
        first = True
        try:
            while True:
                message = await asyncio.wait_for(socket.recv(), self.timeout)
                if isinstance(message, bytes):
                    if not message or len(message) % 2:
                        raise ValueError("invalid PCM frame")
                    if first:
                        await self.stop_ttfb_metrics()
                        first = False
                    if self.audio_context_available(context_id):
                        await self.append_to_audio_context(context_id, TTSAudioRawFrame(audio=message, sample_rate=rate, num_channels=1, context_id=context_id))
                else:
                    event = json.loads(message)
                    if event.get("type") == "text_ack":
                        if not self._ack_enabled or self._ack_waiter is None or self._ack_waiter.done() or type(event.get("sequence")) is not int or event["sequence"] != self._ack_sequence:
                            raise ValueError("unexpected text acknowledgement")
                        self._ack_waiter.set_result(None)
                        continue
                    if event.get("type") == "done":
                        if first:
                            raise ValueError("empty sidecar audio")
                        if self.audio_context_available(context_id):
                            await self.append_to_audio_context(context_id, TTSStoppedFrame(context_id=context_id))
                            await self.remove_audio_context(context_id)
                        return
                    if event.get("type") == "error":
                        raise ValueError(str(event.get("message") or event.get("reason") or "sidecar error"))
                    raise ValueError("unexpected sidecar event")
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, ValueError, websockets.WebSocketException) as exc:
            if self._socket is not socket or context_id in self._failed_contexts:
                return
            if self._ack_waiter is not None and not self._ack_waiter.done():
                self._ack_waiter.set_exception(exc)
            self._failed_contexts.append(context_id)
            error = ErrorFrame(error=f"本地 CosyVoice 失败: {str(exc) or type(exc).__name__}")
            error.metadata["tts_context_id"] = context_id
            await self.push_error_frame(error)
            if self.audio_context_available(context_id):
                await self.append_to_audio_context(context_id, TTSStoppedFrame(context_id=context_id))
                await self.remove_audio_context(context_id)
        finally:
            if self._socket is socket:
                self._socket = None
                self._context = None
            await socket.close()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        try:
            if context_id in self._failed_contexts or not self.audio_context_available(context_id):
                return
            if self._socket is None:
                deadline = asyncio.get_running_loop().time() + min(self.startup_timeout, 10)
                while True:
                    if context_id in self._failed_contexts or not self.audio_context_available(context_id):
                        return
                    socket = await websockets.connect(self.url, open_timeout=5, max_size=4_000_000)
                    self._socket = socket
                    self._context = context_id
                    try:
                        await socket.send(json.dumps({"type": "init"}))
                    except websockets.ConnectionClosed:
                        # A busy sidecar may close immediately after its error.
                        pass
                    ready = json.loads(await asyncio.wait_for(socket.recv(), self.startup_timeout))
                    if ready.get("type") != "error" or ready.get("reason") != "busy":
                        break
                    await socket.close()
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("CosyVoice is still finishing the previous turn")
                    await asyncio.sleep(.1)
                if ready.get("type") == "error":
                    raise ValueError(str(ready.get("message") or ready.get("reason") or "sidecar error"))
                rate = ready.get("sample_rate")
                if ready.get("type") != "ready" or not isinstance(rate, int) or not 8000 <= rate <= 48000 or ready.get("channels") != 1 or ready.get("format") != "pcm_s16le":
                    raise ValueError("invalid sidecar audio format")
                if self.require_cuda and ready.get("device") != "cuda":
                    raise ValueError("GPU 模式要求 CUDA，当前服务未使用 CUDA；请切换 CPU 或自动模式。")
                self._ack_enabled = ready.get("text_ack") is True
                self._ack_sequence = 0
                self._reader = asyncio.create_task(self._receive(socket, context_id, rate))
            if self._context != context_id:
                raise ValueError("sidecar context mismatch")
            if self._ack_enabled:
                self._ack_sequence += 1
                self._ack_waiter = asyncio.get_running_loop().create_future()
            await self._socket.send(json.dumps({"type": "text", "text": text}, ensure_ascii=False))
            if self._ack_enabled:
                await asyncio.wait_for(self._ack_waiter, self.timeout)
                self._ack_waiter = None
            yield None
        except asyncio.CancelledError:
            if self._context == context_id:
                await self._close(cancel=True)
            raise
        except (OSError, TimeoutError, ValueError, websockets.WebSocketException) as exc:
            if context_id in self._failed_contexts:
                return
            self._failed_contexts.append(context_id)
            if self._context == context_id:
                await self._close(cancel=True)
            error = ErrorFrame(error=f"本地 CosyVoice 失败: {str(exc) or type(exc).__name__}")
            error.metadata["tts_context_id"] = context_id
            yield error

    async def flush_audio(self, context_id=None):
        socket = self._socket
        if socket is not None and context_id == self._context:
            try:
                await socket.send(json.dumps({"type": "end"}))
            except websockets.WebSocketException:
                if self._socket is socket and context_id not in self._failed_contexts:
                    raise

    async def on_audio_context_interrupted(self, context_id):
        self._failed_contexts.append(context_id)
        if context_id == self._context:
            await self._close(cancel=True)
        await super().on_audio_context_interrupted(context_id)

    async def cleanup(self):
        await self._close(cancel=True)
        self._failed_contexts.clear()
        await super().cleanup()
