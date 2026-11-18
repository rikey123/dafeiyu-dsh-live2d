# Live2D renderer patch

`pixi-live2d-display+0.4.0.patch` contains only the `dist/cubism4.es.js` section of Project AIRI's patch at commit `759fff0e646364fe3ad78c64a12f5f9739877e7a`: <https://github.com/moeru-ai/airi/blob/759fff0e646364fe3ad78c64a12f5f9739877e7a/patches/pixi-live2d-display.patch>.

The upstream AIRI repository is MIT licensed: <https://github.com/moeru-ai/airi/blob/759fff0e646364fe3ad78c64a12f5f9739877e7a/LICENSE>. The underlying Cubism framework and Core have separate Live2D terms; see `web/LIVE2D-LICENSE.md`.

The upstream complete patch SHA-256 is `cee60f8b5121eb195718c1935f9a3a6012cc8d4e8b6deeafd29bad772c678530`. The patched `cubism4.es.js` SHA-256 after normalizing CRLF to LF is `654f5760c5c34fd31499a550555f8de34602c18a6dbe0131f780ffbc2f35eec8`. `patch-package` applies the diff to the pinned dependency during install and fails if the patch cannot be applied. The package's CommonJS and Cubism 2 entries are not patched; this application imports the Cubism 4 ESM entry.

Build prerequisites include development dependencies: run `npm ci --include=dev` before building. `npm ci --omit=dev` is not supported because it omits the build and patch tools.

`@pipecat-ai+websocket-transport+1.8.2.patch` requests browser echo cancellation, noise suppression and automatic gain control for the official recorder. These are browser constraints, not a guarantee of acoustic echo cancellation. It preserves initial silent audio frames while recording so that the server VAD receives the actual leading silence. Player initialization does not wait for autoplay permission; the application resumes audio in response to a user gesture. Only the ESM entry used by this application is patched; the package is BSD-2-Clause.

The player patch keeps its worklet alive across underruns, flushes the final partial block on a server boundary, and reports only valid samples actually rendered into the Web Audio graph. The transport serializes message deserialization to preserve audio and boundary ordering. This is not a physical speaker playback measurement.

Consumption reports are aggregated in 768-sample batches (32 ms at 24 kHz), with remainders reported at boundaries, epoch changes and interruption. Worklet telemetry exposes current and peak queued samples, underrun episodes, discarded and consumed samples, and overflow count for each worklet lifetime; it does not retain audio or text. The output queue is limited to 240,000 samples (10 seconds at 24 kHz). Overflow discards the queued audio and stops the current turn without a completion receipt, rather than silently skipping speech; a later turn can create a fresh worklet.
