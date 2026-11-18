#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf '%s\n' 'Usage: bash speech/setup_mfa_wsl.sh MICROMAMBA_ARCHIVE WSL_NATIVE_DIRECTORY' >&2
  exit 2
fi
archive=$(realpath "$1")
root=$2
mkdir -p "$root/bin" "$root/pkuseg"
python3 - "$archive" "$root/bin/micromamba" <<'PY'
import hashlib, pathlib, shutil, sys, tarfile
archive, target = map(pathlib.Path, sys.argv[1:])
if hashlib.sha256(archive.read_bytes()).hexdigest() != 'cec496f2299f9ceb5f5e23fc2ccf081fffda0c4bc87a6fdab575bf1e04f103b6':
    raise ValueError('micromamba archive hash mismatch')
with tarfile.open(archive, 'r:bz2') as src, src.extractfile('bin/micromamba') as binary, target.open('wb') as out:
    shutil.copyfileobj(binary, out)
target.chmod(0o755)
PY
python3 - "$archive" "$root/pkuseg" <<'PY'
import hashlib, pathlib, shutil, sys, zipfile
directory = pathlib.Path(sys.argv[1]).parent
cache = pathlib.Path(sys.argv[2])
models = {
    'spacy_ontonotes': ('b216e7f92de7ae285aeab8feba2faa8ea8216e5995ff6fb3d391cc8356db1bfe', ('features.msgpack', 'weights.npz')),
    'postag': ('afdf15f4e39bc47a39be4c37e3761b0c8f6ad1783f3cd3aff52984aebc0a1da9', ('features.pkl', 'weights.npz')),
}
for name, (expected, files) in models.items():
    path = directory / (name + '.zip')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f'{name} archive hash mismatch')
    dest = cache / name
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for filename in files:
            with archive.open(filename) as source, (dest / filename).open('wb') as output:
                shutil.copyfileobj(source, output)
PY
export MAMBA_ROOT_PREFIX="$root/root"
export PKUSEG_HOME="$root/pkuseg"
"$root/bin/micromamba" create -y -p "$root/env" -c conda-forge 'montreal-forced-aligner=3.3.9'
"$root/bin/micromamba" run -p "$root/env" python -m pip install 'spacy-pkuseg==1.0.2' 'dragonmapper==0.3.0' 'hanziconv==0.3.2'
"$root/bin/micromamba" run -p "$root/env" python -m pip install 'fastapi==0.162.0' 'uvicorn==0.54.0' 'python-multipart==0.0.33'
"$root/bin/micromamba" run -p "$root/env" mfa version
