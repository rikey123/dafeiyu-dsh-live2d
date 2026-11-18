"""Local sherpa-onnx Kokoro Chinese/English model loader."""

import os
from pathlib import Path

from dafeiyu_paths import models_dir


def load_kokoro():
    import sherpa_onnx
    root = Path(__file__).resolve().parent.parent
    model = Path(os.environ.get("DAFEIYU_KOKORO_MODEL", str(models_dir(root) / "kokoro-int8-multi-lang-v1_0")))
    kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(model / "model.int8.onnx"), voices=str(model / "voices.bin"), tokens=str(model / "tokens.txt"),
        lexicon=",".join(str(model / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt")),
    )
    config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(kokoro=kokoro, provider="cpu", num_threads=4), rule_fsts=",".join(str(model / name) for name in ("phone-zh.fst", "date-zh.fst", "number-zh.fst")), max_num_sentences=1)
    if not config.validate():
        raise ValueError("Kokoro 模型文件不完整")
    return sherpa_onnx.OfflineTts(config)
