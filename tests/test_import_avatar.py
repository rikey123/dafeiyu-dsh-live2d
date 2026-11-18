"""Original distribution and repository ZIPs share the same Live2D assets."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location("avatar_import", Path(__file__).resolve().parents[1] / "scripts/import_avatar.py")
avatar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatar)

NOTICE = "# 大肥鱼（DeepSeek-chan）免费 Live2D 模型使用须知\n原画及拆分：神宫凉子；Live2D：霓虹猫_NeonNeko\n禁止擅自重新分发模型文件\n".encode()
MODEL = json.dumps({"Version": 3, "FileReferences": {"Moc": "大肥鱼.moc3", "Physics": "大肥鱼.physics3.json", "DisplayInfo": "大肥鱼.cdi3.json", "Textures": ["大肥鱼.4096/texture_00.png"]}}, ensure_ascii=False).encode()


def members(prefix, notice="README.md"):
    return {
        prefix + "大肥鱼.model3.json": MODEL,
        prefix + "大肥鱼.moc3": b"fixture-moc",
        prefix + "大肥鱼.physics3.json": b"{}",
        prefix + "大肥鱼.cdi3.json": b'{"Parameters":[{"Id":"ParamMouthOpenY"}]}',
        prefix + "大肥鱼.4096/texture_00.png": b"fixture-texture",
        prefix + "Exp3/脸红.exp3.json": b"{}",
        prefix + "Animation/IDLE.motion3.json": b"{}",
        prefix + "Animation/举手.motion3.json": b"{}",
        prefix + "不要导入.psd": b"fixture-psd",
        prefix + notice: NOTICE,
    }


def archive(tmp_path, files, symlink=None):
    path = tmp_path / "model.zip"
    with zipfile.ZipFile(path, "w") as stream:
        for name, data in files.items():
            if name == symlink:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                stream.writestr(info, data)
            else:
                stream.writestr(name, data)
    return path


def run(monkeypatch, source, output):
    monkeypatch.setattr(sys, "argv", ["import_avatar.py", str(source), "--output", str(output)])
    with contextlib.redirect_stdout(io.StringIO()) as result:
        avatar.main()
    return json.loads(result.getvalue())


@pytest.mark.parametrize("prefix,notice", [
    ("DeepSeek免费公皮/DeepSeek/", "../DeepSeek免费 Live2D 模型使用须知.txt"),
    ("DeepSeek-chan-824e03aa/", "README.md"),
    ("", "README.md"),
    ("DeepSeek/", "使用须知.txt"),
])
def test_import_original_and_repository_zip(tmp_path, monkeypatch, prefix, notice):
    files = members(prefix)
    if notice != "README.md":
        del files[prefix + "README.md"]
        # Original distribution notice lives beside, not inside, DeepSeek/.
        name = str(Path(prefix + notice).as_posix())
        if "../" in name:
            name = "DeepSeek免费公皮/DeepSeek免费 Live2D 模型使用须知.txt"
        files[name] = NOTICE
    output = tmp_path / "output"
    result = run(monkeypatch, archive(tmp_path, files), output)
    assert result["expressions"] == 1
    assert set(result["motion_groups"]) == {"Idle", "举手"}
    assert (output / "大肥鱼.model3.json").read_bytes() == MODEL
    assert (output / "使用须知.txt").read_bytes() == NOTICE
    assert (output / "大肥鱼.4096/texture_00.png").read_bytes() == b"fixture-texture"
    assert not (output / "不要导入.psd").exists()
    adapted = json.loads((output / "avatar.model3.json").read_text(encoding="utf-8"))
    assert adapted["FileReferences"]["Expressions"] == [{"Name": "脸红", "File": "Exp3/脸红.exp3.json"}]
    assert adapted["Dafeiyu"]["Profile"] == "deepseek"


@pytest.mark.parametrize("broken", ["missing-notice", "unrelated-readme", "multiple-models", "missing-texture", "path-escape", "bad-cdi", "no-motion", "symlink-model", "symlink-notice"])
def test_invalid_archive_leaves_existing_character_unchanged(tmp_path, monkeypatch, broken):
    prefix = "repo/"
    files = members(prefix)
    link = None
    if broken == "missing-notice":
        del files[prefix + "README.md"]
    elif broken == "unrelated-readme":
        files[prefix + "README.md"] = b"# Some code project, not model terms"
    elif broken == "multiple-models":
        files["other/大肥鱼.model3.json"] = MODEL
    elif broken == "missing-texture":
        del files[prefix + "大肥鱼.4096/texture_00.png"]
    elif broken == "path-escape":
        files[prefix + "大肥鱼.model3.json"] = MODEL.replace("大肥鱼.moc3".encode(), b"../escape.moc3")
    elif broken == "bad-cdi":
        files[prefix + "大肥鱼.cdi3.json"] = b"not-json"
    elif broken == "no-motion":
        files = {name: data for name, data in files.items() if "/Animation/" not in name}
    elif broken == "symlink-model":
        link = prefix + "大肥鱼.model3.json"
    elif broken == "symlink-notice":
        link = prefix + "README.md"
    output = tmp_path / "existing"
    output.mkdir()
    (output / "avatar.model3.json").write_bytes(b"existing-avatar")
    (output / "使用须知.txt").write_bytes(b"existing-notice")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises((ValueError, KeyError)):
        run(monkeypatch, archive(tmp_path, files, symlink=link), output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
