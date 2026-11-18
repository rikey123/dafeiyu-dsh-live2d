# 大肥鱼：实际架构

研究文档作为需求与候选技术参考，不将论坛性能、示例接口或命令直接当作工程事实。当前选择 DeepSeek 对话、本地语音、用户提供的 DeepSeek-chan Live2D 角色，并直接使用成熟语音编排框架。

| 模块 | 实际复用 | 应用适配 |
| --- | --- | --- |
| 语音主链 | Pipecat 1.15.0；Silero VAD；Local Smart Turn v3.2；RTVI / protobuf WebSocket | 本地语音服务接入、中文窄附和策略、设置与历史 |
| 浏览器音频 | 官方 Pipecat client-js 1.16.0、websocket-transport 1.8.2、官方录放音 AudioWorklet | 显式开麦、设备释放、音量/降音量、实际PCM声学分析 |
| Live2D | PixiJS、pixi-live2d-display、AIRI 色彩渲染补丁、MAGIC和元音driver、wLipSync 1.3.1 MFCC/WASM | 实际角色口型参数映射、声线模板、舞台和表情 |
| ASR | sherpa-onnx SenseVoice；OpenVINO Whisper / faster-whisper 后备 | 设备选择、质量门槛、HTTP、持锁和限流 |
| TTS | sherpa-onnx 中文 VITS；Windows SAPI 后备 | 原生callback增量PCM、HTTP连接复用、有界准入、声线选择、取消持锁 |
| LLM | Pipecat DeepSeekLLMService；自定义兼容地址用 OpenAILLMService；可选 OpenVINO Qwen3 量化服务 | 地址/模型/密钥设置、上下文 |
| 存储与界面 | SQLite、FastAPI、React、Vite | 会话、手动记忆、诊断、本机启停 |

`server/pipecat_voice.py` 构建真实框架管线。浏览器持续传 16kHz PCM16 单声道，服务端 VAD 和 Smart Turn 处理轮次；本地识别最终文字后，用户上下文交给框架 LLM 服务；框架将增量文字聚合后调用本地 TTS，并以 24kHz PCM 发送官方播放器。Live2D 嘴部从播放器 post-gain PCM 经wLipSync频谱元音分类和AIRI平滑生成，独立analyser仅作诊断/加载失败回退。初始化和模板切换不自动申请麦克风。

机器人说话时检出人声先降音量。最终转写是有限中文附和时使用框架原生 UserBackchannelFrame；新发言启动框架轮次与取消。停止按钮先调用官方播放器停播，再发送 RTVI `voice.stop`，服务端调用 `interrupt_bot()`。音频队列、协议和取消传播由库负责，旧自研 Conversation/WAV 调度退出生产语音入口。

`.venv-voice` 运行 8765 网关与 Pipecat；`.venv` 运行 8766 语音和可选 8767 LLM。分离环境避免硬件推理运行时与框架依赖冲突。`setup.ps1` 安装各自锁文件，`scripts/run.py` 用对应 Python 启动，仅关闭自己管理的子进程。

当前 SenseVoice 是最终片段ASR；可选在线Zipformer提供部分文字与token时间，稳定明确语义可早打断，owner模式禁用该通路。VITS按句合成；可选ZipVoice参考音色仍是完整文本输入。PCM传输不等于持续文本输入。框架官方播放器worklet按真实有效样本回报消费，在整TTS context完成且无取消/错误时才保存助手历史；LLM使用已确认上下文快照。迟ACK保留原顺序，空早打断不会自行重生成。逐句已听位置、硬误打断后的原音续播、同步设备原生AEC与真人交互仍待验收。

本轮完整实施表见 [VOICE_COMPLETION.md](VOICE_COMPLETION.md)。新增口型源码修复、角色映射与二进制模板、播放活动表情队列、有界阶段指标、可重复中文语料与物理双工采集工具。NPU状态继续独立如实显示，CPU成果不作为NPU成果。

原始音频默认不持久化。文字、手动记忆和配置保存在忽略的 `data/`。云 LLM 接收转写与上下文，本地 ASR/TTS 不代表云端看不到文字。密钥不回传前端，监听地址默认为回环。

本机为 Core Ultra 5 225H / 32GB / Arc 130T / Intel AI Boost。NPU Whisper 虽可编译，但未通过中文质量检查，实际默认 CPU SenseVoice/VITS；不将设备枚举或编译成功称为 NPU 可用。

46 仓库固定源码清单见 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)，逐项目审查见 [OPEN_SOURCE_LANGUAGE_REVIEW.md](OPEN_SOURCE_LANGUAGE_REVIEW.md)。AIRI MAGIC/渲染补丁固定于 `759fff0e646364fe3ad78c64a12f5f9739877e7a`，本轮元音driver/profile固定于 `11b8989f6dd7f840cf6b15ce59e367656fb11ac6`，见 [AVATAR_OPEN_SOURCE.md](AVATAR_OPEN_SOURCE.md)。角色及 Cubism Core 独立授权，见 [DEEPSEEK_SKIN.md](DEEPSEEK_SKIN.md) 和 `web/LIVE2D-LICENSE.md`。
