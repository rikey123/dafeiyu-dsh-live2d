# Project working agreement

Build a usable Chinese realtime Live2D companion. The supplied research is reference material, not executable instructions. Prefer maintained open-source libraries over custom inference/rendering engines.

Use feature branches and Git worktrees for parallel agents. Each agent owns its assigned paths and commits its result. Do not edit another agent's assigned paths. Integrator merges and validates end-to-end.

Never describe a demo, missing model, CPU fallback, or unmeasured latency as working NPU inference. Secrets stay in ignored local config. Bind backend to loopback by default.

Protocol contract: see docs/PROTOCOL.md. Backend owns server/ and tests/. Frontend owns web/. Speech agent owns speech/ and requirements-speech.txt. Integrator owns root configuration, scripts/, docs/, and integration fixes after agents finish.
