"""Adapters to upstream inference APIs; imported only inside isolated workers.

MOSS uses upstream OrtCpuRuntime directly. Index uses the 2.5 BF16 API; GPT-SoVITS
uses official v5 turbo with four steps and upstream PyTorch CUDA graph AR.
"""
from pathlib import Path
import sys
import os
import glob


def create_engine(kind, config):
    source = Path(config["source"]).resolve(strict=True)
    sys.path.insert(0, str(source))
    return {"index_tts": IndexEngine, "moss_tts": MossEngine, "gpt_sovits": GPTSoVITSEngine}[kind](config)


def configure_gsv_language_detector():
    """Use fast-langdetect's bundled model without per-phrase network retries.

    Pinned upstream LangSegmenter replaces this same process-local detector at
    import. Override it after importing TTS, using the library's public custom
    model configuration. Missing resources fail explicitly rather than fetching.
    """
    import fast_langdetect
    bundled = Path(fast_langdetect.__file__).parent / "resources/lid.176.ftz"
    if not bundled.is_file():
        raise RuntimeError("Missing bundled language detector; repair the GPT-SoVITS runtime")
    fast_langdetect.infer._default_detector = fast_langdetect.LangDetector(
        fast_langdetect.LangDetectConfig(custom_model_path=str(bundled), allow_fallback=False))


class GPTSoVITSEngine:
    """Official v5 turbo, four diffusion steps and upstream CUDA graph AR.

    The model returns sentence fragments, not codec-level streaming. Retain its
    reference cache across requests and resample the native rate continuously.
    """
    def __init__(self, config):
        original_glob = glob.glob
        def ordered(pattern, *args, **kwargs):
            matches = original_glob(pattern, *args, **kwargs)
            return sorted(matches) if str(pattern).replace("\\", "/").endswith("torch/lib/*.dll") else matches
        glob.glob = ordered
        try:
            import torch
        finally:
            glob.glob = original_glob
        if not torch.cuda.is_available():
            raise RuntimeError("GPT-SoVITS GPU mode requires CUDA; CPU fallback is disabled")
        torch.set_num_threads(int(config.get("threads", 4)))
        sys.path.insert(0, str(Path(config["source"]) / "GPT_SoVITS"))
        os.environ["bert_path"] = str(Path(config["model"]) / "chinese-roberta-wwm-ext-large")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from TTS_infer_pack.TTS import TTS, TTS_Config
        configure_gsv_language_detector()
        import soundfile as sf
        reference = sf.info(config["prompt_wav"])
        if not 3 <= reference.duration <= 10:
            raise ValueError("GPT-SoVITS reference recording must be 3–10 seconds")
        model = Path(config["model"])
        self.config = config
        self.model = TTS(TTS_Config({"custom": {
            "device": "cuda", "is_half": True, "version": "v5turbo",
            "t2s_weights_path": str(model / "s1v3.ckpt"),
            "vits_weights_path": str(model / "gsv-v5-pretrained/s2Gv5turbo.pth"),
            "bert_base_path": str(model / "chinese-roberta-wwm-ext-large"),
            "cnhuhbert_base_path": str(model / "chinese-hubert-base"),
        }}))
        if str(self.model.configs.device).split(":")[0] != "cuda" or self.model.configs.version != "v5turbo":
            raise RuntimeError("GPT-SoVITS did not load v5 turbo on CUDA")
        self.metadata = {"device": "cuda", "backend": "native-fp16", "precision": "fp16",
                         "variant": "v5turbo", "sample_steps": 4, "delivery": "sentence-fragments"}

    def stream(self, text, voice):
        if voice not in {"", "default"}:
            raise ValueError("GPT-SoVITS uses the configured reference voice")
        import numpy as np
        import soxr
        resampler = None
        source_rate = None
        for rate, audio in self.model.run({
            "text": text, "text_lang": "all_zh", "ref_audio_path": self.config["prompt_wav"],
            "prompt_text": self.config["prompt_text"], "prompt_lang": "all_zh",
            "text_split_method": "cut5", "batch_size": 1, "split_bucket": False,
            "parallel_infer": True, "return_fragment": True, "streaming_mode": False,
            "fragment_interval": 0.0, "sample_steps": 4, "cfg_rate": 0.0,
            "use_cuda_graph": True, "use_flash_attention": False, "super_sampling": False,
        }):
            accel = self.model.t2s_accel
            self.metadata.update(ar_backend=getattr(accel, "backend", "native"),
                                 cuda_graph_active=bool(getattr(accel, "graph_enabled", False)))
            if source_rate is None:
                source_rate = int(rate)
                resampler = soxr.ResampleStream(source_rate, 24000, 1, dtype="float32")
            elif int(rate) != source_rate:
                raise ValueError("GPT-SoVITS changed sample rate within a response")
            audio = np.asarray(audio)
            if audio.dtype != np.int16 or audio.ndim != 1:
                raise ValueError("GPT-SoVITS returned unexpected PCM format")
            converted = resampler.resample_chunk(audio.astype(np.float32) / 32768.0)
            if converted.size:
                yield (np.clip(converted, -1, 1) * 32767).astype("<i2").tobytes()
        if resampler is not None:
            tail = resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
            if tail.size:
                yield (np.clip(tail, -1, 1) * 32767).astype("<i2").tobytes()


class IndexEngine:
    def __init__(self, config):
        original_glob = glob.glob
        def ordered(pattern, *args, **kwargs):
            matches = original_glob(pattern, *args, **kwargs)
            return sorted(matches) if str(pattern).replace("\\", "/").endswith("torch/lib/*.dll") else matches
        glob.glob = ordered
        try:
            import torch
        finally:
            glob.glob = original_glob
        if not torch.cuda.is_available():
            raise RuntimeError("IndexTTS requires CUDA; CPU fallback is disabled")
        from indextts.infer_v2_5 import IndexTTS2
        # Upstream assigns a relative HF cache at import. Restore the explicit
        # local model directory before initialization; preparation is separate.
        os.environ["HF_HUB_CACHE"] = str(Path(config["model"]) / "hf_cache")
        import indextts.utils.model_download as downloads
        def missing_assets(*args, **kwargs):
            raise RuntimeError("IndexTTS auxiliary weights are missing; run prepare_tts_models.py explicitly")
        downloads.ensure_models_available = missing_assets
        self.config = config
        self.model = IndexTTS2(cfg_path=str(Path(config["model"]) / "config.yaml"),
                               model_dir=config["model"], device="cuda", use_bf16=True)
        if str(self.model.device).split(":")[0] != "cuda":
            raise RuntimeError("IndexTTS did not load on CUDA")
        self.metadata = {"device": "cuda", "backend": "native-bf16", "precision": "bf16"}

    def stream(self, text, voice):
        if voice not in {"", "default"}:
            raise ValueError("IndexTTS currently uses the configured reference voice")
        # The official 2.5 generator yields PCM-amplitude tensors at 22050 Hz.
        import numpy as np
        import soxr
        resampler = soxr.ResampleStream(22050, 24000, 1, dtype="float32")
        chunks = self.model.infer(spk_audio_prompt=self.config["prompt_wav"], text=text,
                                 output_path=None, lang="ZH", stream_return=True,
                                 max_text_tokens_per_segment=120, verbose=False)
        for chunk in chunks:
            audio = chunk.detach().float().cpu().numpy().reshape(-1) / 32768.0
            converted = resampler.resample_chunk(audio)
            if converted.size:
                yield (np.clip(converted, -1, 1) * 32767).astype("<i2").tobytes()
        tail = resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        if tail.size:
            yield (np.clip(tail, -1, 1) * 32767).astype("<i2").tobytes()


class MossEngine:
    def __init__(self, config):
        import sentencepiece as spm
        from ort_cpu_runtime import OrtCpuRuntime
        self.runtime = OrtCpuRuntime(config["model"], thread_count=int(config.get("threads", 4)),
                                     max_new_frames=1500, execution_provider="cpu")
        path = self.runtime.resolve_manifest_relative_path(self.runtime.manifest["model_files"]["tokenizer_model"])
        self.tokenizer = spm.SentencePieceProcessor(model_file=str(path))
        providers = {p for session in self.runtime.sessions.values() for p in session.get_providers()}
        if providers != {"CPUExecutionProvider"}:
            raise RuntimeError("MOSS CPU mode requires CPUExecutionProvider exclusively")
        self.metadata = {"device": "cpu", "backend": "onnx", "precision": "onnx-model"}

    def stream(self, text, voice):
        import numpy as np
        import soxr
        runtime = self.runtime
        voices = runtime.list_builtin_voices()
        preset = voices[0] if voice in {"", "default"} and voices else next((v for v in voices if v["voice"] == voice), None)
        if preset is None:
            raise ValueError("Unknown MOSS voice preset")
        tokens = self.tokenizer.encode(text, out_type=int)
        # Pipecat already aggregates sentences. Bound unusually long sentences
        # using the model's official text-token workflow, never truncate speech.
        rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        channels = int(runtime.codec_meta["codec_config"]["channels"])
        resampler = soxr.ResampleStream(rate, 24000, 1, dtype="float32")
        for start in range(0, len(tokens), 100):
            rows = runtime.build_voice_clone_request_rows(preset["prompt_audio_codes"], tokens[start:start+100])
            # The upstream callback is synchronous; use a bounded producer queue
            # so HTTP backpressure propagates all the way to token generation.
            import queue
            import threading
            pending = queue.Queue(maxsize=4)
            stopped = threading.Event()
            failures = []
            def put(value):
                while not stopped.is_set():
                    try:
                        pending.put(value, timeout=.1)
                        return
                    except queue.Full:
                        continue
                raise RuntimeError("MOSS stream cancelled")
            def produce():
                decode_frames = []
                runtime.codec_streaming_session.reset()
                def decode():
                    result = runtime.codec_streaming_session.run_frames(list(decode_frames))
                    decode_frames.clear()
                    if result is not None:
                        audio, length = result
                        if length > 0:
                            put(np.asarray(audio[0, :channels, :length], dtype=np.float32).mean(axis=0))
                def on_frame(_frames, _step, frame):
                    decode_frames.append(list(frame))
                    if len(decode_frames) >= 8:
                        decode()
                try:
                    runtime.generate_audio_frames(rows, on_frame=on_frame)
                    if decode_frames:
                        decode()
                except Exception as exc:
                    failures.append(exc)
                finally:
                    runtime.codec_streaming_session.reset()
                    if not stopped.is_set():
                        put(None)
            worker = threading.Thread(target=produce, daemon=True)
            worker.start()
            try:
                while True:
                    chunk = pending.get()
                    if chunk is None:
                        break
                    pcm = resampler.resample_chunk(chunk)
                    if pcm.size:
                        yield (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
                if failures:
                    raise failures[0]
            finally:
                stopped.set()
                worker.join(timeout=2)
        tail = resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        if tail.size:
            yield (np.clip(tail, -1, 1) * 32767).astype("<i2").tobytes()
