"""Import the user's DeepSeek-chan archive into a local Live2D model directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

MAX_FILES = 300
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024


def safe_relative(value: str) -> PurePosixPath:
    if "\\" in value or "\0" in value or ":" in value:
        raise ValueError(f"unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in (".", "..") for part in path.parts):
        raise ValueError(f"unsafe archive path: {value!r}")
    return path


def write_local(root: Path, relative: PurePosixPath, data: bytes) -> None:
    target = root.joinpath(*relative.parts)
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError(f"output path contains a symbolic link: {relative}")
        parent.mkdir(exist_ok=True)
    if not target.parent.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise ValueError(f"output path escapes target directory: {relative}")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive, metadata_encoding="gbk") as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive entry names")
        models = [entry for entry in entries if entry.filename.endswith("/DeepSeek/大肥鱼.model3.json")]
        if len(models) != 1:
            raise ValueError("expected exactly one DeepSeek/大肥鱼.model3.json")
        original = models[0]
        if original.file_size > 1024 * 1024:
            raise ValueError("model manifest exceeds size limit")
        prefix = original.filename[: -len("大肥鱼.model3.json")]
        model = json.loads(archive.read(original).decode("utf-8-sig"))
        references = model["FileReferences"]
        required = [references["Moc"], references["Physics"], references["DisplayInfo"], *references["Textures"]]
        selected = {str(safe_relative(item)) for item in required}
        selected.add("大肥鱼.model3.json")
        for entry in entries:
            if entry.filename.startswith(prefix):
                local = entry.filename[len(prefix):]
                if (local.startswith("Exp3/") and local.endswith(".exp3.json")) or (local.startswith("Animation/") and local.endswith(".motion3.json")):
                    selected.add(str(safe_relative(local)))
        expression_paths = sorted(p for p in selected if p.startswith("Exp3/"))
        motion_paths = sorted(p for p in selected if p.startswith("Animation/"))
        if not expression_paths or not motion_paths:
            raise ValueError("model archive is missing expressions or motions")
        infos = []
        for local in sorted(selected):
            entry = archive.getinfo(prefix + local)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"invalid archive member: {entry.filename}")
            if entry.file_size > MAX_FILE_BYTES:
                raise ValueError(f"archive member exceeds size limit: {entry.filename}")
            infos.append((local, entry))
        if len(infos) > MAX_FILES or sum(entry.file_size for _, entry in infos) > MAX_TOTAL_BYTES:
            raise ValueError("model resources exceed extraction limits")
        for local, entry in infos:
            write_local(root, safe_relative(local), archive.read(entry))
        notices = [entry for entry in entries if entry.filename.endswith("DeepSeek免费 Live2D 模型使用须知.txt")]
        if len(notices) != 1 or notices[0].file_size > 1024 * 1024:
            raise ValueError("model usage notice missing or unexpectedly large")
        write_local(root, PurePosixPath("使用须知.txt"), archive.read(notices[0]))
        references["Expressions"] = [
            {"Name": PurePosixPath(p).name[:-len(".exp3.json")], "File": p}
            for p in expression_paths
        ]
        references["Motions"] = {}
        for motion in motion_paths:
            stem = PurePosixPath(motion).name[:-len(".motion3.json")]
            group = "Idle" if stem.lower() == "idle" else stem
            if group in references["Motions"]:
                raise ValueError(f"duplicate motion group: {group}")
            references["Motions"][group] = [{"File": motion}]
        model["Dafeiyu"] = {"Profile": "deepseek"}
        write_local(root, PurePosixPath("avatar.model3.json"), json.dumps(model, ensure_ascii=False, indent=2).encode("utf-8"))
        cdi = json.loads(archive.read(prefix + references["DisplayInfo"]).decode("utf-8-sig"))
        parameters = [p.get("Id", "") for p in cdi.get("Parameters", [])]
        interesting = [p for p in parameters if any(part in p.lower() for part in ("mouth", "eye", "angle", "body", "breath"))]
        print(json.dumps({"output": str(root), "expressions": len(expression_paths), "motion_groups": list(references["Motions"]), "parameter_ids": interesting, "license": "使用须知.txt"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
