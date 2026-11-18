# CosyVoice model probes

The selected model is now Fun-CosyVoice3-0.5B-2512; configuration and current
validation are documented in [COSYVOICE3.md](../docs/COSYVOICE3.md). The sidecar
defaults to version3. The following CPU measurements are historical CosyVoice2
results and must not be relabelled as third-generation performance. To reproduce
that old model, explicitly use version2 and verify its weights with
`python -m server.cosyvoice_prepare <model-dir> --version 2 --verify-only`.

Source: CosyVoice commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`,
Matcha-TTS submodule `dd9105b34bf2be2230f4aa1e4769fb586a3c824e`. Model revision
`eec1ae6c79877dbd9379285cf8789c9e0879293d`.

Use an isolated Linux Python 3.12 environment. Tested core dependencies:
CPU torch/torchaudio 2.3.1, numpy 1.26.4, transformers 4.51.3,
onnxruntime 1.18.0, hyperpyyaml 1.2.3, librosa 0.10.2, soundfile 0.12.1,
modelscope 1.20.0, huggingface-hub 0.36.2, conformer 0.3.2, diffusers 0.29.0,
x-transformers 2.11.24, lightning 2.2.4, rich 13.7.1, gdown 5.1.0,
omegaconf 2.3.0, hydra-core 1.3.2, onnx 1.16.0, pyarrow 18.1.0,
pyworld 0.3.4, openai-whisper 20231117, tiktoken, matplotlib 3.9.4,
contourpy <1.4, wget 3.2 and inflect 7.3.1. Preserve numpy 1.26.4:
ONNX Runtime 1.18 fails to import with numpy 2. OpenAI Whisper was installed
with setuptools <81 and `--no-build-isolation --no-deps`; its CUDA Triton
dependency was not installed for this CPU-only test. Building pyworld on
Python 3.12 requires a C++ compiler and Python headers.

Set `PYTHONPATH` to the CosyVoice source and pinned Matcha checkout, then run
`OMP_NUM_THREADS=4 timeout 240 python -m server.cosyvoice_probe MODEL_DIR
UPSTREAM_SOURCE/asset/zero_shot_prompt.wav --version 2 --output probe-v2.wav`. Model load, first PCM, output
duration and real-time factor are printed. The test uses the upstream example
prompt, never a user's recording. The timeout is mandatory for unattended runs.

The sidecar runs the model in a separate worker process, caches the prompt and
reuses the worker after a completed session. Cancellation or disconnect kills
and joins the worker; the next request loads a fresh process. Set
`DAFEIYU_COSY_MODEL`, `DAFEIYU_COSY_SOURCE`, `DAFEIYU_COSY_MATCHA`,
`DAFEIYU_COSY_PROMPT_WAV`, `DAFEIYU_COSY_PROMPT_TEXT`, and
`DAFEIYU_COSY_DEVICE=cpu` and `DAFEIYU_COSY_VERSION=2` for this historical model, then run `python -m server.cosyvoice_sidecar` in
the isolated environment. It binds to `127.0.0.1:8770` by default.

On the tested CPU, a cold ready took 53.9 seconds and synthesis of 4.28 seconds
of audio completed in 80.4 seconds including loading; the next ready took
0.016 seconds. These measurements do not establish real-time performance or
NPU execution. The persistent test environment lives under
`~/.local/share/dafeiyu-runtimes/cosy`; its separate compiler and Python
headers were needed to build pyworld without modifying system Python.

The exact tested CPU environment is recorded in
[`requirements-cosyvoice-cpu-lock.txt`](../requirements-cosyvoice-cpu-lock.txt).
It includes explicit versions for the installed dependency closure, uses the
public PyTorch CPU index and contains no local paths. In a clean Python3.12
virtual environment, install `setuptools==80.10.2`, `wheel` and `numpy==1.26.4`
first, provide a C++ compiler and matching Python headers, then install the
snapshot with `python -m pip install --no-deps --no-build-isolation -r
requirements-cosyvoice-cpu-lock.txt`. `--no-deps` preserves this tested CPU
closure instead of installing Whisper's unrelated Triton dependency. This
snapshot is for CPU reproducibility; GPU deployment requires a compatible
CUDA PyTorch environment and its own actual-device validation.

CosyVoice accepts continuously generated text without applying its normal
whole-text normalization. The application uses the native generator API and
consumption acknowledgments to bound in-flight text; it does not claim that
token streaming normalizes numbers or improves pronunciation automatically.
