# 46 个上游项目的语音系统复审

日期：2026-11-06。覆盖研究与直接依赖的44个仓库，并补充官方 MotionSync 与 wLipSync，共46个完整源码归档。固定提交和归档 SHA256 见 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)。下载不包含 Git 历史、LFS 权重或递归子模块；没有批量运行上游安装器。

当前实现的进一步逐能力差距审查与依赖风险见 [CURRENT_VOICE_GAPS.md](CURRENT_VOICE_GAPS.md)，其中重新区分已具备、部分、缺失、待验证和非同类能力。

以下是源码机制对照，不是全部项目在同机运行后的排名。“优势”表示该项目有值得借鉴的机制，可能已被当前系统采用；不表示整套项目一定更快。许可证指源码，模型、声音、角色素材、SDK Core 必须分别核查。原文仅 README 的项目明确标识，不能当作实现证据。完整结构化数据见 [OPEN_SOURCE_LANGUAGE_REVIEW.json](OPEN_SOURCE_LANGUAGE_REVIEW.json)。

## 已落实的改动

- 口型：wLipSync 1.3.1 原版 WASM 对实际 post-gain 播放 PCM 提取 MFCC 并分类；AIRI 元音 driver 提供胜出/次位、静音门和时间平滑；适配 DeepSeek 实际存在参数与边界。增加当前 CPU VITS 声线模板、通用样例选择、重连和停播清零。能做声学元音形状，尚不能做每字精确音素对齐。
- 本地合成：sherpa 原生 callback 提前输出 PCM，有界队列/准入、连接复用与原生锁生命周期；HTTP400/429/500/503和出音后中断不会误回放完整WAV，仅404/501回退。
- 编排：直接使用 Pipecat 和官方客户端/媒体传输，启用原生 TTFB/TTFA/processing metrics，保留 Smart Turn 与中文窄附和策略。
- 声纹：此前已采用 ERes2Net/Silero 与模板可靠性机制；当前本人声音过滤需用户先录入，不会凭空识别用户身份。

## 验证与仍有差距

真实浏览器官方 PCM 播放器→wLipSync→Cubism 的等响度五元音测试通过：RMS 均约2800，而嘴形范围明显不同；本地模板使 U 收唇出现，但 E/O/U 仍有混淆。训练是独立十二重复字的合成录音，验证使用另生成的六重复字录音；小样本不是通用中文发音准确率。具体重现和数据见 [VALIDATION.md](VALIDATION.md)。

短/长句各3次串行 CPU HTTP 基准：首PCM中位数0.124/0.125秒，完整WAV 0.305/1.322秒。流式先测、WAV后测，模型输出有随机变化；不是物理扬声器首音、DeepSeek端到端或NPU性能。

尚未完成：真实外放 AEC/噪声/旁人声误接收评测、字级对齐、在线ASR首字质量、播放确认后的精确已听历史、连续声学流式模型和NPU合格推理。Pipecat empty-user-turn恢复是提示模型重生成，当前无播放ACK，不能直接当原音续播启用。原生AEC实验不能替代正确ADC/DAC播放参考。

## 逐项目机制与移植决定

### akkoaya/EvatarFramework

源码：[63b414c9633d](https://github.com/akkoaya/EvatarFramework/tree/63b414c9633d55234949b3754686dcc7acebea60)；许可：Apache-2.0。

- 证据：[src/evatar_framework/core/events.py:92](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/core/events.py#L92) — 会话事件投影。
- 证据：[src/evatar_framework/core/session_control.py:14](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/core/session_control.py#L14) — 会话控制定义。
- 证据：[src/evatar_framework/core/config.py:22](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/core/config.py#L22) — 配置打断最短时长。
- 证据：[src/evatar_framework/providers/speaker/store.py:97](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/providers/speaker/store.py#L97) — 校验已存向量的维度、有限性和归一化。
- 证据：[src/evatar_framework/providers/speaker/store.py:131](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/providers/speaker/store.py#L131) — 对多条声纹向量归一化、取平均并持久化。
- 证据：[src/evatar_framework/providers/speaker/store.py:143](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/providers/speaker/store.py#L143) — 使用归一化向量进行相似度匹配。

值得借鉴：会话事件及投影保持统一事件结构；会话控制与会话遥测支持运行检查；可配置最短打断时长；校验声纹向量维度、有限性和归一化，避免损坏模板直接参与匹配；多条样本分别归一化并合并，减少对单条录音的依赖；归一化向量使用内积相似度匹配，并可检查索引维度和数量一致性。

当前差距或移植成本：会话运行时与 Pipecat 重复；本项目当前为单人模板，并非 Evatar 的多用户索引。

决定：已将多样本向量归一化、平均合并和相似度匹配思路移植到本地声纹；另有录音质量、模型版本与原子替换校验。保留 Pipecat，不替换整个项目

实际落地：已借鉴模板可靠性机制；未引入完整会话框架。

依赖：LiveKit 会话栈及所选 ASR、LLM、TTS 提供方。

### aryeo0908/whisper-loop

源码：[810e1d5d4105](https://github.com/aryeo0908/whisper-loop/tree/810e1d5d410557038d1379cd709e3fb979422bde)；许可：MIT。

- 证据：[server/app/metrics.py:23](https://github.com/aryeo0908/whisper-loop/blob/810e1d5d410557038d1379cd709e3fb979422bde/server/app/metrics.py#L23) — TurnTimer 记录各阶段时间。
- 证据：[server/app/pipeline.py:106](https://github.com/aryeo0908/whisper-loop/blob/810e1d5d410557038d1379cd709e3fb979422bde/server/app/pipeline.py#L106) — 插话时取消当前任务并通知客户端。

值得借鉴：每轮阶段计时及汇总；助手每轮使用可独立取消的 asyncio 任务；插话时告知客户端被打断的轮次。

当前差距或移植成本：当前产品尚无设备到扬声器的延迟测量。

决定：使用 Pipecat 原生指标，不移植计时器

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：WebSocket；模型和提供方依配置而异。

### Code-Amadeus/Amadeus

源码：[9ef43dda7cc2](https://github.com/Code-Amadeus/Amadeus/tree/9ef43dda7cc2ac177601889478116caabe562e88)；许可：AGPL-3.0。

- 证据：[asr/barge_in_detector.py:43](https://github.com/Code-Amadeus/Amadeus/blob/9ef43dda7cc2ac177601889478116caabe562e88/asr/barge_in_detector.py#L43) — 实现插话检测器。
- 证据：[asr/echo_guard.py:179](https://github.com/Code-Amadeus/Amadeus/blob/9ef43dda7cc2ac177601889478116caabe562e88/asr/echo_guard.py#L179) — 判断是否可能为自身回声。

值得借鉴：独立插话检测器结合音频和 VAD；回声防护判断可能的自身回声；ASR 抽象层分离不同引擎。

当前差距或移植成本：回声启发式需要验证，不能等同声学回声消除。

决定：不复制代码；许可审查后独立评估

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：VAD、ASR 和音频设备；模型依赖随配置变化。

### CoreWorxLab/local-livekit-plugins

源码：[598d56d5a234](https://github.com/CoreWorxLab/local-livekit-plugins/tree/598d56d5a234e81438cd293927d6917b3633c7fb)；许可：源码 MIT；模型单独核查。

- 证据：[src/local_livekit_plugins/piper_tts.py:55](https://github.com/CoreWorxLab/local-livekit-plugins/blob/598d56d5a234e81438cd293927d6917b3633c7fb/src/local_livekit_plugins/piper_tts.py#L55) — Piper chunked stream adapter。
- 证据：[src/local_livekit_plugins/faster_whisper_stt.py:50](https://github.com/CoreWorxLab/local-livekit-plugins/blob/598d56d5a234e81438cd293927d6917b3633c7fb/src/local_livekit_plugins/faster_whisper_stt.py#L50) — faster-whisper LiveKit STT adapter。

值得借鉴：LiveKit 标准语音服务封装，减少适配代码；Piper 分块输出和本地 Whisper 组合。

当前差距或移植成本：依赖 LiveKit 生命周期，与当前 Pipecat 架构不同；未验证本机 Windows 和中文模型。

决定：参考适配边界，保留 Pipecat

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：LiveKit agents, Piper, faster-whisper。

### datascale-ai/opentalking

源码：[8c739a5a6f11](https://github.com/datascale-ai/opentalking/tree/8c739a5a6f114daf71aeace832a668c3ad60f536)；许可：Apache-2.0。

- 证据：[apps/api/services/session_service.py:29](https://github.com/datascale-ai/opentalking/blob/8c739a5a6f114daf71aeace832a668c3ad60f536/apps/api/services/session_service.py#L29) — 将任务推送至 Redis。
- 证据：[apps/api/services/session_service.py:170](https://github.com/datascale-ai/opentalking/blob/8c739a5a6f114daf71aeace832a668c3ad60f536/apps/api/services/session_service.py#L170) — 读取及更新会话状态。
- 证据：[apps/api/services/session_service.py:255](https://github.com/datascale-ai/opentalking/blob/8c739a5a6f114daf71aeace832a668c3ad60f536/apps/api/services/session_service.py#L255) — 上传 PCM 播放前执行打断。

值得借鉴：使用 Redis 保存会话状态和工作队列；提供明确的会话打断与语音操作；协调实时数字人服务。

当前差距或移植成本：独立协议和运行时与现有技术栈重叠。

决定：保留 Pipecat 和 Live2D，暂不迁移

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：WebRTC 及可选模型服务。

### electron/electron

源码：[6d9ec3d7433a](https://github.com/electron/electron/tree/6d9ec3d7433a01587615a23881ed64ed94e1fa6d)；许可：MIT。

- 证据：[shell/browser/electron_permission_manager.cc:117](https://github.com/electron/electron/blob/6d9ec3d7433a01587615a23881ed64ed94e1fa6d/shell/browser/electron_permission_manager.cc#L117) — 设置权限请求处理器。
- 证据：[shell/browser/electron_permission_manager.cc:350](https://github.com/electron/electron/blob/6d9ec3d7433a01587615a23881ed64ed94e1fa6d/shell/browser/electron_permission_manager.cc#L350) — 按请求来源检查权限。

值得借鉴：桌面权限请求可由应用统一管理；可按来源检查权限，适合桌面安全策略。

当前差距或移植成本：当前网页依赖浏览器权限流程，未提供 Electron 桌面壳和其权限策略。。

决定：仅参考权限模型；当前浏览器产品不新增 Electron 运行时。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Electron/Chromium。

### FahadiF/Edge-Voice-Assistant

源码：[6ba8a2d7f715](https://github.com/FahadiF/Edge-Voice-Assistant/tree/6ba8a2d7f715e967ecc2f75539f553fb37198ee6)；许可：Apache-2.0。

- 证据：[src/eva/audio/processor.py:93](https://github.com/FahadiF/Edge-Voice-Assistant/blob/6ba8a2d7f715e967ecc2f75539f553fb37198ee6/src/eva/audio/processor.py#L93) — APM 处理采集与播放参考。
- 证据：[src/eva/asr/base.py:5](https://github.com/FahadiF/Edge-Voice-Assistant/blob/6ba8a2d7f715e967ecc2f75539f553fb37198ee6/src/eva/asr/base.py#L5) — 使用 epoch 丢弃过期解码结果。
- 证据：[src/eva/cli.py:1195](https://github.com/FahadiF/Edge-Voice-Assistant/blob/6ba8a2d7f715e967ecc2f75539f553fb37198ee6/src/eva/cli.py#L1195) — 提供真实设备回声测试命令。

值得借鉴：WebRTC APM 同时处理采集和播放参考；使用 epoch 拒绝过期 ASR 结果；专用回声测试可测量实际音频路径。

当前差距或移植成本：当前浏览器 WebSocket 后端缺少同步的实际播放参考。

决定：完成参考时序与双讲验证前不将 APM 接入生产

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：LiveKit RTC APM 及双向采集播放设备。

### FunAudioLLM/CosyVoice

源码：[074ca6dc9e80](https://github.com/FunAudioLLM/CosyVoice/tree/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc)；许可：源码 Apache-2.0；权重按具体模型卡。

- 证据：[cosyvoice/cli/cosyvoice.py:80](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L80) — SFT 流式合成。
- 证据：[cosyvoice/cli/cosyvoice.py:91](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L91) — 零样本与 stream 参数。
- 证据：[cosyvoice/cli/cosyvoice.py:105](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L105) — 跨语言提示音频。

值得借鉴：支持模型流式输出及语速参数；参考音频零样本音色、跨语言和指令控制；可缓存零样本说话人特征。

当前差距或移植成本：依赖较重的模型及运行时，本机 CPU/NPU 延迟未测；当前 VITS 为本地 CPU 回调分段，不提供零样本克隆。

决定：保留候选，需独立权重许可、硬件及中文语音基准

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch, CosyVoice 模型及前端依赖。

### FunAudioLLM/SenseVoice

源码：[586bbdb2b052](https://github.com/FunAudioLLM/SenseVoice/tree/586bbdb2b052f4fe19322581825228b6810a9fb3)；许可：源码 MIT；模型权重单独核查。

- 证据：[utils/model_bin.py:28](https://github.com/FunAudioLLM/SenseVoice/blob/586bbdb2b052f4fe19322581825228b6810a9fb3/utils/model_bin.py#L28) — SenseVoiceSmall ONNX 推理封装。
- 证据：[utils/model_bin.py:139](https://github.com/FunAudioLLM/SenseVoice/blob/586bbdb2b052f4fe19322581825228b6810a9fb3/utils/model_bin.py#L139) — 特征输入推理。

值得借鉴：多语言语音识别并提供 ONNX 实现；可复用现有本地中文识别模型。

当前差距或移植成本：当前接入为分段最终识别，不提供实时部分转写；无本机 NPU 性能证据。

决定：保留 sherpa-onnx SenseVoice 作为最终识别

实际落地：通过 sherpa-onnx 使用模型；不是复制其 Python 模型实现。

依赖：ONNX Runtime、模型权重及 token。

### ggml-org/llama.cpp

源码：[10d4846a572a](https://github.com/ggml-org/llama.cpp/tree/10d4846a572aebf21c0482d140b00e74c0f1ad20)；许可：源码 MIT；模型许可独立。

- 证据：[tools/server/server-context.cpp:1019](https://github.com/ggml-org/llama.cpp/blob/10d4846a572aebf21c0482d140b00e74c0f1ad20/tools/server/server-context.cpp#L1019) — 本地推理服务上下文实现。

值得借鉴：本地模型服务与量化生态；可作为替代云端文本生成的运行时。

当前差距或移植成本：本身不替代当前识别与 TTS 语音管线；目标模型及 Windows NPU 未验证。

决定：保留为可选本地 LLM 服务

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：GGML、GGUF 模型及对应后端。

### hexgrad/kokoro

源码：[dfb907a02bba](https://github.com/hexgrad/kokoro/tree/dfb907a02bba8152ca444717ca5d78747ccb4bec)；许可：源码 Apache-2.0；权重和音色许可单独核查。

- 证据：[kokoro/pipeline.py:42](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py#L42) — KPipeline 输出文本、音素和音频。
- 证据：[kokoro/pipeline.py:361](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py#L361) — 文本管线迭代输出。

值得借鉴：分段生成并暴露音素和文本信息；支持音色与速度配置，便于替换 TTS。

当前差距或移植成本：输出分段不代表连续声学流式或音素时间戳；中文音质和 CPU 延迟未在本机测量。

决定：中文音质基准候选，不替换现有 VITS

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch、语言前端、模型及音色。

### huggingface/speech-to-speech

源码：[5108a3eacea8](https://github.com/huggingface/speech-to-speech/tree/5108a3eacea81298a9dc62d5179abcacfb8119f1)；许可：Apache-2.0。

- 证据：[src/speech_to_speech/api/openai_realtime/echo_canceller.py:45](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/api/openai_realtime/echo_canceller.py#L45) — 带时间戳的播放参考。
- 证据：[src/speech_to_speech/api/openai_realtime/echo_canceller.py:60](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/api/openai_realtime/echo_canceller.py#L60) — 带时间戳的采集处理。
- 证据：[src/speech_to_speech/backend_registry.py:90](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/backend_registry.py#L90) — 流水线共享 CancelScope。

值得借鉴：AEC 对齐带时间戳的播放参考和采集音频；共享 CancelScope 协调流水线各阶段取消；支持本地模块化语音处理。

当前差距或移植成本：后端无法获取浏览器实际播放时序及参考信号。

决定：作为参考保留，不单独在服务端移植 AEC

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：pywebrtc_audio 及真实采集、播放时序。

### k2-fsa/sherpa-onnx

源码：[079a6f05d05a](https://github.com/k2-fsa/sherpa-onnx/tree/079a6f05d05a18bc6e993704a557c2f62c7a17a5)；许可：源码 Apache-2.0；每个模型许可单独核查。

- 证据：[sherpa-onnx/python/sherpa_onnx/online_recognizer.py:1051](https://github.com/k2-fsa/sherpa-onnx/blob/079a6f05d05a18bc6e993704a557c2f62c7a17a5/sherpa-onnx/python/sherpa_onnx/online_recognizer.py#L1051) — 在线识别流解码。
- 证据：[sherpa-onnx/python/sherpa_onnx/offline_recognizer.py:1932](https://github.com/k2-fsa/sherpa-onnx/blob/079a6f05d05a18bc6e993704a557c2f62c7a17a5/sherpa-onnx/python/sherpa_onnx/offline_recognizer.py#L1932) — 离线识别流解码。

值得借鉴：同一运行时支持在线与离线识别；本机已使用 SenseVoice 和 VITS；VITS 回调可逐段输出 PCM；本地 CPU 部署避免在线服务依赖。

当前差距或移植成本：回调分段不证明连续声学流式；实验在线模型对数字和部分样本有误识，不能替代最终识别。

决定：继续作为本地生产运行时；在线识别只可选预览

实际落地：直接运行 SenseVoice/VITS/ERes2Net；本轮采用原生 TTS callback 增量 PCM。

依赖：sherpa-onnx、ONNX Runtime、分别下载模型。

### kyutai-labs/moshi

源码：[e6a55d2722a6](https://github.com/kyutai-labs/moshi/tree/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362)；许可：源码 Apache-2.0 或 MIT；权重许可另核查。

- 证据：[moshi/moshi/models/lm.py:786](https://github.com/kyutai-labs/moshi/blob/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/moshi/moshi/models/lm.py#L786) — 语言模型逐步处理音频 token。
- 证据：[moshi/moshi/models/tts.py:497](https://github.com/kyutai-labs/moshi/blob/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/moshi/moshi/models/tts.py#L497) — TTS 生成接口。

值得借鉴：语音 token 模型提供逐步生成机制；探索语音到语音全双工和语调上下文。

当前差距或移植成本：完整模型部署和中文表现未在当前硬件验证；与现有分离 ASR/LLM/TTS 可观测管线接口不同。

决定：研究候选，不作为当前生产依赖

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch 或 Rust 运行时、Moshi/Mimi 模型。

### liampetti/fulloch

源码：[c7b08e736397](https://github.com/liampetti/fulloch/tree/c7b08e736397e2066b13c37fbea2e833e25cd5f0)；许可：MIT。

- 证据：[server/static/js/browser-satellite.js:311](https://github.com/liampetti/fulloch/blob/c7b08e736397e2066b13c37fbea2e833e25cd5f0/server/static/js/browser-satellite.js#L311) — 请求浏览器回声消除与降噪。
- 证据：[server/satellite_v2.py:137](https://github.com/liampetti/fulloch/blob/c7b08e736397e2066b13c37fbea2e833e25cd5f0/server/satellite_v2.py#L137) — 协商 AEC 上行音频通道。
- 证据：[clients/headless/satellite.py:386](https://github.com/liampetti/fulloch/blob/c7b08e736397e2066b13c37fbea2e833e25cd5f0/clients/headless/satellite.py#L386) — 中止或停止扬声器流。

值得借鉴：浏览器卫星端请求浏览器 AEC 和降噪；卫星协议协商 AEC 上行通道；无界面卫星端管理 sounddevice 全双工输入输出并在取消时中止播放。

当前差距或移植成本：本项目浏览器已请求 AEC；尚无实际声学 AEC 或已播放文本确认的测量。

决定：不重复引入卫星运行栈

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：WebSocket 卫星端和音频设备。

### lipku/LiveTalking

源码：[c7269433a2b6](https://github.com/lipku/LiveTalking/tree/c7269433a2b6ecebcd9342445d2ecc882c98b0da)；许可：Apache-2.0。

- 证据：[app.py:102](https://github.com/lipku/LiveTalking/blob/c7269433a2b6ecebcd9342445d2ecc882c98b0da/app.py#L102) — 异步处理 WebRTC offer。
- 证据：[avatars/audio_features/hubert.py:33](https://github.com/lipku/LiveTalking/blob/c7269433a2b6ecebcd9342445d2ecc882c98b0da/avatars/audio_features/hubert.py#L33) — 将音频帧放入特征处理队列。

值得借鉴：WebRTC offer 提供实时传输入口；HuBERT 特征队列支持音频驱动头像管线。

当前差距或移植成本：当前 Pipecat 管理传输和打断，Cubism 是可编辑模型；该头像视频管线需另部署模型，尚无本机延迟比较。。

决定：参考队列和中断边界；不替换现有 Pipecat 与 Cubism。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch/WebRTC。

### Live2D/CubismWebMotionSyncComponents

源码：[9e7a356fb551](https://github.com/Live2D/CubismWebMotionSyncComponents/tree/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4)；许可：Live2D Open Software；Core/SDK 另受 Proprietary/SDK 条款。

- 证据：[README.md:33](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/README.md#L33) — MotionSync Core 不包含在源码仓库，需另取发行包。
- 证据：[Framework/src/cubismmotionsyncprocessorcri.ts:25](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Framework/src/cubismmotionsyncprocessorcri.ts#L25) — CRI Analyze 接收采样、平滑和混合参数。
- 证据：[Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json:1](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json#L1) — 元音映射至多个模型参数的配置样例。

值得借鉴：官方 CRI 声学分析、混合与平滑；模型专属多参数口型映射。

当前差距或移植成本：当前皮肤无 motionsync3 配置，不能直接套用样例；Core 与 SDK 独立许可、发行方式，仓库不是完整可运行依赖。

决定：作为高阶候选，当前采用 MIT wLipSync；不打包未取得的 Core。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Cubism SDK、MotionSync Core、模型专属映射。

### livekit/agents

源码：[652eee4ea809](https://github.com/livekit/agents/tree/652eee4ea809ee524fb0ada2383d06eebc3d93a0)；许可：Apache-2.0。

- 证据：[livekit-agents/livekit/agents/voice/agent_activity.py:5044](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/livekit-agents/livekit/agents/voice/agent_activity.py#L5044) — 启用时恢复误打断。
- 证据：[livekit-agents/livekit/agents/voice/agent.py:113](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/livekit-agents/livekit/agents/voice/agent.py#L113) — 选择自适应或 VAD 打断检测。
- 证据：[livekit-agents/livekit/agents/voice/agent_session.py:445](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/livekit-agents/livekit/agents/voice/agent_session.py#L445) — 打断时长、词数和超时选项。

值得借鉴：误打断计时器可恢复暂停的语音；支持自适应及 VAD 打断；可配置打断最短时长和词数；提供 RTC 和会话指标。

当前差距或移植成本：当前 Pipecat 路径尚无经验证的等价暂停恢复或已听播放确认。

决定：保留 Pipecat；替换前评测轮次检测

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：LiveKit RTC 及所选插件和模型。

### modelscope/FunASR

源码：[fd1d4aa655ef](https://github.com/modelscope/FunASR/tree/fd1d4aa655effca86dc03b70a09db7e4e6409a10)；许可：源码 MIT；具体模型许可另核查。

- 证据：[funasr/models/paraformer_streaming/model.py:47](https://github.com/modelscope/FunASR/blob/fd1d4aa655effca86dc03b70a09db7e4e6409a10/funasr/models/paraformer_streaming/model.py#L47) — 分块流式识别与 cache。
- 证据：[funasr/auto/auto_model.py:841](https://github.com/modelscope/FunASR/blob/fd1d4aa655effca86dc03b70a09db7e4e6409a10/funasr/auto/auto_model.py#L841) — 统一 generate 入口。

值得借鉴：Paraformer 流式缓存允许增量识别；模型和预处理组件丰富，支持多种中文语音任务。

当前差距或移植成本：新模型须实测打断、误识率与 Windows 性能；目前 SenseVoice 最终结果已集成，迁移会增加模型与依赖。

决定：作为在线识别对照候选，保留 SenseVoice final

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：FunASR、PyTorch、模型与前端。

### moeru-ai/airi

源码：[11b8989f6dd7](https://github.com/moeru-ai/airi/tree/11b8989f6dd7f840cf6b15ce59e367656fb11ac6)；许可：MIT。

- 证据：[packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts:101](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts#L101) — 按音量和胜出权重判断静音。
- 证据：[packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts:117](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts#L117) — 根据经过时间进行元音权重攻放平滑。
- 证据：[packages/model-driver-lipsync/src/live2d/index.ts:76](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/model-driver-lipsync/src/live2d/index.ts#L76) — 创建 wLipSync 音频节点。

值得借鉴：wLipSync 对音频频谱做元音分类；元音结果按真实时间平滑并有静音门限；已有 Live2D 音频节点适配。

当前差距或移植成本：当前已接入固定驱动和上游 profile；该 profile 未针对本地中文 VITS 校准，U/O 分类实测不稳定。。

决定：已复用 MIT 元音驱动与 profile；后续使用 uLipSync 对本地声音校准并验证。

实际落地：直接移植元音 driver、样例 profile；此前已移植 MAGIC 和渲染补丁，来源提交分别记录。

依赖：wlipsync/WASM。

### mrxz/wlipsync

源码：[177f3ac4095d](https://github.com/mrxz/wlipsync/tree/177f3ac4095dbad81be0a800a8c6f975abe4ae04)；许可：MIT。

- 证据：[src/main.c:130](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/src/main.c#L130) — 实际音频频谱/MFCC 提取及模板分类，非单一响度。
- 证据：[www/audio-node.ts:70](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/www/audio-node.ts#L70) — 按真实音频时间更新分类权重和平滑。
- 证据：[README.md:55](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/README.md#L55) — 官方未提供校准创建器，指向 Unity uLipSync 流程。

值得借鉴：浏览器 WASM/AudioWorklet 可直接分析实际播放 PCM；兼容 uLipSync 声学校准模板和多个元音类别；MIT，单文件内嵌 WASM 无额外运行服务。

当前差距或移植成本：AIRI 通用模板对当前 VITS 有元音混淆；本地声线模板改善 U 收唇，但 E/O 仍会混淆；不提供辅音或字级时间对齐。

决定：直接固定依赖1.3.1；使用原版 WASM MFCC 导出生成本地声线模板，保留 AIRI 样例供其他声音选择。

实际落地：直接依赖 WASM 频谱分类；新增声线模板校准工具与选择界面。

依赖：WebAudio AudioWorklet、WASM、声音专属 profile、localhost/HTTPS。

### ollama/ollama

源码：[a6d33251620e](https://github.com/ollama/ollama/tree/a6d33251620eef7629c73b09e672f2df243eb363)；许可：源码 MIT；模型许可单独核查。

- 证据：[server/routes.go:308](https://github.com/ollama/ollama/blob/a6d33251620eef7629c73b09e672f2df243eb363/server/routes.go#L308) — 本地生成 HTTP 处理。
- 证据：[server/routes.go:3019](https://github.com/ollama/ollama/blob/a6d33251620eef7629c73b09e672f2df243eb363/server/routes.go#L3019) — 聊天 HTTP 处理。

值得借鉴：本地模型服务与模型管理；文本流可连接现有对话流水线。

当前差距或移植成本：不是 ASR/TTS 实现；本机模型性能及 NPU 后端未实测。

决定：作为可选本地 LLM，语音继续由现有组件负责

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Ollama 服务与模型权重。

### Open-LLM-VTuber/Open-LLM-VTuber

源码：[992309c0aa19](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/tree/992309c0aa19845960228f880013d4685fde93b5)；许可：MIT。

- 证据：[src/open_llm_vtuber/websocket_handler.py:369](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/websocket_handler.py#L369) — 处理中断消息。
- 证据：[src/open_llm_vtuber/asr/asr_interface.py:11](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/asr/asr_interface.py#L11) — 定义异步转写接口。

值得借鉴：中断处理与 WebSocket 会话集中管理；ASR 接口可替换，默认异步包装同步引擎。

当前差距或移植成本：当前已有 Pipecat 中断与 ASR 适配，替换框架将增加整合成本；线程包装无法保证抢占原生计算。。

决定：参考可替换 ASR 和中断边界；保留现有 Pipecat。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Python/ASR。

### Open-LLM-VTuber/Open-LLM-VTuber-Web

源码：[d176e7df2366](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/tree/d176e7df2366952e3bacbf12cf9a8b18a4315932)；许可：Open-LLM-VTuber License 1.0。

- 证据：[src/renderer/WebSDK/src/lappwavfilehandler.ts:63](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/WebSDK/src/lappwavfilehandler.ts#L63) — 从音频计算 RMS 口型幅度。
- 证据：[src/renderer/src/utils/audio-manager.ts:20](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/utils/audio-manager.ts#L20) — 同时停止当前音频和口型。

值得借鉴：基于 PCM 的 RMS 驱动嘴部开合；播放与口型支持统一停止；提供 Cubism Web SDK 集成。

当前差距或移植成本：当前已有播放生命周期与 Cubism 集成；RMS 无法区分等响度元音，其前端许可条款需单独审阅。。

决定：参考停止生命周期；不复制定制许可代码或退回纯 RMS。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Electron/Cubism SDK。

### openai/whisper

源码：[86098128c0b4](https://github.com/openai/whisper/tree/86098128c0b4f24f0e2aa2994de830614b474227)；许可：源码 MIT；权重许可另核查。

- 证据：[whisper/transcribe.py:38](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/transcribe.py#L38) — 分段转写实现。
- 证据：[whisper/timing.py:279](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/timing.py#L279) — 单词时间戳对齐。

值得借鉴：多语言识别与翻译；提供词级时间戳对齐实现。

当前差距或移植成本：文件窗口转写并非原生实时部分识别；相对当前 SenseVoice CPU 路径性能未实测。

决定：作为质量对照；运行时优先现有 faster-whisper fallback

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch、Whisper 权重、音频解码。

### OpenBMB/MiniCPM-o

源码：[47e1fa75b45b](https://github.com/OpenBMB/MiniCPM-o/tree/47e1fa75b45b8c122ca2a52150762bf6183f1c5e)；许可：Apache-2.0; model terms separate。

- 证据：[web_demos/minicpm-o_2.6/model_server.py:66](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/web_demos/minicpm-o_2.6/model_server.py#L66) — 用事件跟踪流式完成状态。
- 证据：[web_demos/minicpm-o_2.6/vad_utils.py:266](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/web_demos/minicpm-o_2.6/vad_utils.py#L266) — 对输入音频运行 VAD。

值得借鉴：记录流式生成完成状态并检测超时；VAD 分段和音频 prefill 支持多模态流式处理。

当前差距或移植成本：当前采用独立 ASR/LLM/TTS 服务，没有端到端多模态模型；部署权重及设备要求需额外验证。。

决定：作为备选多模态路线；先评估权重许可和本机实时性能。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch/model weights。

### OpenBMB/VoxCPM

源码：[4b8dd4440d33](https://github.com/OpenBMB/VoxCPM/tree/4b8dd4440d33396b3f429201f8af0529b4d2c601)；许可：源码 Apache-2.0；模型权重单独核查。

- 证据：[src/voxcpm/core.py:201](https://github.com/OpenBMB/VoxCPM/blob/4b8dd4440d33396b3f429201f8af0529b4d2c601/src/voxcpm/core.py#L201) — 完整生成与流式接口。
- 证据：[src/voxcpm/core.py:312](https://github.com/OpenBMB/VoxCPM/blob/4b8dd4440d33396b3f429201f8af0529b4d2c601/src/voxcpm/core.py#L312) — 提示缓存与逐步波形生成。

值得借鉴：generate_streaming 逐步产生波形块；参考提示缓存提供语音条件控制；可探索自然度和音色迁移。

当前差距或移植成本：本机 CPU/NPU、首音延迟和中文音质未验证；与现有 VITS 的依赖和模型体积不同。

决定：保留候选，单独做权重许可和基准测试

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch、VoxCPM 权重及音频模型。

### pipecat-ai/pipecat

源码：[de8998789d56](https://github.com/pipecat-ai/pipecat/tree/de8998789d5690073ddd1dafcec7268839af8153)；许可：BSD-2-Clause。

- 证据：[src/pipecat/pipeline/worker.py:185](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/src/pipecat/pipeline/worker.py#L185) — 配置流水线指标。
- 证据：[src/pipecat/services/tts_service.py:85](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/src/pipecat/services/tts_service.py#L85) — 定义按句和按 token 聚合。
- 证据：[src/pipecat/processors/aggregators/llm_response_universal.py:169](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/src/pipecat/processors/aggregators/llm_response_universal.py#L169) — 描述被打断后的空轮次恢复。

值得借鉴：原生帧流水线处理打断传播和上下文聚合；原生指标提供处理器首帧时间和处理时长；TTS 支持按句与按 token 聚合。

当前差距或移植成本：服务端首帧时间不等于设备实际播放延迟。

决定：启用原生指标；中文语音保留按句聚合

实际落地：直接作为生产编排内核，Silero、Smart Turn、backchannel、取消、RTVI；本轮启用原生 metrics。

依赖：pipecat-ai 1.15 及本地语音适配器。

### pipecat-ai/pipecat-client-web

源码：[c6a0a68c8d56](https://github.com/pipecat-ai/pipecat-client-web/tree/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79)；许可：BSD-2-Clause。

- 证据：[client-js/rtvi/messages.ts:47](https://github.com/pipecat-ai/pipecat-client-web/blob/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79/client-js/rtvi/messages.ts#L47) — 定义 metrics 消息。
- 证据：[client-js/client/client.ts:41](https://github.com/pipecat-ai/pipecat-client-web/blob/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79/client-js/client/client.ts#L41) — 使用有类型的指标数据。

值得借鉴：有类型的 RTVI 指标消息；客户端回调暴露打断和播放状态；传输层与应用界面解耦。

当前差距或移植成本：指标不能证明实际播放或已听历史。

决定：使用现有客户端及标准消息

实际落地：直接依赖官方 client-js 1.16.0；源码归档与实际发行包版本分别记录。

依赖：浏览器及兼容传输层。

### pipecat-ai/pipecat-client-web-transports

源码：[5cc10220f45e](https://github.com/pipecat-ai/pipecat-client-web-transports/tree/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f)；许可：BSD-2-Clause。

- 证据：[transports/websocket-transport/src/webSocketTransport.ts:234](https://github.com/pipecat-ai/pipecat-client-web-transports/blob/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f/transports/websocket-transport/src/webSocketTransport.ts#L234) — 处理打断消息。
- 证据：[transports/websocket-transport/src/generated/proto/frames.ts:118](https://github.com/pipecat-ai/pipecat-client-web-transports/blob/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f/transports/websocket-transport/src/generated/proto/frames.ts#L118) — 定义打断帧。

值得借鉴：官方 WebSocket 传输层解析打断；支持多种传输实现；有类型的 protobuf 帧序列化音频和控制消息。

当前差距或移植成本：无法证明发出的音频已到达扬声器。

决定：保留官方传输层，不推断已播放历史

实际落地：直接依赖 websocket-transport 1.8.2 官方 PCM worklet/protobuf 传输。

依赖：浏览器音频和 WebSocket 传输包。

### pipecat-ai/pipecat-examples

源码：[7875d02bc071](https://github.com/pipecat-ai/pipecat-examples/tree/7875d02bc0714d59528b0c8797664308af960a3a)；许可：BSD-2-Clause。

- 证据：[daily-multi-translation/bot.py:12](https://github.com/pipecat-ai/pipecat-examples/blob/7875d02bc0714d59528b0c8797664308af960a3a/daily-multi-translation/bot.py#L12) — 语音流水线导入 Silero VAD。
- 证据：[aws-agentcore/bot.py:11](https://github.com/pipecat-ai/pipecat-examples/blob/7875d02bc0714d59528b0c8797664308af960a3a/aws-agentcore/bot.py#L11) — 另一机器人集成使用 Silero VAD。

值得借鉴：展示 Silero VAD 流水线组合；提供多种集成实现；可参考框架模式进行兼容性测试。

当前差距或移植成本：示例部署和模型选择不能验证本项目效果。

决定：仅参考流水线模式

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Pipecat 及各示例所需服务。

### pipecat-ai/smart-turn

源码：[4786657e242d](https://github.com/pipecat-ai/smart-turn/tree/4786657e242dfe77dd138699ac564ee074a2a543)；许可：BSD-2-Clause; separately check model weights。

- 证据：[record_and_predict.py:192](https://github.com/pipecat-ai/smart-turn/blob/4786657e242dfe77dd138699ac564ee074a2a543/record_and_predict.py#L192) — 预测轮次完整或未完成并报告概率。
- 证据：[benchmark.py:372](https://github.com/pipecat-ai/smart-turn/blob/4786657e242dfe77dd138699ac564ee074a2a543/benchmark.py#L372) — 报告 p50 和 p90 延迟。

值得借鉴：基于音频的轮次结束模型补充 VAD；基准工具报告 p50、p90 和吞吐量。

当前差距或移植成本：中文轮次准确率及硬件延迟尚未测量。

决定：当前已使用：Pipecat 默认结束策略加载 LocalSmartTurn v3.2 CPU；需测量中文轮次准确率与延迟

实际落地：通过 Pipecat 使用 Local Smart Turn v3.2 收尾判断，不自写轮次模型。

依赖：模型权重及模型推理运行时。

### QwenLM/Qwen3-ASR

源码：[7c6daf77a242](https://github.com/QwenLM/Qwen3-ASR/tree/7c6daf77a2421100f5fb066495372c00129d39ff)；许可：源码 Apache-2.0；权重按对应模型卡。

- 证据：[qwen_asr/inference/qwen3_asr.py:584](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py#L584) — 流式识别状态初始化。
- 证据：[qwen_asr/inference/qwen3_asr.py:657](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py#L657) — PCM 分块流式转写。
- 证据：[qwen_asr/inference/qwen3_forced_aligner.py:395](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_forced_aligner.py#L395) — 强制时间对齐。

值得借鉴：支持有状态实时 PCM 增量识别；可选强制对齐产生中文字符或词时间区间；批量和离线转写接口。

当前差距或移植成本：模型及依赖较重，本机实时性能未测；对齐依赖独立模型，不能从当前文本直接推断口型。

决定：候选方案，基于真实麦克风准确率和首字延迟比较

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch/Transformers 或 vLLM、ASR 和可选对齐模型。

### QwenLM/Qwen3-Omni

源码：[e42358531255](https://github.com/QwenLM/Qwen3-Omni/tree/e4235853125589c789f06a2dd83e9f4126df5e9d)；许可：源码 Apache-2.0；模型权重按模型卡。

- 证据：[web_demo_captioner.py:50](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/web_demo_captioner.py#L50) — 音频输入生成描述演示。

值得借鉴：统一多模态音频理解能力；可探索直接音频对话与上下文理解。

当前差距或移植成本：演示路径不是可直接替换的本地实时语音服务；模型硬件和中文全双工延迟未验证。

决定：研究候选，先保留分离管线

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Transformers/PyTorch、多模态模型。

### QwenLM/Qwen3-TTS

源码：[022e286b98fb](https://github.com/QwenLM/Qwen3-TTS/tree/022e286b98fbec7e1e916cb940cdf532cd9f488e)；许可：源码 Apache-2.0；权重按模型卡。

- 证据：[qwen_tts/inference/qwen3_tts_model.py:470](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L470) — 语音克隆生成。
- 证据：[qwen_tts/inference/qwen3_tts_model.py:513](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L513) — 明确说明该选项不提供真正流式生成。
- 证据：[qwen_tts/inference/qwen3_tts_model.py:637](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L637) — 文本描述音色设计。

值得借鉴：参考语音克隆、预设音色和文字音色设计；可按语言和风格控制生成。

当前差距或移植成本：所审推理接口 non_streaming_mode 不等于真正流式输入或生成；本机 CPU/NPU 首音延迟与模型许可未验证。

决定：作为音质及音色候选，不以模拟流式替换现有回调

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch、Transformers、Qwen3-TTS 模型。

### QwenLM/Qwen3.5

源码：[2ea10dc72582](https://github.com/QwenLM/Qwen3.5/tree/2ea10dc725823bf7c3e21ce8557cbe15245132ae)；许可：仓库 Apache-2.0；模型版本许可独立核查。

- 证据：[README.md:34](https://github.com/QwenLM/Qwen3.5/blob/2ea10dc725823bf7c3e21ce8557cbe15245132ae/README.md#L34) — 模型系列介绍；固定归档无实现代码。

值得借鉴：可作为中文对话模型候选；不同尺寸允许本地资源与能力权衡。

当前差距或移植成本：固定归档没有可检查的推理实现；不是直接的流式 ASR 或 TTS。

决定：在外部运行时作为可选 LLM 评测；不声称实现已审计

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：外部 Transformers、Ollama 或其他支持的运行时及权重。

### snakers4/silero-vad

源码：[066409f3d9db](https://github.com/snakers4/silero-vad/tree/066409f3d9db45a30d21dfcbf9147826ffdd7052)；许可：源码 MIT；模型许可另核查。

- 证据：[src/silero_vad/utils_vad.py:281](https://github.com/snakers4/silero-vad/blob/066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/utils_vad.py#L281) — 语音区间检测。
- 证据：[src/silero_vad/utils_vad.py:591](https://github.com/snakers4/silero-vad/blob/066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/utils_vad.py#L591) — 有状态 VADIterator。

值得借鉴：流式 VADIterator 支持逐块检测；分段接口提供语音区间和阈值控制。

当前差距或移植成本：VAD 只检测语音活动，不验证身份或语义打断；真实环境阈值和漏检需要麦克风测试。

决定：沿用 Pipecat 的 Silero VAD，保持上层策略

实际落地：通过 Pipecat 与声纹质量门使用。

依赖：Silero 模型、ONNX Runtime 或 PyTorch。

### suzuran0y/Live2D-LLM-Chat

源码：[b333789c0962](https://github.com/suzuran0y/Live2D-LLM-Chat/tree/b333789c0962cd6244330120ec24634f8a5a70a8)；许可：Apache-2.0。

- 证据：[packages/contracts/protocol.py:16](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/packages/contracts/protocol.py#L16) — 验证 WAV 的 RIFF 长度及格式。
- 证据：[workers/asr/worker.py:39](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/workers/asr/worker.py#L39) — ASR worker 调用转写引擎。

值得借鉴：音频协议校验 RIFF 长度和 WAV 格式；ASR worker 与通信契约分离；支持音频分块确认事件。

当前差距或移植成本：当前使用 Pipecat PCM 流和已有 WAV 录入校验，不使用其独立 worker 协议。。

决定：参考输入验证与 worker 隔离；不增加重复传输协议。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：Python/ASR。

### SYSTRAN/faster-whisper

源码：[2a3a857737d1](https://github.com/SYSTRAN/faster-whisper/tree/2a3a857737d17d974f30d818ebec69ce11929e5c)；许可：源码 MIT；转换模型许可另核查。

- 证据：[faster_whisper/transcribe.py:254](https://github.com/SYSTRAN/faster-whisper/blob/2a3a857737d17d974f30d818ebec69ce11929e5c/faster_whisper/transcribe.py#L254) — 批量分段转写。
- 证据：[faster_whisper/transcribe.py:285](https://github.com/SYSTRAN/faster-whisper/blob/2a3a857737d17d974f30d818ebec69ce11929e5c/faster_whisper/transcribe.py#L285) — 词级时间戳和 VAD 参数。

值得借鉴：CTranslate2 支持 CPU int8 转写；支持词级时间戳和 VAD 过滤；适合作为 SenseVoice 不可用时回退。

当前差距或移植成本：按音频分段识别，不保证原生实时增量；与 SenseVoice 的本机准确率和端到端延迟仍需比较。

决定：保留现有本地 fallback

实际落地：保留可选识别后备，当前主识别为 SenseVoice。

依赖：CTranslate2、faster-whisper、Whisper 模型。

### TacoTakumi/HermesConsole

源码：[55d8c732482c](https://github.com/TacoTakumi/HermesConsole/tree/55d8c732482cfbab398cfcab68d8eea08146d2ba)；许可：MIT。

- 证据：[app/src/androidTest/kotlin/com/hermesconsole/app/AecHardwareGateTest.kt:46](https://github.com/TacoTakumi/HermesConsole/blob/55d8c732482cfbab398cfcab68d8eea08146d2ba/app/src/androidTest/kotlin/com/hermesconsole/app/AecHardwareGateTest.kt#L46) — 硬件回环 AEC 验收。
- 证据：[scripts/make-bargein-speech.py:3](https://github.com/TacoTakumi/HermesConsole/blob/55d8c732482cfbab398cfcab68d8eea08146d2ba/scripts/make-bargein-speech.py#L3) — 生成可重复的语音打断样本。

值得借鉴：物理设备 AEC 测试覆盖扬声器到麦克风路径；提供可重复语音刺激生成；区分设备端音频行为与服务端响应。

当前差距或移植成本：针对 Android 硬件，不能代表本项目浏览器音频路径。

决定：借鉴测试原则，不移植生产代码

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：具备采集和播放能力的 Android 设备。

### TacoTakumi/VoiceManager

源码：[256d573cbd69](https://github.com/TacoTakumi/VoiceManager/tree/256d573cbd6981da29f51dc66faabcebb83d8eab)；许可：MIT。

- 证据：[src/voicemanager/protocol.py:90](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/protocol.py#L90) — 定义 cancelled 和 interrupted 结束原因。
- 证据：[src/voicemanager/transport/turn_engine.py:115](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/transport/turn_engine.py#L115) — 取消被打断回复并发送音频结束信号。
- 证据：[src/voicemanager/client.py:189](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/client.py#L189) — 客户端接收 interrupted 音频结束事件。

值得借鉴：全双工流式 STT 与 TTS 协议；TTS 结束状态区分取消和打断；轮次引擎处理取消与音频结束状态。

当前差距或移植成本：替换现有适配器成本高，且不能证明浏览器 AEC 效果。

决定：保留现有语音服务；基准测试后再考虑协议

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：STT、TTS 模型、VAD 和运行时依配置变化。

### THUDM/GLM-4-Voice

源码：[eb00ce9142e8](https://github.com/THUDM/GLM-4-Voice/tree/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a)；许可：源码 Apache-2.0；模型许可另核查。

- 证据：[flow_inference.py:97](https://github.com/THUDM/GLM-4-Voice/blob/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a/flow_inference.py#L97) — 音频 token 流式推理。
- 证据：[model_server.py:83](https://github.com/THUDM/GLM-4-Voice/blob/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a/model_server.py#L83) — 模型 token 流式生成。

值得借鉴：语音 token 生成与流式声音解码；端到端语音上下文可探索自然交互。

当前差距或移植成本：模型服务与语音 tokenizer 部署复杂；本机硬件与中文全双工实测缺失。

决定：研究候选，暂不替换当前管线

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch、GLM 模型、语音 tokenizer 和 flow 模型。

### TMElyralab/MuseTalk

源码：[0a89dec45a01](https://github.com/TMElyralab/MuseTalk/tree/0a89dec45a0192b824e3cf4daf96c239440c5ed8)；许可：MIT; model terms separate。

- 证据：[scripts/realtime_inference.py:212](https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py#L212) — 处理生成的人脸视频帧。
- 证据：[scripts/realtime_inference.py:239](https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py#L239) — 执行音频条件实时推理。
- 证据：[scripts/realtime_inference.py:164](https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py#L164) — 从图像提取人脸关键点和边界框。

值得借鉴：音频条件驱动人脸视频帧生成；预处理人脸关键点和边界框；提供实时推理入口。

当前差距或移植成本：该项目生成像素人脸视频，并非 Cubism 参数驱动；本机实时延迟、显存及资源占用均未测量。。

决定：保留为像素视频替代路线；无法直接移植到当前 Cubism 参数。

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：PyTorch/FFmpeg。

### vllm-project/vllm

源码：[14d147a7a05d](https://github.com/vllm-project/vllm/tree/14d147a7a05d29d011a67ed1f1f819c03546dafe)；许可：源码 Apache-2.0；模型许可独立。

- 证据：[vllm/v1/engine/async_llm.py:411](https://github.com/vllm-project/vllm/blob/14d147a7a05d29d011a67ed1f1f819c03546dafe/vllm/v1/engine/async_llm.py#L411) — 异步请求提交。
- 证据：[vllm/v1/engine/async_llm.py:740](https://github.com/vllm-project/vllm/blob/14d147a7a05d29d011a67ed1f1f819c03546dafe/vllm/v1/engine/async_llm.py#L740) — 异步生成接口。

值得借鉴：异步请求处理和增量 token 生成；高吞吐模型服务适合共享服务器。

当前差距或移植成本：不直接提供完整语音管线；本机 Windows/NPU 部署和单用户延迟未验证。

决定：远程 LLM 服务候选，当前不引入

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：vLLM、支持的硬件后端和模型。

### vllm-project/vllm-omni

源码：[1200aa7379ff](https://github.com/vllm-project/vllm-omni/tree/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9)；许可：源码 Apache-2.0；模型许可独立。

- 证据：[vllm_omni/entrypoints/async_omni.py:150](https://github.com/vllm-project/vllm-omni/blob/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9/vllm_omni/entrypoints/async_omni.py#L150) — 多模态异步生成。
- 证据：[vllm_omni/clients/duplex.py:801](https://github.com/vllm-project/vllm-omni/blob/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9/vllm_omni/clients/duplex.py#L801) — 双工 PCM 客户端接口。

值得借鉴：多模态服务及音频双工接口；可复用模型服务与增量生成基础设施。

当前差距或移植成本：本机部署依赖与硬件适配未验证；不能推定所有模型均支持流式或相同协议。

决定：面向有加速服务器的后续对照方案

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：vLLM Omni、支持的运行时及多模态模型。

### wwbin2017/bailing

源码：[2f7dc881b684](https://github.com/wwbin2017/bailing/tree/2f7dc881b684c50fb0c612361a34b44bd5626aea)；许可：源码 MIT；模型与服务条款单独核查。

- 证据：[bailing/asr.py:36](https://github.com/wwbin2017/bailing/blob/2f7dc881b684c50fb0c612361a34b44bd5626aea/bailing/asr.py#L36) — FunASR 识别封装。
- 证据：[bailing/tts.py:202](https://github.com/wwbin2017/bailing/blob/2f7dc881b684c50fb0c612361a34b44bd5626aea/bailing/tts.py#L202) — Kokoro TTS 封装。

值得借鉴：展示 ASR/TTS 可替换接口；集成多种本地或在线语音后端。

当前差距或移植成本：部分后端依赖网络或平台组件；项目调度与 Pipecat 生命周期不同，音质和中断无本机证据。

决定：借鉴适配器边界，不整体迁移

实际落地：未将该项目新增为生产依赖；具体可移植点和限制见决定。

依赖：具体选择的 FunASR、Kokoro 或在线语音服务。
