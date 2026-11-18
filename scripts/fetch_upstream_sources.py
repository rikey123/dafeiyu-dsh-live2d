"""Download research OSS source archives; never run upstream setup or fetch weights."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import time
import hashlib
import io
import urllib.request
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAMED = {
    'FunAudioLLM/CosyVoice': 'CosyVoice',
    'FunAudioLLM/SenseVoice': 'SenseVoice',
    'modelscope/FunASR': 'FunASR / Paraformer',
    'k2-fsa/sherpa-onnx': 'sherpa-onnx',
    'openai/whisper': 'Whisper',
    'SYSTRAN/faster-whisper': 'faster-whisper',
    'QwenLM/Qwen3-TTS': 'Qwen3-TTS',
    'QwenLM/Qwen3-ASR': 'Qwen3-ASR',
    'QwenLM/Qwen3-Omni': 'Qwen3-Omni',
    'OpenBMB/MiniCPM-o': 'MiniCPM-o',
    'THUDM/GLM-4-Voice': 'GLM-4-Voice',
    'kyutai-labs/moshi': 'Moshi',
    'TMElyralab/MuseTalk': 'MuseTalk',
    'snakers4/silero-vad': 'Silero VAD',
    'hexgrad/kokoro': 'Kokoro',
    'Open-LLM-VTuber/Open-LLM-VTuber-Web': 'Open-LLM-VTuber frontend',
    'suzuran0y/Live2D-LLM-Chat': 'Live2D-LLM-Chat (resolved by GitHub repository search)',
    'pipecat-ai/pipecat-client-web': 'Pipecat official browser client dependency',
    'pipecat-ai/pipecat-client-web-transports': 'Pipecat official browser transports dependency',
    'ollama/ollama': 'Ollama',
    'ggml-org/llama.cpp': 'llama.cpp',
    'vllm-project/vllm': 'vLLM',
    'vllm-project/vllm-omni': 'vLLM-Omni',
    'OpenBMB/VoxCPM': 'VoxCPM',
    'QwenLM/Qwen3.5': 'Qwen3.5',
    'electron/electron': 'Electron desktop shell',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('research', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--extra-repo', action='append', default=[], help='Additional owner/repo to source-review alongside the research inventory')
    args = parser.parse_args()
    content = args.research.read_text(encoding='utf-8-sig')
    repos = {}
    for owner, name in re.findall(r'https://github\.com/([\w.-]+)/([\w.-]+)', content):
        repo = f'{owner}/{name.removesuffix(".git").rstrip(".")}'
        repos[repo.lower()] = (repo, 'explicit research GitHub URL')
    for repo, name in NAMED.items():
        repos.setdefault(repo.lower(), (repo, f'named project: {name}'))
    for repo in args.extra_repo:
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            parser.error('--extra-repo must be an owner/repo name')
        repos.setdefault(repo.lower(), (repo, 'additional implementation source review'))
    folder = ROOT / 'artifacts/upstream-archives'
    folder.mkdir(parents=True, exist_ok=True)
    records = []

    def fetch(item):
        repo, origin = item
        path = folder / repo.replace('/', '__')
        record = {'repo': repo, 'origin': origin, 'url': f'https://github.com/{repo}', 'path': str(path)}
        started = time.monotonic()
        try:
            metadata = path / '.source.json'
            if metadata.exists():
                return json.loads(metadata.read_text(encoding='utf-8'))
            request = urllib.request.Request(f'https://api.github.com/repos/{repo}/commits/HEAD', headers={'User-Agent': 'Dafeiyu-source-audit'})
            try:
                commit = json.load(urllib.request.urlopen(request, timeout=30))['sha']
            except urllib.error.HTTPError as exc:
                if exc.code not in {403, 429}:
                    raise
                commit = None
            archive_url = f'https://codeload.github.com/{repo}/zip/{commit or "HEAD"}'
            data = urllib.request.urlopen(archive_url, timeout=180).read()
            archive_path = folder / (repo.replace('/', '__') + '.zip')
            archive_path.write_bytes(data)
            path.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if commit is None:
                    commit = archive.comment.decode('ascii').strip()
                    if not re.fullmatch(r'[0-9a-f]{40}', commit):
                        raise ValueError('Archive did not identify its commit')
                for member in archive.infolist():
                    relative = Path(*Path(member.filename).parts[1:])
                    if not relative.parts:
                        continue
                    target = (path / relative).resolve()
                    if not target.is_relative_to(path.resolve()):
                        raise ValueError('Archive path escaped destination')
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(member))
            record.update(commit=commit, archive=str(archive_path), sha256=hashlib.sha256(data).hexdigest())
            record['licenses'] = [p.name for p in path.iterdir() if p.is_file() and p.name.lower().startswith(('license', 'copying'))]
            record['status'] = 'downloaded'
            metadata.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            record.update(status='failed', error=str(exc))
        record['elapsed_s'] = round(time.monotonic() - started, 2)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(fetch, repos.values()):
            records.append(record)
            (folder / 'manifest.json').write_text(json.dumps({'method': 'Complete GitHub source archives at pinned commits; no LFS weights, no recursive submodules, no upstream setup executed.', 'repositories': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'downloaded': sum(r['status'] == 'downloaded' for r in records), 'failed': sum(r['status'] != 'downloaded' for r in records)}))


if __name__ == '__main__':
    main()
