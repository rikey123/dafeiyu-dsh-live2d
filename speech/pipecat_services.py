"""Pipecat adapters for the existing loopback speech service."""

from __future__ import annotations

import asyncio
import io
import json
import wave
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from pipecat.frames.frames import ErrorFrame, Frame, InterimTranscriptionFrame, OutputTransportMessageUrgentFrame, TTSAudioRawFrame, TTSStoppedFrame, TranscriptionFrame
from pipecat.processors.frameworks.rtvi.models import ServerMessage
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language


def pcm_wav(audio: bytes, rate: int) -> bytes:
    if not audio or len(audio) % 2 or rate != 16000 or len(audio) > 16000 * 2 * 30:
        raise ValueError("expected 16 kHz mono PCM16, at most 30 seconds")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(audio)
    return output.getvalue()


def decode_wav(data: bytes) -> tuple[bytes, int]:
    if len(data) > 15_000_000:
        raise ValueError("speech response exceeds size limit")
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("speech response must be mono PCM16 WAV")
        rate, frames = wav.getframerate(), wav.getnframes()
        if rate < 8000 or rate > 48000 or frames <= 0:
            raise ValueError("speech response has invalid sample rate or duration")
        samples = wav.readframes(frames)
        if len(samples) != frames * 2:
            raise ValueError("speech response is truncated")
        return samples, rate


class LocalSpeechSTT(SegmentedSTTService):
    """Use Pipecat VAD segmentation and the local SenseVoice HTTP endpoint."""

    @property
    def wants_wav_segments(self) -> bool:
        return False

    def can_generate_metrics(self) -> bool:
        return True

    def __init__(self, *, base_url: str = "http://127.0.0.1:8766", timeout: float = 90, owner_only: bool = False, streaming_preview: bool = False, decision_metadata: bool = False, decision_audio: bool = False, **kwargs):
        super().__init__(sample_rate=16000, settings=STTSettings(model=None, language=Language.ZH), **kwargs)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.owner_only = owner_only
        self.streaming_preview = streaming_preview and not owner_only
        self.decision_metadata = decision_metadata
        self.decision_audio = decision_metadata and decision_audio
        self._preview_task = None
        self._preview_queue = None
        self._preview_generation = 0
        self._preview_guard = None
        self._http_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout,
                trust_env=urlsplit(self.base_url).hostname not in {"localhost", "127.0.0.1", "::1"})
        return self._http_client

    async def cleanup(self):
        try:
            await self._close_preview()
            await super().cleanup()
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None

    async def _close_preview(self):
        if self._preview_guard is not None:
            self._preview_guard["active"] = False
            self._preview_guard = None
        task, self._preview_task = self._preview_task, None
        self._preview_queue = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _queue_preview(self, audio: bytes):
        if self._preview_queue is None:
            return
        for offset in range(0, len(audio), 16000):
            try:
                self._preview_queue.put_nowait(audio[offset:offset + 16000])
            except asyncio.QueueFull:
                if self._preview_guard is not None:
                    self._preview_guard["active"] = False
                self._preview_task.cancel()
                self._preview_queue = None
                return

    async def _preview(self, queue, guard=None):
        import websockets
        url = self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/v1/audio/stream"
        previous = ""
        emitted = ""
        try:
            async with websockets.connect(url, open_timeout=3, max_queue=4) as socket:
                ready = json.loads(await asyncio.wait_for(socket.recv(), 3))
                if ready.get("type") != "ready":
                    return
                while True:
                    await socket.send(await queue.get())
                    event = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    text = event.get("text") if event.get("type") == "preview" else None
                    if isinstance(text, str) and text and len(text) <= 4000:
                        if text == previous and text != emitted:
                            emitted = text
                            frame = InterimTranscriptionFrame(text=text, user_id="local", timestamp=datetime.now(timezone.utc).isoformat(), language=Language.ZH)
                            if guard is not None:
                                frame.metadata["preview_generation"] = guard["generation"]
                                frame.metadata["_preview_guard"] = guard
                            tokens, timestamps = event.get("tokens"), event.get("timestamps")
                            if isinstance(tokens, list) and isinstance(timestamps, list) and len(tokens) == len(timestamps) and all(isinstance(t, str) for t in tokens) and all(isinstance(t, (int, float)) and not isinstance(t, bool) and t >= 0 for t in timestamps):
                                frame.metadata["online_asr"] = {"tokens": tokens, "timestamps": timestamps, "endpoint": event.get("endpoint") is True, "verified": False}
                            await self.push_frame(frame)
                        previous = text
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, ValueError, websockets.WebSocketException):
            return

    async def _handle_user_started_speaking(self, frame):
        await self._close_preview()
        await super()._handle_user_started_speaking(frame)
        if self.streaming_preview:
            self._preview_generation += 1
            self._preview_guard = {"generation": self._preview_generation, "active": True}
            self._preview_queue = asyncio.Queue(maxsize=100)
            self._preview_task = asyncio.create_task(self._preview(self._preview_queue, self._preview_guard))
            self._queue_preview(bytes(self._audio_buffer))

    async def transcribe_snapshot(self, audio: bytes) -> str | None:
        """Bounded local preview, not a final transcript or a context/history write.

        Reuses the installed recognizer when an online ASR preview isn't
        available. A slow preview must not delay normal VAD/final recognition.
        Owner-only never uses this speculative path.
        """
        if self.owner_only or not audio:
            return None
        try:
            async with asyncio.timeout(2):
                response = await self._client().post(self.base_url + "/v1/audio/transcriptions",
                    data={"owner_only": "false"},
                    files={"file": ("preview.wav", pcm_wav(audio[-128000:], 16000), "audio/wav")})
                response.raise_for_status()
                result = response.json()
                text = result.get("text") if isinstance(result, dict) else None
                return text.strip()[:1000] if isinstance(text, str) and len(text) <= 4000 else None
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, OSError, wave.Error):
            return None

    async def process_frame(self, frame, direction):
        if self.decision_metadata:
            from pipecat.frames.frames import VADUserStartedSpeakingFrame
            if isinstance(frame, VADUserStartedSpeakingFrame):
                frame.metadata["systemone_segment"] = self._segment_count + 1
        await super().process_frame(frame, direction)

    async def _handle_user_stopped_speaking(self, frame):
        await self._close_preview()
        await super()._handle_user_stopped_speaking(frame)

    async def process_audio_frame(self, frame, direction):
        await super().process_audio_frame(frame, direction)
        if self._user_speaking:
            self._queue_preview(frame.audio)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        try:
            wav = pcm_wav(audio, self.sample_rate)
            response = await self._client().post(self.base_url + "/v1/audio/transcriptions", data={"owner_only": "true" if self.owner_only else "false"}, files={"file": ("input.wav", wav, "audio/wav")})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("invalid transcription response")
            if self.owner_only:
                decision = result.get("speaker")
                if not isinstance(decision, dict) or decision.get("accepted") is not True:
                    reason = decision.get("reason") if isinstance(decision, dict) else None
                    if reason not in {"insufficient_speech", "mismatch"}:
                        reason = "verification_unavailable"
                    message = ServerMessage(data={"type": "voice.speaker", "accepted": None if reason != "mismatch" else False, "reason": reason})
                    yield OutputTransportMessageUrgentFrame(message=message.model_dump(exclude_none=False))
                    return
            text = result.get("text")
            if not isinstance(text, str) or len(text) > 4000:
                raise ValueError("invalid transcription response")
            if text.strip():
                frame = TranscriptionFrame(text=text.strip(), user_id="local", timestamp=datetime.now(timezone.utc).isoformat(), language=Language.ZH, finalized=True)
                if self.decision_metadata:
                    frame.metadata["systemone_segment"] = self._transcribing_segment
                    # Only attach audio after owner verification, if enabled.
                    if self.decision_audio:
                        frame.metadata["systemone_pcm"] = audio[-self.sample_rate * 8:]
                yield frame
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, ValueError, OSError, wave.Error) as exc:
            if self.owner_only:
                message = ServerMessage(data={"type": "voice.speaker", "accepted": None, "reason": "verification_unavailable"})
                yield OutputTransportMessageUrgentFrame(message=message.model_dump(exclude_none=False))
            yield ErrorFrame(error=f"本地语音识别失败: {exc}")


class LocalSpeechTTS(TTSService):
    """Use native callback PCM when available, with WAV fallback."""

    def can_generate_metrics(self) -> bool:
        return True

    def __init__(self, *, base_url: str = "http://127.0.0.1:8766", voice: str = "", timeout: float = 120, sample_rate: int = 16000, expected_model: str | None = None, **kwargs):
        kwargs.setdefault("stop_frame_timeout_s", timeout + 1)
        super().__init__(sample_rate=sample_rate, push_start_frame=True, push_stop_frames=True, settings=TTSSettings(model=None, voice=voice or None, language=Language.ZH), **kwargs)
        self.base_url = base_url.rstrip("/")
        self.voice = voice
        self.timeout = timeout
        self.expected_model = expected_model
        self._http_client: httpx.AsyncClient | None = None
        self._tts_requests: dict[str, asyncio.Task] = {}

    async def on_audio_context_interrupted(self, context_id):
        task = self._tts_requests.get(context_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await super().on_audio_context_interrupted(context_id)

    async def on_turn_context_completed(self):
        # HTTP requests finish inline even if the final sentence yields only an
        # ErrorFrame. Pipecat infers synchronous completion from the last audio
        # frame; an error-only last request otherwise leaves the shared context
        # open until the long network idle timeout.
        context_id = self._turn_context_id
        if context_id and self.audio_context_available(context_id):
            await self.append_to_audio_context(context_id, TTSStoppedFrame(context_id=context_id))
            await self.remove_audio_context(context_id)
        await super().on_turn_context_completed()

    async def _push_spoken_text(self, src_frame, text, context_id, append_to_context):
        await super()._push_spoken_text(src_frame, text, context_id, append_to_context)
        if not self._reuse_context_id_within_turn and self.audio_context_available(context_id):
            await self.append_to_audio_context(context_id, TTSStoppedFrame(context_id=context_id))
            await self.remove_audio_context(context_id)

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout,
                trust_env=urlsplit(self.base_url).hostname not in {"localhost", "127.0.0.1", "::1"})
        return self._http_client

    async def cleanup(self):
        try:
            tasks = list(self._tts_requests.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await super().cleanup()
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        generator = self._run_tts_frames(text, context_id)
        try:
            while True:
                task = asyncio.create_task(anext(generator))
                self._tts_requests[context_id] = task
                try:
                    frame = await task
                except StopAsyncIteration:
                    return
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    return
                finally:
                    if self._tts_requests.get(context_id) is task:
                        self._tts_requests.pop(context_id, None)
                if isinstance(frame, ErrorFrame):
                    frame.metadata.setdefault("tts_context_id", context_id)
                yield frame
        finally:
            await generator.aclose()

    async def _run_tts_frames(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        stage = "本地语音合成"
        try:
            if self.expected_model:
                response = await self._client().get(self.base_url + "/health", timeout=3)
                response.raise_for_status()
                state = response.json()
                if not isinstance(state, dict) or state.get("model_name") != self.expected_model:
                    raise ValueError("GPU 服务模型与保存选择不一致，请等待模型切换完成或检查服务地址")
            async with self._client().stream("POST", self.base_url + "/v1/audio/speech/stream", json={"input": text, "voice": self.voice, "response_format": "pcm"}) as response:
                if response.status_code not in (404, 501):
                    response.raise_for_status()
                    rate = int(response.headers["X-Audio-Sample-Rate"])
                    if not 8000 <= rate <= 48000 or response.headers.get("X-Audio-Channels") != "1" or response.headers.get("X-Audio-Format") != "pcm_s16le":
                        raise ValueError("invalid streaming audio format")
                    pending = b""
                    total = 0
                    first = True
                    async for chunk in response.aiter_bytes():
                        pending += chunk
                        total += len(chunk)
                        if total > 15_000_000:
                            raise ValueError("speech response exceeds size limit")
                        size = len(pending) & ~1
                        if size:
                            if first:
                                await self.stop_ttfb_metrics()
                                first = False
                            yield TTSAudioRawFrame(audio=pending[:size], sample_rate=rate, num_channels=1, context_id=context_id)
                            pending = pending[size:]
                    if pending or first:
                        raise ValueError("invalid or empty streaming audio")
                    return
            response = await self._client().post(self.base_url + "/v1/audio/speech", json={"input": text, "voice": self.voice, "response_format": "wav"})
            response.raise_for_status()
            audio, rate = decode_wav(response.content)
            await self.stop_ttfb_metrics()
            yield TTSAudioRawFrame(audio=audio, sample_rate=rate, num_channels=1, context_id=context_id)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, OSError, wave.Error) as exc:
            frame = ErrorFrame(error=f"{stage}失败: {exc}")
            frame.metadata["tts_context_id"] = context_id
            yield frame
