"""Historical offline research only: fetch MFA Mandarin and Linux micromamba.

Not used by the application, launcher or realtime playback.
"""

import hashlib
import tempfile
import urllib.request
from pathlib import Path

from dafeiyu_paths import models_dir

FILES = {
    "micromamba-linux-64-2.5.0.tar.bz2": ("https://micro.mamba.pm/api/micromamba/linux-64/2.5.0", "cec496f2299f9ceb5f5e23fc2ccf081fffda0c4bc87a6fdab575bf1e04f103b6"),
    "mandarin_mfa-v3.0.0.zip": ("https://github.com/MontrealCorpusTools/mfa-models/releases/download/acoustic-mandarin_mfa-v3.0.0/mandarin_mfa.zip", "c4c91c499ada0de35346481d4af69c7328075ddb0ce16a8cfb19fc74d0401199"),
    "mandarin_china_mfa-v3.0.0.dict": ("https://github.com/MontrealCorpusTools/mfa-models/releases/download/dictionary-mandarin_china_mfa-v3.0.0/mandarin_china_mfa.dict", "0881d4e338e26509d022992cb5b897ead24a176448f534481238cb3a7fe949f0"),
    "spacy_ontonotes.zip": ("https://github.com/explosion/spacy-pkuseg/releases/download/v0.0.26/spacy_ontonotes.zip", "b216e7f92de7ae285aeab8feba2faa8ea8216e5995ff6fb3d391cc8356db1bfe"),
    "postag.zip": ("https://github.com/lancopku/pkuseg-python/releases/download/v0.0.16/postag.zip", "afdf15f4e39bc47a39be4c37e3761b0c8f6ad1783f3cd3aff52984aebc0a1da9"),
}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    target = models_dir(Path(__file__).resolve().parent.parent) / "mfa-mandarin"
    target.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in FILES.items():
        path = target / name
        if path.exists():
            if digest(path) != expected:
                raise ValueError(f"existing file hash mismatch: {path}")
            continue
        with tempfile.NamedTemporaryFile(dir=target, prefix="download-", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            urllib.request.urlretrieve(url, temporary)
            if digest(temporary) != expected:
                raise ValueError(f"download hash mismatch: {name}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Ready: {path}", flush=True)


if __name__ == "__main__":
    main()
