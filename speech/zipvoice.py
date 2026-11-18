"""Optional local sherpa-onnx ZipVoice, with explicit local reference audio."""

import os
import wave
from pathlib import Path

from dafeiyu_paths import models_dir

import numpy as np


def load_zipvoice():
    root = Path(__file__).resolve().parent.parent
    model = Path(os.environ.get("DAFEIYU_ZIPVOICE_MODEL", str(models_dir(root) / "zipvoice-zh-en")))
    reference = Path(os.environ.get("DAFEIYU_ZIPVOICE_REFERENCE", ""))
    text = os.environ.get("DAFEIYU_ZIPVOICE_REFERENCE_TEXT", "").strip()
    if not reference.is_file() or not text or len(text) > 1000:
        raise ValueError("ZipVoice 需要本地参考 WAV 和对应的参考文本")
    with wave.open(str(reference), "rb") as wav:
        rate, frames = wav.getframerate(), wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= rate <= 48000 or not 0 < frames <= rate * 30:
            raise ValueError("ZipVoice 参考音频必须是 30 秒以内的单声道 PCM16 WAV")
        raw = wav.readframes(frames)
        if len(raw) != frames * 2:
            raise ValueError("ZipVoice 参考 WAV 不完整")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    import sherpa_onnx
    lexicons = [str(model / "lexicon.txt")]
    if (model / "lexicon-en-us.txt").is_file():
        lexicons.append(str(model / "lexicon-en-us.txt"))
    zipvoice = sherpa_onnx.OfflineTtsZipvoiceModelConfig(tokens=str(model / "tokens.txt"), encoder=str(model / "encoder.int8.onnx"), decoder=str(model / "decoder.int8.onnx"), vocoder=str(model / "vocos_24khz.onnx"), lexicon=",".join(lexicons))
    config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(zipvoice=zipvoice, provider="cpu", num_threads=4), max_num_sentences=1)
    if not config.validate():
        raise ValueError("ZipVoice 模型不完整")
    return sherpa_onnx.OfflineTts(config), text, samples, rate


def generate_zipvoice(tts, text, reference_text, reference_samples, reference_rate, speed, callback):
    return tts.generate(text, reference_text, reference_samples, reference_rate, speed=speed, num_steps=4, callback=callback)
