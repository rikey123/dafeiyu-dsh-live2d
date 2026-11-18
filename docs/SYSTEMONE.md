# System One interaction decisions: Ark / TokenToSea

Optional `systemone_enabled` adds an independent decision provider to the existing ASR → DeepSeek → selected TTS pipeline. It classifies behavior; it never generates the reply or substitutes a speech model. Default is **off**. GPU, CPU, auto and API TTS remain independently selectable. `moss_live` cannot be combined: that service owns its turn/interruption lifecycle. Pipeline conversation mode still suppresses input during playback; choose duplex for spoken interruption.

## Configuration

Settings → 智能交互判断 · System One:

- `systemone_provider`: `ark` (fresh-install default) or `tokentosea`. Existing installations with a TokenToSea credential and no provider field retain TokenToSea until explicitly changed. There is **no automatic cross-provider fallback**.
- Ark: `systemone_ark_api_key`, initialized from `ARK_API_KEY`; GET exposes only `systemone_ark_api_key_set`; `clear_systemone_ark_api_key` explicitly clears it. `systemone_ark_model` defaults to `doubao-seed-2-1-lite-260915` and also accepts a console-created `ep-...` inference endpoint bound to that model. Open the model and grant the appropriate key/endpoint permissions in the Ark console first.
- TokenToSea: legacy `systemone_api_key`, initialized from `TOKENTOSEA_API_KEY`; GET exposes only `systemone_api_key_set`; `clear_systemone_api_key` explicitly clears it. These credentials are never reused for Ark or DeepSeek.
- Both credentials stay in ignored local SQLite. Empty updates preserve them. Enabling or switching while enabled requires the selected provider's key. Clearing the active key requires disabling the feature; clearing an inactive provider's key is allowed. URLs are fixed, not user-configurable credential destinations.
- `systemone_audio_enabled`: default true, effective only when feature enabled. Sends at most four seconds of mono16k PCM16 as embedded WAV along with bounded recent dialogue. Text-only mode omits all audio. No camera, screen, image or video capture is added.
- `systemone_timeout_ms`: 200–5000, default1200. A total request/recovery budget, **not a measured response time**.
- `systemone_interrupt_threshold`: .5–.99, default .75. Noul probability for meaningful interruption or backchannel decisions.
- `systemone_confidence`: .5–.99, default .6. Visual choices require both choice probability and confidence; energy requires confidence. Defaults are uncalibrated.

Saving relevant settings closes existing voice sessions. Reconnection leaves the microphone off. Enable only after providing a key; configuration/status reads never make a paid request. `POST /api/systemone/test` explicitly sends one fixed text example using saved credentials, returning sanitized reason, elapsed time and validated behavior. This tests the text API, not microphone quality, audio-modality acceptance or conversational latency.

## Turn control

Pipecat Silero VAD, Smart Turn stopping and local ASR remain active. While bot speech overlaps a live utterance, the decision processor can ask the selected provider on bounded audio snapshots after roughly .65s and1.8s of received audio, at most twice per utterance and one active early request. These are capture thresholds, not end-to-end timing promises. Stable ASR previews, when independently enabled, can instead provide text. Requests never fabricate an ASR transcript.

A high interruption probability with low backchannel probability emits a guarded system frame into the existing Chinese turn-start strategy, using Pipecat's native interruption/cancellation. VAD stop, a new utterance, bot stop and manual interruption invalidate pending early results. Late results cannot interrupt another utterance. Final ASR can classify once more; confidently classified overlap acknowledgements are filtered before history/LLM. Unknown decisions retain the existing rule policy. A successful early interruption is not later reversed by a final acknowledgement classification.

Non-overlapping final speech is forwarded immediately; its affect decision runs alongside DeepSeek. Only an overlapping final utterance needing backchannel classification waits for the bounded decision. New user input cancels/invalidate older input decisions.

Owner-only disables early uploads and early model interruption. Only successfully verified final STT output can carry bounded audio to the decision layer. Audio is removed from frame metadata before downstream delivery; no audio is persisted by this component. Remote calls may already have incurred a charge when locally cancelled; closing HTTP is not a provider cancellation guarantee.

## Assistant initiative (experimental, opt-in)

Settings → **允许助手主动接话** is a separate policy from detecting the user interrupting the assistant. It uses the currently selected provider (including Ark), not a new Jev endpoint or a replacement for DeepSeek. DeepSeek still writes the short contribution; the selected TTS still speaks it. No camera/video or idle autonomous prompt loop is added.

While a user speaks and the assistant is idle, the processor can reuse a recent valid online ASR preview or request a bounded snapshot from the existing local recognizer. This works without installing an online ASR model. Recognition runs asynchronously, by default at most3 probes/continuous utterance and at least3s of new audio between probes; these limits are configurable below. Only the most recent4s are retained. Local snapshot recognition has a2s budget. Normal final recognition is independent and is never replaced by a partial result.

The separate `speak_now`, `must_wait`, `intent` questions assess the value of speaking now versus listening, respect for the user's floor, and a confident purpose (acknowledge/empathize/clarify/correct; normally wait). Desire must reach `.9` by default and must-wait must be <=`.2`. These are uncalibrated estimates, **not a measure of consciousness or actual internal desire**. Explicit requests such as “先听我说完” suppress the current utterance locally as well. Recognizer/provider failure does not trigger a keyword fallback.

There is at most one accepted contribution per utterance, a default20s connection cooldown, and no contribution while an ordinary reply is generating or pending audio remains. New utterance, stop, text input and disconnect invalidate pending decisions, checked again when the queued prompt reaches the LLM. Slow speculative generation is cancelled if the user finishes before playback starts. Full final text follows the normal turn lifecycle and may cancel an earlier interjection before generating the full answer. The input audio is not muted or cut and the partial text is never persisted as a fabricated user turn.

Capture starts ineligible. Browser `voice.capture` lifecycle messages enable eligibility only after successful microphone start; turning capture off immediately invalidates pending judgments and speculative replies. Outdated async microphone starts cannot enable this after a newer off action. Snapshot cancellation closes the local HTTP request, but a native ASR already running can retain its bounded inference slot until completion; no claim of instantly preempting native inference is made.

The short contribution uses a transient isolated context after confirmed-history reconstruction. Its instruction and pre-TTS stream limiter use the same configured maximum length (default48 Unicode code points, including punctuation). Both still require one sentence. The regular reply stream is not truncated. Visual behavior and assistant persistence retain the same playback-bound controls.

### Initiative settings

Settings → 智能交互判断 · System One → 主动接话参数. Primary fields remain visible/editable with the feature off; the last three fields are under 主动接话高级参数. Values are saved on the normal 保存设置 action, not while typing. Invalid or blank numeric inputs block saving, including collapsed advanced fields. The API also enforces finite values, bounds, and integer types for counts/time/length.

| Setting | Default | Accepted range | Effect |
| --- | --- | --- | --- |
| `systemone_initiative_threshold` | .9 | .8–.99 | Minimum speak-now desire; higher is more conservative |
| `systemone_initiative_min_speech_ms` | 3000 | 1500–15000 integer ms | First probe after this much received speech |
| `systemone_initiative_cooldown_s` | 20 | 10–120 integer s | Minimum interval between accepted contributions in a connection |
| `systemone_initiative_max_reply_chars` | 48 | 8–80 integer characters | One-sentence prompt and stream limit; includes punctuation |
| `systemone_initiative_wait_threshold` | .2 | 0–.5 | Suppress when must-wait is above this; lower protects the user's floor more |
| `systemone_initiative_probe_interval_ms` | 3000 | 1500–10000 integer ms | Newly received audio before another probe; no concurrent probes |
| `systemone_initiative_max_probes` | 3 | 1–6 integer | Probe budget per continuous VAD utterance; not a reply count |

恢复主动接话默认参数 resets only these numeric drafts, never the enable switch, credentials or other settings; save to apply. Each actual change closes old voice sessions so the next connection uses a consistent configuration, with the microphone off. Re-saving unchanged values does not itself close existing sessions. Existing databases merge the new defaults without overwriting old preferences. One contribution/utterance, explicit requests to finish, 4s bounded audio/expiry and no-busy-assistant protections are fixed safety boundaries, not tunable switches. More probes/shorter intervals can increase local load and paid cloud usage; probabilities remain uncalibrated.

Configuration acceptance on2026-11-14:322 backend/speech tests passed (1 skipped),125 frontend tests passed, production build passed. Edge fixture acceptance passed6 cases, including empty/out-of-range/fractional count rejection before PUT, default reset, all7 non-default values saved/reloaded, and the configured24-character instruction reaching the fixture LLM. Production browser read-only verification found all7 fields, zero microphone requests and no page errors; saved preferences were unchanged. No new paid model calls or real acoustic tests were made. Reports/screenshots: `E:/Dafeiyu/verification/systemone-initiative-settings/`.

New defaults: `systemone_initiative_enabled=false`, `systemone_initiative_threshold=.9`, `systemone_initiative_min_speech_ms=3000`, `systemone_initiative_cooldown_s=20`. Requires System One on, duplex, owner-only off; otherwise inactive even if the preference is retained. No microphone is started automatically. Saving reconnects voice with microphone off. Cloud judgments and short DeepSeek/TTS contributions can add usage; local cancellation doesn't guarantee provider refunds. Capture intervals/budgets are not measured end-to-end latency. A diagnostic `voice.initiative` event shows waiting/accepted/unavailable and uncalibrated desire; acceptance doesn't assert that audio actually played.

## Emotion / expression / gesture

TTS's announced sentence starts an independent decision task. The request asks for emotion (neutral/happy/sad/surprised), one existing expression, one existing gesture and an ordinal energy score. It includes at most four recent dialogue messages, each capped600 characters, plus the sentence capped2000 characters. User affect from a confident current input decision is context, not a medical or personality inference.

The result is sent as `voice.behavior` tagged with the TTS context epoch. Synthesis/playback do not wait for it. The browser holds early results until that epoch consumes PCM; a result arriving during the current epoch can update it. Completed, interrupted and retired epochs reject late changes. Unknown names, nonfinite/range-invalid controls and arbitrary parameter writes are rejected. Requests are capped at8 per response, with at most2 concurrent outgoing decisions. Overload and late results leave existing visuals in place.

Manual face overrides model expression. Manual hand poses override model gestures; disabling reactive poses disables automatic gestures. Energy scales the user's natural-motion strength, bounded to1; disabling natural motion still takes precedence. Existing profiles remain idle/speaking; the model adjusts intensity and existing gestures, not new generated motion animations. Lipsync remains independent and is written last. No TTS emotional-style API is introduced.

## Transport / degradation / observability

- **Ark (Beta)**: POST `https://ark.cn-beijing.volces.com/api/v1/systemone`, Bearer key, **`ark-beta-systemone-api: true`**. This is not an `Ark-Beta` header. Text-only requests use a JSON `state`; audio requests use `state: [{type:'text',text:context},{type:'audio',audio_url:'data:audio/wav;base64,...'}]`. Do not send TokenToSea's top-level `audio`, or undocumented `input_audio`, `return_probabilities` or streaming options. Responses use `answers.*.noul`, `.choice`, `.score`, `.confidence`, `.probabilities`, not a generic `value` field. Exactly one synchronous POST; no automatic retry or invented Ark results endpoint. Closing HTTP does not prove remote inference stopped.
- **TokenToSea**: POST `https://api.tokentosea.com/v1/systemone`, fixed model `clef-omni`. A new logical request gets one UUID `Idempotency-Key` and one POST. Pending/409 or transport uncertainty may recover via GET `/v1/results/{same-key}` within the same deadline. No automatic second POST or resubmission after timeout. Completed envelopes use `output`.
- Both use strict common Noul/Choice/Score validation: exact question IDs, allowed choices, finite probabilities, complete probability tables summing approximately to one, maximum-probability choice, and score consistent with its expected-value distribution. Ark endpoint responses may identify the configured endpoint or the supported underlying model; unrelated models are rejected.

Responses are bounded64KiB and strictly validated; redirects are disabled. At most4 requests in flight across this gateway process, with immediate fallback rather than an unbounded queue. Three consecutive failures open a per-session15s circuit. Timeouts, protocol errors, auth failures, overload and low visual confidence fall back to rules. Manual stop and mouth reset never depend on cloud availability. Provider bodies and credentials are not returned in errors.

Errors distinguish `region_restricted`, `permission_denied`, `authentication`, endpoint/model errors and rate limits. Concurrent tasks have task-local reason codes, avoiding attribution to another request. `voice.behavior.source` is `doubao-systemone`, `clef-omni`, or `rules`, with the requested `model` included. The browser preserves actual source with each playback-bound decision; an unsaved settings change cannot relabel old audio. The test button requires saving provider/model/key changes and reports the tested provider, not the draft selection.

## Probability evaluation (explicit opt-in)

`scripts/evaluate_systemone.py` is a dry run by default and does not send any cloud requests. Its bundled eight labelled text examples are a smoke set, **not a calibrated benchmark or real acoustic evidence**. Review and replace labels with representative held-out data (backchannels, corrections, echo/noise, short utterances, different voices) before choosing thresholds.

```powershell
# Validate examples only; zero cloud requests.
.venv-voice/Scripts/python.exe scripts/evaluate_systemone.py
# Explicitly authorize up to one billable request per example, with saved settings.
.venv-voice/Scripts/python.exe scripts/evaluate_systemone.py --execute-paid-requests --output E:/Dafeiyu/verification/systemone-ark/calibration.json
```

A custom `--dataset` is a JSON array (1–100 examples) of `{id,text,overlap,labels:{interrupt:boolean,backchannel:boolean}}`. Optional `audio_wav` references a <=4-second 16kHz mono PCM16 WAV relative to the dataset; requires `--allow-audio-upload` and saved audio judgments enabled. No microphone is activated. No user history or audio is written into the output report. The script does not overwrite an existing report or tune thresholds automatically.

Report includes Brier score, positive-probability ECE/reliability bins, classification accuracy, joint-policy false/missed interruption rates, per-request reasons/latency and successful coverage. Failed/unattempted examples remain visible in coverage, not silently counted as correct. ECE depends on binning and can hide mistakes; examine Brier, bin counts and actual error cases together. No-data metrics are null, not zero. Account/config errors abort the remaining batch. No speculative resubmissions.

`/api/voice/metrics/{session}` includes `systemone_requests`, `systemone_success`, `systemone_fallback` and `systemone.processing` sample counts/P50/P95. These are gateway request metrics, not physical speaker or user reaction measurements. The settings panel reports the latest output-decision result and explicit connectivity test.

## Verification boundary

Assistant-initiative update,2026-11-14: `pytest tests speech/test_pipecat_services.py speech/test_streaming_asr.py speech/test_quality.py speech/test_api_tts.py` reports311 passed/1 skipped. Frontend123 tests pass and production build succeeds. `scripts/check_systemone_initiative.cjs` passes5 real-Edge/Pipecat fixture cases (settings opt-in, strong desire→short generation→tone playback receipt, complete final transcript preserved, low desire→listen, stopped utterance→no late reply). The existing System One browser regression passes5 more cases. These use synthetic VAD frames, snapshot ASR text, supplier decisions, LLM and tone PCM, never the microphone. The initiative fixture allows tone autoplay because it deliberately bypasses the microphone gesture that normally resumes output; it is not a real acoustic test.

A single new **real saved-Ark text-only** initiative decision was attempted: total1203ms, `timeout` under the saved1200ms budget. It uploaded a fixed example, no microphone audio or chat history. This is not evidence of successful live initiative or calibrated probabilities; on-device settings/fixtures do not remove that verification gap. Reports/screenshots are under `E:/Dafeiyu/verification/systemone-initiative/`. The opt-in remains off in the primary saved configuration. Do not infer that the historical output-behavior success also validates user-floor timing or new initiative questions.

Browser validation also reproduced HTTPX selecting a Windows system proxy for loopback, with intermittent fixture connection/502 failures. The supervisor now adds loopback hosts to both NO_PROXY variants while preserving existing entries; local speech clients bypass environment proxies explicitly. Remote APIs retain proxy support. No system proxy setting is changed.

Automated tests cover both provider contracts, bounded audio, same-key TokenToSea recovery, Ark's no-retry policy, independent credentials/migration, fallback, guarded native interruption, owner policy and playback-aligned controls. Browser acceptance uses an explicitly labelled local protocol fixture; it does not establish live model quality or latency. On 2026-11-14, real Clef calls returned HTTP403 `model_not_supported_in_region`, including an explicit local-proxy test. Ark credentials were not available during this migration. Real Ark text/audio decisions and thresholds still require a configured account and microphone tests. HTTP401 without credentials proves neither model availability nor authorized inference.

References checked2026-11-14: https://docs.volcengine.com/docs/ark/system-one-api?lang=zh (official page last updated2026-11-11) ; https://docs.tokentosea.com/api/systemone/ ; https://docs.tokentosea.com/guides/system-one/ ; https://docs.tokentosea.com/api/results/ ; https://docs.tokentosea.com/guides/idempotency/ .
