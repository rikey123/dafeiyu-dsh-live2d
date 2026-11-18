# 已退役的自研语音管线验收

这些脚本仅保留替换前 JSON/WAV/epoch/播放回执管线的测试方法，作为 `docs/VOICE_AUDIT.md` 历史结果的来源。它们不适配当前 Pipecat RTVI/protobuf 协议，移动后也不保证可运行。不要对当前生产应用执行或引用它们来宣称当前性能。

新端到端验收使用 `scripts/serve_voice_acceptance.py` 和 `scripts/check_pipecat_voice.cjs`。纯 Live2D 待机验证仍使用 `scripts/check_idle.cjs`。
