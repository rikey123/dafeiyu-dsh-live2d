# Development progress

## 2026-11-06 exhaustive gap closure (active)

The current implementation ledger is [VOICE_COMPLETION.md](VOICE_COMPLETION.md), generated from JSON with coverage checks for all46 repositories,99 capability rows and59 additional audit findings. [VOICE_TASKS.csv](VOICE_TASKS.csv) contains the23 grouped implementation/acceptance tasks; every original capability remains individually traceable. Earlier sections below are historical checkpoints.

Integrated actual online Zipformer CPU previews, stricter preview lifetime/owner isolation, ordinary HTTP Silero quality filtering, official-worklet sample consumption receipts, bounded playback telemetry and overflow termination, source-rebuilt twelve-coefficient MFCC, recalibrated binary profiles, model-specific mouth mapping, expression activity queues, and optional maintained sherpa ZipVoice/Kokoro backends. Browser verification found and repaired both cancel→next-turn silence and production CSP failure of the single-file wLipSync import/inlined profile.

Measured artifacts and exact limits are in [VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json), [VOICE_CORPUS_MATCHED_2026-11-06.json](VOICE_CORPUS_MATCHED_2026-11-06.json) and [VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json). Native per-TTS-context confirmation now preserves a contiguous played prefix in one ordered assistant record, with bounded epochs and context; real2/6-context replies and interruption after2 confirmed contexts passed. Explicit HTTP context closure removed the native3-second idle delay between segments. Three post-handshake disconnect/reconnect/manual-mic cycles and recorder-start fault/retry passed with old contexts/tracks released. User-triggered continuation creates a new turn; it does not revive cancelled audio.

The CSP-corrected whole-context baseline completed30 minutes/225 turns; the segmented version separately completed1807.417 seconds/206 turns (177 full/29 cancelled), no overflow or growing live contexts, without requesting a microphone. See [VOICE_SOAK_2026-11-06.json](VOICE_SOAK_2026-11-06.json). Qwen Chinese word alignment and MFA IPA phoneme alignment actually ran on CPU; cached MFA runs still take about32 seconds for1.65 seconds of audio, so only an optional offline path is appropriate. The trusted same-WAV fixture passed actual Edge sample-clock/i-mouth/mute/stop checks. CosyVoice2 true generator text input actually produced audio but CPU first PCM12.45s/RTF6.19 failed realtime; unproven generator cancellation keeps it out of the production bridge. CPU output, synthetic voice identity, browser consumption and physical listening are different gates; no completion is inferred from a model download or interface probe.

## Goal
Local-first Chinese portrait Live2D companion with streaming model responses, real offline speech adapters, interrupt cancellation, playback-synchronized mouth movement, conversation storage, settings and diagnostics.

## Worktrees
- main: integration, setup, verification and release
- feat/frontend: web UI, audio capture/playback, Live2D stage
- feat/backend: conversation gateway, cancellation, storage and provider streaming
- feat/speech: Intel OpenVINO ASR, offline TTS, model preparation

## Acceptance targets (not measured results)
First audible response P50 1–2 seconds; sustained interruption stops old playback; no stale audio on resumed turns; 30-minute real microphone session; portrait and landscape rendering. Physical microphone/speaker testing and provider credentials are separate gates.

## Completed
- Initialized empty workspace; read research as reference, confirmed Intel Core Ultra 5 225H / Arc 130T / AI Boost / 32GB.
- `feat/frontend`: be4cdd0 Live2D/Silero interface; d453cc8 manual memories and dependency updates. Merged.
- `feat/backend`: 8b5b10c gateway/storage/cancellation; 12bd97a optional offline LLM; ac1eb8b CPU/GPU benchmark. Merged.
- `feat/speech`: e7f27ce real local voice + NPU quality gate; 8b960db SenseVoice optimization. Merged.
- Main integration: launch/stop management, model preparation, context bounds, dependency locks, real-service and browser verification.
- Real local 20-turn runs: CPU first-WAV P50 1.646s / GPU 1.108s. NPU Whisper failed Chinese quality gate; use verified CPU speech.
- User selected DeepSeek official API / deepseek-chat as primary. URL and model prefilled; API key remains user-entered in application settings. Offline model retained as optional backup.
- DeepSeek-chan user-provided Live2D archive is excluded from Git; local import and license guidance are available in `scripts/import_avatar.py` and `docs/DEEPSEEK_SKIN.md`. Setup uses the imported model and downloads Cubism Core separately.
- Latest backend/speech/local-model regression: 12 passed, 1 skipped (the optional real local LLM test); TestClient emitted a deprecation warning.
- DeepSeek-chan renderer and portrait fit integrated. Real model browser QA passed with five textures, manual eye expression comparison, controlled WAV mouth peak 0.853 and return to zero on interruption, desktop/portrait/mobile screenshots, and fullscreen exit by button or Escape. That initial nose workaround was superseded by the AIRI rendering patch described below.

- Reused AIRI fixed revision 759fff0e's actual Cubism4 multiply/screen color patch, restoring the original nose without hiding Part46. Installation applies the patch reproducibly with patch-package.
- Vendored AIRI MAGIC generation/filter/crossfade modules and idle/speaking profiles under MIT; the React adapter drives head/body only. Settings expose natural motion and respect the initial reduced-motion preference.
- Main clean dependency installation, 24 frontend/upstream/adapter tests, production build and real browser avatar regression passed. Actual motion, original nose, WAV lip sync, interrupt clearing and mobile/fullscreen were checked. Open-LLM-VTuber was source-reviewed but its app/frontend code was not copied; Pipecat/HF speech-to-speech remain unintegrated.

- Corrected DeepSeek-chan idle adaptation: write model-specific Angle/Position physics inputs instead of standard outputs overwritten by physics. Restore pre-physics scheduling, SDK blinking, AIRI model offsets, default strength 0.6 with a slider and smooth disable.
- Continuous silent 20-second browser verification now checks actual final head/body angles and clothing geometry in every five-second interval, rather than only an early head parameter change. Body-X range was 7.6–10.5 degrees across the four windows; blinking and breathing occurred and idle mouth stayed closed. Frontend regression now has 26 passing tests.

## Current review gate
At that earlier checkpoint, primary cloud conversation still required the user's DeepSeek key (`api_key_set=false`). The later2026-11-06 integration below detected a configured key and passed one real cloud turn. Physical microphone/speaker, echo and30-minute human conversation remain acceptance items. See VALIDATION.md for exact coverage. Worktrees are retained for continued development and review.

## Voice audit and reliability fixes (2026-11-05)

Three existing feature worktrees audited frontend, gateway and speech concurrently. Integrated cancellation-aware bounded inference admission, playback acknowledgement backpressure, playback failure termination, error/history consistency, overlapping-session protection, microphone lifecycle cleanup, VAD uninitialized-destroy patch and hard sentence-size bounds. Final regression: 32 frontend tests; 20 Python passed / 1 optional skipped; production build passed.

Real Silero virtual-microphone browser checks passed permission retry, sustained interruption, stale audio rejection, next utterance and disconnect/restart. Real local ASR/TTS with a controlled SSE model and temporary storage passed cancellation/history recovery, but the next short reply still waited about 3.55s while a cancelled native TTS segment finished. A Chinese backchannel lasting approximately 0.8 seconds triggered interruption. These are confirmed gaps, not finished natural turn taking. HF speech-to-speech, Pipecat and LiveKit remain reference-only. See VOICE_AUDIT.md for exact pinned sources, measurements and next gates.


## Mature voice-core replacement (2026-11-05)

Downloaded 44 full pinned upstream source archives with SHA256 (docs/UPSTREAM_SOURCES.json). Replaced production custom Conversation and browser audio scheduler with installed Pipecat 1.15.0, official JS client/PCM worklets/protobuf transport, Silero VAD and Local Smart Turn v3.2. DeepSeek uses native framework service; local ASR/TTS remain isolated HTTP adapters. Chinese overlap acknowledgements use native UserBackchannelFrame. /ws/chat is retired; old audit scripts are under scripts/legacy, and old browser audio/epoch/VAD code and dependency were removed.

Used existing frontend/backend/speech worktrees for parallel implementation, then cherry-picked reviewed commits into main. Fixed real Edge capture graph starvation with a zero-gain sink, preserved leading silence in the official worklet, requested browser audio-processing constraints, restored cancellable reconnection and approximate output-text expressions. Official-browser/local-speech test passed short acknowledgement, real interruption, next reply, manual stop, actual mouth motion, permission retry and mic-safe reconnection. Ten official-protocol turns completed with real local audio and 10/10 history pairs. No claim of physical AEC, NPU success, cloud latency, exact heard-history, or human long-session acceptance. See VOICE_OPEN_SOURCE.md and current VALIDATION.md.

Normal-browser acceptance additionally found and fixed an autoplay handshake deadlock: official player initialization no longer waits for a gesture before client-ready; send/mic actions resume output. Final frontend regression: 26 tests; primary missing-key UI clears busy state.

## Audio engineering and owner voice gate (2026-11-06)

Used the existing three worktrees for parallel frontend/backend/speech work. Integrated scoped commits for post-gain 1024-sample mouth analysis and time smoothing; actual browser mic settings; official-recorder enrollment and WAV normalization; gateway owner settings/proxies; CPU sherpa ERes2Net/Silero enrollment/verification; and strict fail-closed Pipecat STT gating. Integration found and corrected capability/filter status confusion and the adapter initially failing to forward owner_only. Registered samples stay in memory; only normalized embeddings persist, and deletion disables filtering/reconnects without reopening the microphone.

Real isolated acceptance used temporary settings/profile, local ASR/TTS/embedding and another SAPI voice: cross-text same synthetic voice accepted (0.9097), another rejected (0.1199), noise/silence/short uncertain; rejected audio neither interrupted bot nor started LLM/history, and next accepted voice worked. Actual Edge recordings enrolled successfully through the UI; toggles/deletion and track release passed. Playback/mouth checks passed, as did the official voice interruption/backchannel regression and primary missing-key error recovery. Frontend30; gateway/Pipecat20; speech/model10 passed/1 optional skipped. Main services restarted, owner model ready but user not enrolled.

Reviewed HF WASAPI/AEC3, EdgeVoiceAssistant duplex APM and Evatar speaker-store mechanisms. LiveKit Windows offline APM experiment is retained separately; double-talk near preservation is insufficient to enable it in production. Physical echo and real-human recognition remain unmeasured. Fixed sources, model hash, setup commands and limits are in AUDIO_ENGINEERING.md and VALIDATION.md.

## Language-aware mouth and incremental output (2026-11-06)

The second-stage mouth requirement is now implemented. The fixed AIRI wLipSync vowel driver/profile and MIT `wlipsync@1.3.1` AudioWorklet analyze the actual post-gain player signal and produce AEIOU weights with silence gating and time smoothing. The DeepSeek model's real parameter bounds are read at runtime; `ParamMouthOpenY`, form, pucker, funnel and widen are written only when exposed by the moc. The old RMS window remains only as a diagnostic fallback. Edge acceptance loaded the wLipSync chunk, observed nonzero form/funnel changes, and passed mute, resume and stop checks.

The local VITS callback now has a bounded incremental PCM endpoint and Pipecat preference path, with WAV fallback for unsupported engines. Native metrics are enabled. This reduces time to first generated PCM in local measurements, while documentation keeps it separate from continuous acoustic streaming and physical speaker latency. The final review covers46 repositories, including official MotionSync and wLipSync, with107 validated fixed-commit source citations in OPEN_SOURCE_LANGUAGE_REVIEW.md and its tracked JSON.

Integrated frontend5b47f8f, backendb7faf2a and speech9c515b4 from their owned feature worktrees. Production mouth mapping now checks real moc parameter IDs and bounds, initializes WASM without blocking handshake, follows the current session after reconnect, and shows fallback status. Integration added a local VITS voice-specific template collected through upstream unmodified WASM MFCC exports; an independent five-vowel/equal-RMS official-player test demonstrates spectral mouth shapes and actual U pucker. E/O/U confusion remains; this is not phoneme alignment. Profile selection/reconnect and blocked-WASM fallback passed normal Edge autoplay without acquiring a microphone.

Final unit suites: frontend32; gateway/Pipecat29; local speech10. Production build passes with known large-bundle warnings. Streaming failure/cancel tests prevent full-WAV replay after bad HTTP or partial PCM and retain native locks to actual exit. Real browser backchannel/barge-in/next turn/stop/tracks/reconnect passed;1.914s synthetic interruption input reached framework interruption at2.811s, not physical stop latency. CPU HTTP benchmark3 samples each: short/long firstPCM medians0.124/0.125s vs completeWAV0.305/1.322s. Physical AEC, real-human speaker accuracy, fine phoneme timing, playback ACK and qualified NPU inference remain open.

The primary settings now report a configured DeepSeek key. A single real deepseek-chat text turn returned a short greeting and passed actual local CPU TTS/player/Cubism/persistence with no microphone or page errors; click-to-first-mouth was2.514s, not a speaker measurement or distribution. No secrets were printed, and only the QA session was deleted. See scripts/check_deepseek_live.cjs and artifacts/deepseek-live/.

## Current voice gap review (2026-11-06, code baseline5c5ce43)

Revisited the relevant voice implementation/documentation in all46 pinned archives with the three existing scoped worktrees. The current review records99 capabilities and120 source/document citations, separating25 absent,31 partial,22 already present,14 different-purpose and7 unverified capabilities. These are descriptive counts, not quality scores. Coverage was re-extracted from the research URLs and named/direct dependencies; no missing or duplicate repositories.

New details include CosyVoice2/3 generator text input (not its vLLM path), HF timed visemes with an English default and0.5s buffering, HF streaming diarization distinct from owner verification, LiveKit output-dependent pause/resume/playout position, and Open-LLM-VTuber Web completion ACK with whole-task text granularity. Existing cancellation, callback PCM, Smart Turn, browser AEC requests, backoff and spectral mouth processing are not reclassified as missing.

Found an upstream dependency defect: six-class wlipsync1.3.1 execute updates only six exported MFCC slots, whereas scoring reads twelve. Confirmed with isolated WASM sentinel memory via scripts/probe_wlipsync_mfcc.cjs; production memory was untouched. This remains unresolved and does not prove the sole cause of vowel confusion. Current findings and prioritized gaps are in CURRENT_VOICE_GAPS.md/.json and WLIPSYNC_MFCC_PROBE.json. This round changed review documents and diagnostic/render scripts only; no new product capability or performance test was claimed.
