"""Download a pinned Apache-2.0 model; reruns resume incomplete files."""
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    path = snapshot_download("OpenVINO/Qwen3-1.7B-int4-ov",
                             revision="6f32d81e9deebeca30bb5490a7176cf4fa8c79e3",
                             local_dir=ROOT / "models/qwen3-1.7b-int4", max_workers=4)
    print(f"Local model ready: {path}")
