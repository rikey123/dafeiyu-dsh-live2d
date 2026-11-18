"""Download pinned DSH community sources for review; never install or run them.

Uses only Python's standard library. No npm lifecycle scripts, plugin imports,
login cookies, DSH configuration changes, or automatic screen capture.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
import zipfile


PROJECTS = [
    ("01-personality", "Scorp1o117/dsh-soul-md"),
    ("01-personality", "ssamurias/dsh-fish"),
    ("01-personality", "Yuuyuko-uu/dsh-feiyu-mood"),
    ("01-personality", "Yuuyuko-uu/dsh-speak-up"),
    ("02-memory-optional", "Yuuyuko-uu/dsh-fish-memory"),
    ("02-memory-optional", "Scorp1o117/dsh-tdai-memory"),
    ("02-memory-optional", "Yuuyuko-uu/dsh-xingxi"),
    ("03-bilibili", "Yuuyuko-uu/dsh-bili-subagent"),
    ("03-bilibili", "Alterssss/dsh-bili-whale"),
    ("03-bilibili", "nullifyi/dsh-bili-pod"),
    ("03-bilibili", "InariNGT-Ofiicial/dsh-bili-humanism"),
    ("04-qq", "Yuuyuko-uu/dsh-qq-link"),
    ("04-qq", "tencent-connect/dsh-qqbot"),
    ("04-qq", "YUsaltyfish/dsh-onebot-qq"),
    ("04-qq", "zaofan-make/dsh-qqbot"),
    ("05-screen-companion", "Yuuyuko-uu/dsh-fish-buddy"),
    ("05-screen-companion", "pairun325/dsh-whale-sense"),
    ("05-screen-companion", "SAOS-3624/dsh-see-now"),
    ("06-integrated-alternatives", "Britneycode/dsh-fish-soul"),
    ("06-integrated-alternatives", "aureth-labs/dsh-aurabot-qq"),
    ("06-integrated-alternatives", "Yuuyuko-uu/dsh-tts-bridge"),
]
HEADERS = {"User-Agent": "Dafeiyu-DSH-source-review/1.0", "Accept": "application/vnd.github+json"}
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def fetch(url: str, limit: int = MAX_ARCHIVE) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=90) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError(f"Download exceeds {limit} bytes")
                return body
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("Retries exhausted")


def write_json(path: Path, value: object) -> None:
    pending = path.with_suffix(path.suffix + ".part")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(pending, path)


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive member: {name!r}")
    for part in path.parts:
        if part in (".", "..") or part.endswith((".", " ")) or re.search(r'[<>:"|?*\x00-\x1f]', part):
            raise ValueError(f"Unsafe archive member: {name!r}")
        if part.split(".")[0].upper() in RESERVED:
            raise ValueError(f"Reserved Windows filename: {name!r}")
    return path


def extract(archive: Path, target: Path, root: Path) -> dict:
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite reviewed sources: {target}")
    stage = root / (".extract-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > 30000 or sum(item.file_size for item in entries) > MAX_EXPANDED:
                raise ValueError("Archive expansion limit exceeded")
            roots = set()
            for entry in entries:
                relative = safe_relative(entry.filename)
                roots.add(relative.parts[0])
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Symlink not extracted: {entry.filename}")
                output = stage.joinpath(*relative.parts)
                output.resolve().relative_to(stage.resolve())
                if entry.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, output.open("xb") as sink:
                    shutil.copyfileobj(source, sink)
            if len(roots) != 1:
                raise ValueError("Expected one GitHub source root")
            target.parent.mkdir(parents=True, exist_ok=True)
            (stage / next(iter(roots))).rename(target)
            return {"archive_members": len(entries), "expanded_bytes": sum(x.file_size for x in entries)}
    finally:
        # Delete only the unique staging directory created inside this explicit root.
        stage.resolve().relative_to(root.resolve())
        if stage.name.startswith(".extract-"):
            shutil.rmtree(stage)


def manifests_at(root: Path) -> list[dict]:
    result = []
    for path in root.rglob("package.json"):
        if any(part in ("node_modules", ".git") for part in path.relative_to(root).parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError):
            continue
        if len(result) < 100:
            result.append({
                "file": path.relative_to(root).as_posix(),
                **{key: data[key] for key in ("name", "version", "license", "engines", "scripts", "dsh") if key in data},
            })
    return result


def download_one(root: Path, category: str, repo: str, previous: dict | None) -> dict:
    record = {"repository": repo, "source_url": f"https://github.com/{repo}", "category": category}
    try:
        if previous and previous.get("status") == "downloaded":
            archive = Path(previous["archive_path"])
            archive.resolve().relative_to(root.resolve())
            Path(previous["source_path"]).resolve().relative_to(root.resolve())
            if archive.is_file() and Path(previous["source_path"]).is_dir():
                if hashlib.sha256(archive.read_bytes()).hexdigest() == previous["archive_sha256"]:
                    print(f"CACHED {repo} @{previous['commit'][:12]}", flush=True)
                    return previous
        commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/HEAD", 4 * 1024 * 1024))
        sha = commit["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Unexpected commit ID")
        identifier = repo.replace("/", "--") + "-" + sha[:12]
        archive_url = f"https://codeload.github.com/{repo}/zip/{sha}"
        archive = root / "archives" / (identifier + ".zip")
        target = root / "sources" / category / identifier
        data = fetch(archive_url)
        archive.parent.mkdir(parents=True, exist_ok=True)
        pending = archive.with_suffix(".zip.part")
        pending.write_bytes(data)
        os.replace(pending, archive)
        extracted = extract(archive, target, root)
        record.update({
            "status": "downloaded", "commit": sha,
            "commit_date_utc": commit["commit"]["committer"]["date"],
            "archive_url": archive_url, "archive_sha256": hashlib.sha256(data).hexdigest(),
            "archive_bytes": len(data), "archive_path": str(archive), "source_path": str(target),
            "packages": manifests_at(target), **extracted,
        })
        print(f"DOWNLOADED {repo} @{sha[:12]} ({len(data)} bytes)", flush=True)
    except Exception as exc:
        record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        print(f"FAILED {repo}: {record['error']}", flush=True)
    return record


def download_package(root: Path, project: dict) -> dict:
    """Fetch an exact published tarball directly, without running npm/pnpm."""
    package = next((item for item in project.get("packages", []) if item["file"] == "package.json"), {})
    name, version = package.get("name"), package.get("version")
    record = {"repository": project["repository"], "name": name, "version": version}
    if not name or not version:
        return {**record, "status": "no_root_package"}
    try:
        if not re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", name):
            raise ValueError("Invalid npm package name")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
            raise ValueError("Invalid npm version")
        url = "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@") + "/" + urllib.parse.quote(version, safe="")
        metadata = json.loads(fetch(url, 8 * 1024 * 1024))
        if metadata.get("name") != name or metadata.get("version") != version:
            raise ValueError("Registry returned a different package identity")
        distribution = metadata["dist"]
        parsed = urllib.parse.urlparse(distribution["tarball"])
        if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
            raise ValueError("Unexpected tarball host; review it manually")
        payload = fetch(distribution["tarball"])
        integrity = distribution.get("integrity", "")
        verified = False
        for entry in integrity.split():
            algorithm, _, expected = entry.partition("-")
            if algorithm in ("sha512", "sha256"):
                actual = base64.b64encode(hashlib.new(algorithm, payload).digest()).decode("ascii")
                verified = verified or hmac.compare_digest(actual, expected)
        if not verified:
            raise ValueError("Missing or mismatched SHA-256/SHA-512 registry integrity")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) > 30000 or sum(item.size for item in members) > MAX_EXPANDED:
                raise ValueError("Package expansion limit exceeded")
            for item in members:
                safe_relative(item.name)
                if item.issym() or item.islnk() or not (item.isfile() or item.isdir()):
                    raise ValueError("Package contains a link or special file")
            manifest = bundle.getmember("package/package.json")
            if manifest.size > 1024 * 1024:
                raise ValueError("Oversized package manifest")
            with bundle.extractfile(manifest) as source:
                contents = json.load(source)
            if contents.get("name") != name or contents.get("version") != version:
                raise ValueError("Tarball package identity mismatch")
        output = root / "npm-tarballs" / (name.replace("/", "--") + "-" + version + ".tgz")
        output.resolve().relative_to(root.resolve())
        output.parent.mkdir(parents=True, exist_ok=True)
        pending = output.with_suffix(".tgz.part")
        pending.write_bytes(payload)
        os.replace(pending, output)
        record.update({"status": "downloaded", "path": str(output), "registry_url": url,
            "tarball_url": distribution["tarball"], "registry_integrity": integrity,
            "registry_integrity_verified": True, "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload), "npm_git_head": metadata.get("gitHead"),
            "source_commit_equals_npm_git_head": metadata["gitHead"] == project["commit"] if metadata.get("gitHead") else None,
            "lifecycle_scripts": {key: value for key, value in contents.get("scripts", {}).items()
                if key in ("preinstall", "install", "postinstall", "prepare", "prepack")}})
        print(f"PACKAGE {name}@{version} ({len(payload)} bytes; integrity verified)", flush=True)
    except urllib.error.HTTPError as exc:
        record.update({"status": "version_not_on_npm" if exc.code == 404 else "failed", "error": str(exc)})
        print(f"NO PACKAGE {name}@{version}: {record['status']}", flush=True)
    except Exception as exc:
        record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        print(f"PACKAGE FAILED {name}@{version}: {record['error']}", flush=True)
    return record


def write_index(root: Path, projects: list[dict], packages: list[dict]) -> None:
    published = {item["repository"]: item for item in packages}
    lines = ["# DSH community source download index", "", "Downloaded for review only; nothing installed or enabled.", "",
        "Source commits and npm release artifacts are recorded separately. Equal version numbers do not imply identical source commits.", ""]
    hashes = []
    category = None
    for project in sorted(projects, key=lambda item: (item["category"], item["repository"])):
        if category != project["category"]:
            category = project["category"]
            lines.extend([f"## {category}", ""])
        lines.extend([f"### {project['repository']}", "", f"- Source: {project['source_url']}", f"- Status: {project['status']}"])
        if project["status"] == "downloaded":
            package = next((item for item in project.get("packages", []) if item["file"] == "package.json"), {})
            lines.extend([f"- Package: `{package.get('name', '')}@{package.get('version', '')}`",
                f"- Commit: `{project['commit']}` ({project['commit_date_utc']})",
                f"- Sources: [{Path(project['source_path']).name}]({Path(project['source_path']).as_posix()})",
                f"- ZIP: [{Path(project['archive_path']).name}]({Path(project['archive_path']).as_posix()})",
                f"- ZIP SHA-256: `{project['archive_sha256']}`"])
            hashes.append(f"{project['archive_sha256']} *{Path(project['archive_path']).relative_to(root).as_posix()}")
        artifact = published.get(project["repository"])
        if artifact:
            lines.append(f"- npm artifact: {artifact['status']}")
            if artifact["status"] == "downloaded":
                lines.extend([f"- TGZ: [{Path(artifact['path']).name}]({Path(artifact['path']).as_posix()})",
                    f"- Registry integrity: `{artifact['registry_integrity']}` (verified)",
                    f"- npm gitHead matches source: `{artifact['source_commit_equals_npm_git_head']}`"])
                hashes.append(f"{artifact['sha256']} *{Path(artifact['path']).relative_to(root).as_posix()}")
        lines.append("")
    (root / "source-index.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "SHA256SUMS.txt").write_text("\n".join(sorted(hashes)) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--packages", action="store_true", help="Also download exact npm tarballs, with integrity verification; no installation")
    args = parser.parse_args()
    root = args.destination.resolve()
    # Keep this project's downloads off the system drive, as requested.
    if root.drive.upper() == os.environ.get("SystemDrive", "C:").upper():
        parser.error("Choose a non-system drive for third-party downloads")
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    previous = {item["repository"]: item for item in old.get("projects", [])}
    records_by_repo = {repo: previous[repo] for _, repo in PROJECTS if repo in previous}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(download_one, root, category, repo, previous.get(repo)) for category, repo in PROJECTS]
        for future in concurrent.futures.as_completed(tasks):
            record = future.result()
            records_by_repo[record["repository"]] = record
            write_json(manifest, {"mode": "source-review-only", "plugins_installed": False,
                "downloaded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "projects": sorted(records_by_repo.values(), key=lambda item: (item["category"], item["repository"]))})
    records = list(records_by_repo.values())
    success = sum(item["status"] == "downloaded" for item in records)
    print(f"RESULT {success}/{len(PROJECTS)} source archives downloaded. Manifest: {manifest}")
    packages = []
    if args.packages:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            packages = list(pool.map(lambda project: download_package(root, project),
                [record for record in records if record["status"] == "downloaded"]))
        write_json(root / "npm-tarballs-manifest.json", {"mode": "download-only-no-install", "packages": packages})
        print(f"PACKAGES {sum(item['status'] == 'downloaded' for item in packages)} verified npm tarballs saved")
    elif (root / "npm-tarballs-manifest.json").exists():
        packages = json.loads((root / "npm-tarballs-manifest.json").read_text(encoding="utf-8")).get("packages", [])
    write_index(root, records, packages)
    return 0 if success == len(PROJECTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
