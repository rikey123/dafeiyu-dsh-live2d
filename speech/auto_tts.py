"""Per-response TTS selection using Pipecat's native service switcher."""

import httpx
from pipecat.frames.frames import ErrorFrame, LLMFullResponseStartFrame, ManuallySwitchServiceFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.service_switcher import ServiceSwitcher
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .pipecat_services import LocalSpeechTTS


class AutoTTSSelector(FrameProcessor):
    def __init__(self, cpu, gpu, health_url, gpu_model_name="IndexTTS-2.5", **kwargs):
        super().__init__(**kwargs)
        self.cpu = cpu
        self.gpu = gpu
        self.health_url = health_url
        self.gpu_model_name = gpu_model_name
        self._client = None
        self._force_cpu_once = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.UPSTREAM and isinstance(frame, ErrorFrame) and frame.processor is self.gpu:
            self._force_cpu_once = True
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMFullResponseStartFrame):
            eligible = False
            if self._force_cpu_once:
                self._force_cpu_once = False
            else:
                try:
                    if self._client is None:
                        self._client = httpx.AsyncClient(timeout=3.0)
                    response = await self._client.get(self.health_url)
                    response.raise_for_status()
                    data = response.json()
                    eligible = isinstance(data, dict) and data.get("gpu_eligible") is True and data.get("configured") is True and data.get("model_name") == self.gpu_model_name and data.get("busy") is False
                except (httpx.HTTPError, ValueError):
                    pass
            await self.push_frame(ManuallySwitchServiceFrame(service=self.gpu if eligible else self.cpu), direction)
        await self.push_frame(frame, direction)

    async def cleanup(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        await super().cleanup()


def AutoSpeechTTS(*, moss_base_url="http://127.0.0.1:8772", index_base_url="http://127.0.0.1:8770", voice="", gpu_model_name="IndexTTS-2.5"):
    cpu = LocalSpeechTTS(base_url=moss_base_url, voice=voice, sample_rate=24000,
                         reuse_context_id_within_turn=False)
    gpu = LocalSpeechTTS(base_url=index_base_url, voice="default", sample_rate=24000,
                         timeout=185, reuse_context_id_within_turn=False)
    selector = AutoTTSSelector(cpu, gpu, index_base_url.rstrip("/") + "/health", gpu_model_name=gpu_model_name)
    return Pipeline([selector, ServiceSwitcher(services=[cpu, gpu])])
