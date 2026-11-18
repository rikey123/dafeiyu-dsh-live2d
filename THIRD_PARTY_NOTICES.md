# Distribution notices

This package contains application code and a compiled frontend. The project
owner has not selected an open-source license for the application; the npm
manifest therefore declares `UNLICENSED`. This does not relicense upstream work.
Choose and document the application license before a public open-source release.

## Excluded user and model data

No API keys, `.env`, credentials, databases, conversation history, voice profiles,
model weights, Python environments, caches, or user-supplied character assets
belong in the distributable. Optional model downloads are separate, explicit
installation operations governed by each upstream model's license.

DeepSeek-chan illustration/separation: 神宫凉子. Live2D rigging: 霓虹猫_NeonNeko.
The supplied character's notice prohibits unauthorized redistribution of the
complete model. It is **not included**. Users import their lawfully obtained
archive into their external installation home. Direct acquisition references:

- Author's original release: https://www.bilibili.com/video/BV1KmxY66EZ3/
- Public community asset repository: https://github.com/YJackie-Li/DeepSeek-chan
- Referenced revision: `824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f` (checked 2026-11-18).

The GitHub maintainer's identity has not been verified as the model author.
Its README retains the restriction against unauthorized rehosting of the full
model; public availability is not treated as a redistribution license. Version
0.3.1 accepts its repository ZIP as well as the original distribution archive,
and preserves the full supplied usage notice. See `docs/DEEPSEEK_SKIN.md`.

The first-run installer can alternatively download a user-authorized archive
from a supplied HTTPS location after SHA-256 verification. It supplies no default
character URL and does not host or redistribute the original character.

uv is downloaded separately from Astral's official 0.13.7 release, not bundled.
Both the archive and extracted executable are verified against pinned SHA-256
values. uv and its dependencies retain their upstream licenses (MIT / Apache-2.0).

Live2D Cubism Core and the optional Haru sample are **not included**. Cubism Core
is separately subject to Live2D's proprietary software/SDK distribution terms.
An explicit local import or license-acknowledged download is required. See
`web/LIVE2D-LICENSE.md`. A license acknowledgement is not a grant of redistribution
rights, and this package does not claim to grant any such rights.

## Included third-party components

The bundled frontend includes React/ReactDOM (MIT), PixiJS (MIT),
pixi-live2d-display (MIT), Lucide (ISC), es-toolkit (MIT), Pipecat browser client
and WebSocket transport (BSD-2-Clause), and wLipSync (MIT). The build collects
their installed license files into `app/notices/frontend/` and records exact
package versions in `app/notices/frontend-dependencies.json`. The renderer patch
derived from AIRI is documented in `app/notices/renderer-patches.md`.

The optional blue-whale persona is distributed with its original MIT license,
attribution, and source metadata in `app/personas/blue-whale/`. It is not installed
over the user's existing DSH personality automatically.

DSH itself is provided by the host, not embedded into this package. Its model
providers, tool permissions, sessions, agent loop, delegation and memory remain
the host's responsibility. Python packages are installed separately from the
included requirement files; their own licenses continue to apply.
