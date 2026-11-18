"""Guard the offline frontend and GPU identity at the integration boundary."""
import sys
from types import SimpleNamespace

import httpx
import pytest

from speech.model_engines import configure_gsv_language_detector


def test_language_detector_uses_bundled_model_without_download(tmp_path, monkeypatch):
    bundled = tmp_path / "resources/lid.176.ftz"
    bundled.parent.mkdir()
    bundled.write_bytes(b"fake model")
    infer = SimpleNamespace(_default_detector=None)
    fake = SimpleNamespace(__file__=str(tmp_path / "__init__.py"), infer=infer,
                           LangDetectConfig=lambda **kw: kw, LangDetector=lambda config: config)
    monkeypatch.setitem(sys.modules, "fast_langdetect", fake)
    configure_gsv_language_detector()
    assert infer._default_detector == {"custom_model_path": str(bundled), "allow_fallback": False}
    bundled.unlink()
    with pytest.raises(RuntimeError, match="Missing bundled"):
        configure_gsv_language_detector()


@pytest.mark.asyncio
async def test_wrong_gpu_model_never_receives_synthesis_request():
    from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
    from speech.pipecat_services import LocalSpeechTTS
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"model_name": "IndexTTS-2.5"})
    service = LocalSpeechTTS(expected_model="GPT-SoVITS-v5-turbo")
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        frames = [frame async for frame in service.run_tts("你好", "context")]
        assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
        assert not any(isinstance(frame, TTSAudioRawFrame) for frame in frames)
        assert requests == ["/health"]
        assert "模型与保存选择不一致" in frames[0].error
    finally:
        await service.cleanup()
