# 当前语音系统与全部46个上游的差距审查

日期：2026-11-06。当前生产代码基线：`5c5ce43`。逐仓核查语音相关实现和文档，共46个仓库、99项能力、120处上游源码/文档引用。

结论：当前已经具备可运行的分离式语音链路、框架取消、增量PCM、声纹筛选和声学元音口型。与相关上游相比，主要差距是增量识别与更早可靠打断、同步播放参考AEC、播放确认及恢复、音色韵律控制、可靠中文音素时间口型，以及真实场景长期验收。部分上游功能已经被我们采用；另一些属于视频头像、桌面壳或服务器部署，不应全部算成我们落后。

范围逐一对齐 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)：研究附件中的18个直接GitHub仓库地址，加上按名称补齐的项目及直接支持库，以及官方MotionSync/wLipSync。重新提取比对后46项无缺失、无重复。本次使用本地固定归档，不声称是远端最新HEAD，不下载/运行全部模型。上游实现存在不等于本机中文更准、更快或NPU可用。

完整机器可读审查：[CURRENT_VOICE_GAPS.json](CURRENT_VOICE_GAPS.json)。此前移植记录仍见 [OPEN_SOURCE_LANGUAGE_REVIEW.md](OPEN_SOURCE_LANGUAGE_REVIEW.md)，本文件按当前实现重新判定差距。

## 当前基线

| 环节 | 当前真实实现 |
|---|---|
| 识别 | 连续PCM输入，但LocalSpeechSTT收完整VAD片段后HTTP请求SenseVoice，仅产生finalized=True；尚无实时部分转写。 证据：[speech/pipecat_services.py:47](../speech/pipecat_services.py#L47)；[speech/pipecat_services.py:77](../speech/pipecat_services.py#L77) |
| 轮次与打断 | 已有Silero、默认Local Smart Turn结束判断、播放时先duck；硬打断只由确认最终转写触发，附和为有限中文规则。 证据：[server/pipecat_voice.py:80](../server/pipecat_voice.py#L80)；[speech/pipecat_turns.py:9](../speech/pipecat_turns.py#L9)；[speech/pipecat_turns.py:36](../speech/pipecat_turns.py#L36) |
| 语音输出 | 按句文本提交VITS，通过原生callback提前发送PCM，有界准入/连接复用/取消持锁；不支持同一合成会话持续append LLM token。 证据：[speech/pipecat_services.py:134](../speech/pipecat_services.py#L134)；[speech/server.py:474](../speech/server.py#L474) |
| 播放与历史 | 官方PCM播放器、手动停止、清队与口型重置已具备；服务器保存框架输出历史，没有应用级播放进度/完成ACK。 证据：[web/src/voice.ts:182](../web/src/voice.ts#L182)；[server/pipecat_voice.py:120](../server/pipecat_voice.py#L120)；[docs/PROTOCOL.md:37](../docs/PROTOCOL.md#L37) |
| 回声与降噪 | 浏览器请求AEC/NS/AGC，并展示实际报告；生产后端无同步扬声器参考AEC。独立APM实验及合成测试不能证明外放双讲效果。 证据：[web/src/voice.ts:135](../web/src/voice.ts#L135)；[server/pipecat_voice.py:91](../server/pipecat_voice.py#L91) |
| 本人声音 | CPU ERes2Net/Silero、2—5样本模板、质量门和相似度筛选；整段至少2秒有效人声后核对，不是在线多说话人分离/目标声音提取。 证据：[speech/speaker.py:79](../speech/speaker.py#L79)；[speech/speaker.py:131](../speech/speaker.py#L131) |
| 口型与表情 | wLipSync/MFCC、AIRI平滑、本地声线模板、多嘴参数已具备；没有音素时间区间，E/O/U混淆；表情仍按TTS文本关键词近似。 证据：[web/src/voice.ts:47](../web/src/voice.ts#L47)；[web/src/avatar/lipsync/adapter.ts:10](../web/src/avatar/lipsync/adapter.ts#L10)；[web/src/voice.ts:162](../web/src/voice.ts#L162) |
| 工程与验收 | 原生阶段metrics、受控回归和一次真实DeepSeek链路已具备；无持续真人P50/P95、真实外放AEC指标、长时噪声/多人语音验收。语音实际CPU。 证据：[server/pipecat_voice.py:97](../server/pipecat_voice.py#L97)；[docs/VALIDATION.md:1](../docs/VALIDATION.md#L1) |

最近实测是历史证据：短/长句各3次CPU HTTP首PCM中位约0.124/0.125秒；一次真实DeepSeek文本输入至首次嘴动约2.51秒；约1.91秒合成插话至框架interruption约2.81秒。它们不是本轮新性能测试，不代表P50/P95、真实麦克风/扬声器时延或自然度评分，原始边界见 [VALIDATION.md](VALIDATION.md)。

## 优先差距

| 优先级 | 差距及主要参考 | 为什么仍有差距 / 采用前提 |
|---|---|
| P0 | **增量识别和更早的可靠打断**；sherpa-onnx / FunASR / Qwen3-ASR / VoiceManager | 在说话过程中获得部分文字，再结合本人声音门和打断意图区分。Smart Turn已经接入，继续等final ASR不会获得首词打断。 先对中文短指令、附和、数字和噪声做质量/延迟对照；声纹当前要求2秒，不能直接让陌生人的部分转写启动回答。 |
| P0 | **核查并修复现有口型依赖与校准质量**；wLipSync / HF STV / MotionSync | 已发现六类配置MFCC写入范围问题；当前嘴形会变，但不等于发音分类正确。 先处理依赖问题并重新收集模板、独立验证；再比较中文音素模型或官方引擎，不能盲搬默认英文模型。 |
| P0 | **真实外放AEC与双讲验收**；HF speech-to-speech / Edge-Voice-Assistant / HermesConsole | 需要正确播放参考和ADC/DAC时钟，且证明角色说话时用户人声仍被保留。 浏览器内建AEC与原生设备APM分开评测；不能在没有正确参考时叠加第二层AEC。 |
| P1 | **播放确认、已听历史和误打断恢复**；LiveKit / Open-LLM-VTuber Web / VoiceManager | 把实际播放区间回传服务端，才有条件截断上下文并决定续播还是新回答。 上游完成回执/整段展示文本也不等于逐字已听。Pipecat empty-user-turn重新提示LLM，不是原音续播。 |
| P1 | **韵律、音色与文本/音频双向流**；CosyVoice / VoxCPM / Qwen3-TTS / AIRI | 当前VITS能早出PCM，仍没有参考音色克隆、自然语言风格控制、跨句统一韵律或持续文本输入会话。 中文音质、首音、长句停顿、资源占用和权重许可要分别实测；模型API的stream参数不自动代表双向文本流。 |
| P1 | **声音身份与复杂声场**；HF diarization / Evatar / sherpa-onnx | 当前能做整段单人模板验证，尚不能持续跟踪多人、分离同时讲话或只提取用户声音。 diarization只标谁在何时说话，不等于认出已注册的你，也不等于消除重叠语音；短命令误拒绝和重放需另评估。 |
| P1 | **持续观测、压力和真人验收**；Smart Turn benchmarks / Pipecat metrics / HermesConsole / VoiceManager | 原生阶段指标已有，但欠缺用户可感知的整链时钟、队列水位、欠载/溢出、误打断率及长时统计。 目前0.124秒首PCM和2.51秒云端首次嘴动分别是小样本组件/单次链路，不能当P50/P95或物理首音。 |
| P2 | **端到端语音模型与规模化部署**；Moshi / MiniCPM-o / GLM-4-Voice / Qwen3-Omni / vLLM-Omni / OpenTalking | 可以探索保留语气的直接语音理解、模型层双工、主动发言，或多会话服务。 这类功能可能需要整体架构和硬件改变；不一定适合当前Intel Windows单人Live2D产品，不能先当确定收益。 |

## 判定含义与覆盖统计

- **缺失**（25项）：上游有对应接口/实现，当前生产链未接入；适用性与效果仍受模型、后端、硬件和许可证限制。
- **部分**（31项）：当前有同类基础能力，但缺少所列细节，或上游只提供不同层级的机制；不等于完全落后。
- **已具备**（22项）：当前已直接复用或有同等用途机制，不计为新增缺口。
- **非同类**（14项）：用于另一产品/部署层；不能直接称作当前语音体验优势。
- **待验证**（7项）：源码/文档提供候选或配置，但实现完整性、对应后端或本机效果尚不够确定。

这些数量是按本次列举的能力项统计，不是统一打分；同一仓库可以同时有已具备、部分和缺失项。未发现额外优势时明确写出，不为凑差距而把已有能力重新列作缺失。

## 46仓库总表

| 项目 | 源码中值得借鉴的机制及当前判定 |
|---|---|
| akkoaya/EvatarFramework | 多样本声纹模板归一化与匹配：**部分**；原生客户端重连与退避配置：**已具备** |
| aryeo0908/whisper-loop | 独立轮次任务取消与通知：**已具备**；流式 LLM 按句入队 TTS：**已具备** |
| Code-Amadeus/Amadeus | 基于音量及回声候选的插话判断：**部分**；最终音频消费接口：**已具备** |
| CoreWorxLab/local-livekit-plugins | Piper ChunkedStream 封装分块音频：**部分**；faster-whisper STT 适配器：**已具备** |
| datascale-ai/opentalking | Redis 会话状态和任务排队：**非同类**；上传音频前明确打断：**部分** |
| electron/electron | 桌面媒体权限策略：**非同类**；来源权限检查：**非同类** |
| FahadiF/Edge-Voice-Assistant | WebRTC APM 双向参考处理：**缺失**；ASR 过期结果 epoch 丢弃：**待验证** |
| FunAudioLLM/CosyVoice | 零样本参考音频与流式模型输出：**缺失**；跨语言与自然语言指令控制：**缺失**；音频生成器按 stream 参数返回：**部分**；CosyVoice2/3 持续流式文本输入：**缺失** |
| FunAudioLLM/SenseVoice | ONNX 语音识别推理封装：**已具备**；音频数据加载与特征提取：**部分** |
| ggml-org/llama.cpp | 本地模型服务上下文：**非同类** |
| hexgrad/kokoro | 返回文本、音素和音频分段：**部分**；文本管线按块迭代输出：**部分** |
| huggingface/speech-to-speech | 带时间戳播放参考的 AEC：**缺失**；音频时间轴口型事件：**部分**；流式说话人分离与跨话段跟踪：**缺失** |
| k2-fsa/sherpa-onnx | 在线识别端点检测与 token 时间戳：**缺失**；离线 TTS 生成回调：**已具备** |
| kyutai-labs/moshi | 有状态语言模型逐步音频 token 生成：**缺失**；模型 TTS 生成：**非同类** |
| liampetti/fulloch | 浏览器 AEC 请求及播放取消：**已具备**；无界面卫星端指数退避重连：**待验证** |
| lipku/LiveTalking | 音频视频时钟：**非同类**；音频特征队列：**非同类** |
| Live2D/CubismWebMotionSyncComponents | 模型专属音频→形状映射和后处理配置：**部分**；官方CRI分析、混合和平滑接口：**待验证** |
| livekit/agents | 自适应打断和误打断恢复：**缺失**；播放完成位置和同步文本：**缺失** |
| modelscope/FunASR | Paraformer 缓存分块及最终块标记：**缺失**；统一模型生成接口：**部分** |
| moeru-ai/airi | 元音音频分析：**已具备**；流式语音调度：**部分**；表情队列：**部分** |
| mrxz/wlipsync | 播放音频的 MFCC 分类与时间平滑：**已具备**；声音专属校准模板：**已具备**；预计算二进制 profile：**缺失** |
| ollama/ollama | 本地聊天与生成服务：**非同类** |
| Open-LLM-VTuber/Open-LLM-VTuber | 中断已听文本：**部分**；客户端中断消息：**部分** |
| Open-LLM-VTuber/Open-LLM-VTuber-Web | 音频任务队列：**已具备**；音频与口型停止：**已具备**；表情映射：**部分**；播放完成回执及中断文本：**部分** |
| openai/whisper | 词级时间戳对齐：**缺失**；窗口式多语言转写：**部分** |
| OpenBMB/MiniCPM-o | 流式输入与生成：**部分**；说话时钟：**待验证**；4.5 全双工声明：**待验证** |
| OpenBMB/VoxCPM | 模型生成步骤输出音频块：**部分**；参考提示缓存条件生成：**缺失** |
| pipecat-ai/pipecat | 原生阶段指标和句子聚合：**已具备**；空用户轮次恢复：**部分** |
| pipecat-ai/pipecat-client-web | 打断回调与事件：**已具备**；类型化指标消息：**已具备** |
| pipecat-ai/pipecat-client-web-transports | 打断消息处理：**已具备**；重连失败事件：**部分** |
| pipecat-ai/pipecat-examples | 并行流水线与 VAD：**非同类**；框架指标启用示例：**已具备** |
| pipecat-ai/smart-turn | 音频轮次结束预测：**已具备**；延迟与吞吐基准：**部分** |
| QwenLM/Qwen3-ASR | 状态化 PCM 分块识别：**缺失**；可选强制对齐：**缺失** |
| QwenLM/Qwen3-Omni | 音频输入多模态推理示例：**缺失**；自动设备映射与多模态处理：**待验证** |
| QwenLM/Qwen3-TTS | 参考音频克隆：**缺失**；文本描述设计音色：**缺失**；非流式文本接口的模拟设置：**非同类** |
| QwenLM/Qwen3.5 | 模型系列介绍与规模选择：**非同类** |
| snakers4/silero-vad | 状态化流式 VAD：**已具备**；离线语音区间时间戳：**部分** |
| suzuran0y/Live2D-LLM-Chat | WAV 输入校验：**已具备**；ASR worker 分离：**已具备**；结构化 worker 帧：**部分** |
| SYSTRAN/faster-whisper | 分段 Whisper 转写和词级时间戳：**部分**；转写时语音活动过滤：**部分** |
| TacoTakumi/HermesConsole | 物理设备 AEC 验收门槛：**缺失**；可重复打断语音样本：**部分** |
| TacoTakumi/VoiceManager | 增量 STT 中间结果与最终结果：**缺失**；客户端播放边界与麦克风样本时钟：**缺失**；有界队列与溢出丢弃：**待验证** |
| THUDM/GLM-4-Voice | 语言模型音频 token 流输出：**缺失**；语音 flow 流推理：**部分** |
| TMElyralab/MuseTalk | 音频特征与帧切片：**非同类**；视频帧输出：**非同类** |
| vllm-project/vllm | 异步模型请求与增量生成：**非同类** |
| vllm-project/vllm-omni | 双工客户端发送 PCM 流：**部分**；异步多模态生成：**缺失** |
| wwbin2017/bailing | FunASR 识别后端接口：**部分**；Kokoro 合成后端：**缺失** |

## 逐项目依据、价值与成本

### akkoaya/EvatarFramework

固定源码：[63b414c9633d](https://github.com/akkoaya/EvatarFramework/tree/63b414c9633d55234949b3754686dcc7acebea60)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

当前对照：Pipecat 会话；已实现单人声纹向量合并与校验。

**多样本声纹模板归一化与匹配 — 部分**

上游价值：多样本可降低单次录音的偶然影响；上游还支持多用户索引。

当前差距 / 采用成本：本项目已采用单人模板思路；多用户需要身份管理、阈值和隐私设计。

- [src/evatar_framework/providers/speaker/store.py:131](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/providers/speaker/store.py#L131)：归一化各样本、合并均值并存储；143 行按相似度匹配。

**原生客户端重连与退避配置 — 已具备**

上游价值：连接中断后的自动重试和可观测性。

当前差距 / 采用成本：当前web/src/reconnect.ts已有1—30秒指数退避，同会话重连已有受控验收；上游原生设备配置不能证明在途音频/时钟完整恢复。

- [src/evatar_framework/core/config.py:73](https://github.com/akkoaya/EvatarFramework/blob/63b414c9633d55234949b3754686dcc7acebea60/src/evatar_framework/core/config.py#L73)：配置初始及最大重连间隔；native_soak.py 的 67 行使用这些参数。

重点核对：需要时才扩展多用户索引；用户当前需求是只回应本人；反复网络抖动后的在途音频及播放状态恢复仍待实测。

校正 / 限制：旧报告已补声纹模板机制；重连配置不是完整端到端恢复证明。

### aryeo0908/whisper-loop

固定源码：[810e1d5d4105](https://github.com/aryeo0908/whisper-loop/tree/810e1d5d410557038d1379cd709e3fb979422bde)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

当前对照：Pipecat 取消传播、按句聚合及阶段指标；STT 为分段请求。

**独立轮次任务取消与通知 — 已具备**

上游价值：隔离轮次取消并明确客户端事件。

当前差距 / 采用成本：需比较 Pipecat 帧取消及客户端队列清空，增加故障和背压测试。 当前已经有同类机制，不把其存在计作当前缺失；实际鲁棒性仍须测试。

- [server/app/pipeline.py:106](https://github.com/aryeo0908/whisper-loop/blob/810e1d5d410557038d1379cd709e3fb979422bde/server/app/pipeline.py#L106)：插话取消当前 asyncio 任务并发送被打断轮次通知。

**流式 LLM 按句入队 TTS — 已具备**

上游价值：在回复结束前开始句子合成。

当前差距 / 采用成本：当前已有原生句子聚合及增量 PCM；中文标点与延迟需继续实测。

- [server/app/pipeline.py:173](https://github.com/aryeo0908/whisper-loop/blob/810e1d5d410557038d1379cd709e3fb979422bde/server/app/pipeline.py#L173)：累积 token 并将完整句子发送到合成队列。

重点核对：端到端播放确认尚未具备。

校正 / 限制：逐帧 VAD 不代表流式增量识别；其代码先汇集话段再识别。

### Code-Amadeus/Amadeus

固定源码：[9ef43dda7cc2](https://github.com/Code-Amadeus/Amadeus/tree/9ef43dda7cc2ac177601889478116caabe562e88)。源码许可记录：AGPL-3.0；模型、素材、SDK/Core和服务许可另核。

当前对照：最终识别后确认打断、中文附和过滤、浏览器请求 AEC。

**基于音量及回声候选的插话判断 — 部分**

上游价值：可探索在播放时更早区分人声和自回声。

当前差距 / 采用成本：启发式并非声学 AEC；需中文、双讲误判实验及 AGPL 许可评估。

- [asr/barge_in_detector.py:271](https://github.com/Code-Amadeus/Amadeus/blob/9ef43dda7cc2ac177601889478116caabe562e88/asr/barge_in_detector.py#L271)：检测候选并调用自回声判断以抑制扬声器回声触发。

**最终音频消费接口 — 已具备**

上游价值：与当前分段识别同类，不能据此证明真流式 STT。

当前差距 / 采用成本：无需替换现有识别链。

- [asr/manager.py:159](https://github.com/Code-Amadeus/Amadeus/blob/9ef43dda7cc2ac177601889478116caabe562e88/asr/manager.py#L159)：consume 接收最终音频片段。

重点核对：真实环境自回声误打断效果未测。

校正 / 限制：旧报告中的回声启发式不应称为已验证 AEC。

### CoreWorxLab/local-livekit-plugins

固定源码：[598d56d5a234](https://github.com/CoreWorxLab/local-livekit-plugins/tree/598d56d5a234e81438cd293927d6917b3633c7fb)。源码许可记录：源码 MIT；模型单独核查；模型、素材、SDK/Core和服务许可另核。

**Piper ChunkedStream 封装分块音频 — 部分**

上游价值：可用标准 LiveKit 音频流接口；当前已有 VITS 回调 PCM

当前差距 / 采用成本：需要引入 LiveKit 生命周期并验证中文 Piper 音质

- [src/local_livekit_plugins/piper_tts.py:55](https://github.com/CoreWorxLab/local-livekit-plugins/blob/598d56d5a234e81438cd293927d6917b3633c7fb/src/local_livekit_plugins/piper_tts.py#L55)：LiveKit 分块 TTS 流

**faster-whisper STT 适配器 — 已具备**

上游价值：本地识别可替换；当前已有 faster-whisper 后备

当前差距 / 采用成本：框架适配与模型许可核查

- [src/local_livekit_plugins/faster_whisper_stt.py:50](https://github.com/CoreWorxLab/local-livekit-plugins/blob/598d56d5a234e81438cd293927d6917b3633c7fb/src/local_livekit_plugins/faster_whisper_stt.py#L50)：本地 STT 服务类

校正 / 限制：分块 TTS 不等于流式文本输入，当前同样已有音频增量输出。

### datascale-ai/opentalking

固定源码：[8c739a5a6f11](https://github.com/datascale-ai/opentalking/tree/8c739a5a6f114daf71aeace832a668c3ad60f536)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

当前对照：本地 Pipecat 会话和 Live2D；无 Redis 会话队列。

**Redis 会话状态和任务排队 — 非同类**

上游价值：适合服务进程解耦与多会话部署。

当前差距 / 采用成本：引入 Redis 和跨服务一致性，对单机伴侣可能增加复杂度。

- [apps/api/services/session_service.py:29](https://github.com/datascale-ai/opentalking/blob/8c739a5a6f114daf71aeace832a668c3ad60f536/apps/api/services/session_service.py#L29)：向 Redis 推送任务，170 行读取和更新会话状态。

**上传音频前明确打断 — 部分**

上游价值：明确处理新语音与在播任务的冲突。

当前差距 / 采用成本：协议和媒体栈不同，需先核对现有取消和播放完成语义。

- [apps/api/services/session_service.py:255](https://github.com/datascale-ai/opentalking/blob/8c739a5a6f114daf71aeace832a668c3ad60f536/apps/api/services/session_service.py#L255)：发起上传 PCM 语音前调用 interrupt。

重点核对：多进程会话队列非当前单机场景必要条件。

校正 / 限制：排队能力不证明实时延迟或播放 ACK。

### electron/electron

固定源码：[6d9ec3d7433a](https://github.com/electron/electron/tree/6d9ec3d7433a01587615a23881ed64ed94e1fa6d)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

**桌面媒体权限策略 — 非同类**

上游价值：桌面封装可集中控制授权

当前差距 / 采用成本：引入 Electron、桌面打包与权限维护

- [shell/browser/electron_permission_manager.cc:117](https://github.com/electron/electron/blob/6d9ec3d7433a01587615a23881ed64ed94e1fa6d/shell/browser/electron_permission_manager.cc#L117)：设置权限请求处理器

**来源权限检查 — 非同类**

上游价值：适合桌面容器权限治理

当前差距 / 采用成本：需评估浏览器与桌面策略一致性

- [shell/browser/electron_permission_manager.cc:350](https://github.com/electron/electron/blob/6d9ec3d7433a01587615a23881ed64ed94e1fa6d/shell/browser/electron_permission_manager.cc#L350)：按来源检查请求权限

校正 / 限制：本次依据当前 5c5ce43 能力重审；差异不表示统一性能优势。

### FahadiF/Edge-Voice-Assistant

固定源码：[6ba8a2d7f715](https://github.com/FahadiF/Edge-Voice-Assistant/tree/6ba8a2d7f715e967ecc2f75539f553fb37198ee6)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

当前对照：浏览器请求 AEC；后端无同步实际扬声器参考；已有 TTS 流和取消。

**WebRTC APM 双向参考处理 — 缺失**

上游价值：设备同步正确时具备声学回声消除路径。

当前差距 / 采用成本：必须取得实际播放参考、时钟对齐并验证双讲；本机未证明效果。

- [src/eva/audio/processor.py:93](https://github.com/FahadiF/Edge-Voice-Assistant/blob/6ba8a2d7f715e967ecc2f75539f553fb37198ee6/src/eva/audio/processor.py#L93)：分别处理采集和播放参考帧，支持流延迟设置。

**ASR 过期结果 epoch 丢弃 — 待验证**

上游价值：取消后避免旧识别结果污染新轮次。

当前差距 / 采用成本：需对 Pipecat 取消与本地推理不可中断情形设计实测。

- [src/eva/asr/base.py:5](https://github.com/FahadiF/Edge-Voice-Assistant/blob/6ba8a2d7f715e967ecc2f75539f553fb37198ee6/src/eva/asr/base.py#L5)：不可中断的解码通过 epoch 丢弃过期结果。

重点核对：设备参考同步 AEC；旧 ASR 结果跨轮隔离的系统级实测。

校正 / 限制：本地 APM 合成实验不是产品真实双讲验收。

### FunAudioLLM/CosyVoice

固定源码：[074ca6dc9e80](https://github.com/FunAudioLLM/CosyVoice/tree/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc)。源码许可记录：源码 Apache-2.0；权重按具体模型卡；模型、素材、SDK/Core和服务许可另核。

**零样本参考音频与流式模型输出 — 缺失**

上游价值：无需固定说话人即可控制音色，同时分块输出

当前差距 / 采用成本：需权重许可、参考音频治理及本机性能和音质评测

- [cosyvoice/cli/cosyvoice.py:91](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L91)：inference_zero_shot 接受参考音频及 stream 参数

**跨语言与自然语言指令控制 — 缺失**

上游价值：跨语言音色保持与表达风格控制

当前差距 / 采用成本：较重 PyTorch 依赖，中文效果及 CPU/NPU 待测

- [cosyvoice/cli/cosyvoice.py:105](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L105)：跨语言推理入口

**音频生成器按 stream 参数返回 — 部分**

上游价值：更早输出音频；当前 VITS 已有回调分段

当前差距 / 采用成本：须比较首块延迟与打断恢复；这里不证明文本输入本身流式

- [cosyvoice/cli/cosyvoice.py:85](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L85)：循环返回模型 TTS 输出

**CosyVoice2/3 持续流式文本输入 — 缺失**

上游价值：同一合成会话可持续接收文本生成器，交错生成语音token，超出当前“整句text请求→callback PCM”的能力。

当前差距 / 采用成本：源码明确仅CosyVoice2/3且该路径不支持vLLM；需适配生成器、取消、缓存、中文音质和本机资源，不能保证在当前CPU更快。

- [cosyvoice/cli/frontend.py:79](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/frontend.py#L79)：输入为Generator时返回增量token生成器
- [cosyvoice/cli/model.py:104](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/model.py#L104)：Generator路由到inference_bistream并检查版本与vLLM限制
- [cosyvoice/llm/llm.py:552](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/llm/llm.py#L552)：实现接收Generator的inference_bistream

重点核对：参考音色克隆；风格指令；同一会话增量文本输入，需CosyVoice2/3且非vLLM路径。

校正 / 限制：VITS 已有原生 callback，不应把音频分块当作独有优势。

### FunAudioLLM/SenseVoice

固定源码：[586bbdb2b052](https://github.com/FunAudioLLM/SenseVoice/tree/586bbdb2b052f4fe19322581825228b6810a9fb3)。源码许可记录：源码 MIT；模型权重单独核查；模型、素材、SDK/Core和服务许可另核。

**ONNX 语音识别推理封装 — 已具备**

上游价值：当前已通过 sherpa-onnx 在 CPU 完成中文分段最终识别

当前差距 / 采用成本：现有模型和运行时继续维护

- [utils/model_bin.py:139](https://github.com/FunAudioLLM/SenseVoice/blob/586bbdb2b052f4fe19322581825228b6810a9fb3/utils/model_bin.py#L139)：特征推理入口

**音频数据加载与特征提取 — 部分**

上游价值：可复用参考前处理进行精度对照

当前差距 / 采用成本：不能据此推断实时部分结果或 NPU 加速

- [utils/model_bin.py:101](https://github.com/FunAudioLLM/SenseVoice/blob/586bbdb2b052f4fe19322581825228b6810a9fb3/utils/model_bin.py#L101)：音频加载及后续特征提取

校正 / 限制：源码仓库许可证是 MIT，具体模型权重许可独立核查；本机运行是 CPU。

### ggml-org/llama.cpp

固定源码：[10d4846a572a](https://github.com/ggml-org/llama.cpp/tree/10d4846a572aebf21c0482d140b00e74c0f1ad20)。源码许可记录：源码 MIT；模型许可独立；模型、素材、SDK/Core和服务许可另核。

**本地模型服务上下文 — 非同类**

上游价值：可选本地语言模型推理，降低对云端依赖

当前差距 / 采用成本：部署兼容 GGUF 模型，需测中文效果、设备性能和许可

- [tools/server/server-context.cpp:1019](https://github.com/ggml-org/llama.cpp/blob/10d4846a572aebf21c0482d140b00e74c0f1ad20/tools/server/server-context.cpp#L1019)：server_context_impl 服务实现

重点核对：可选本地对话模型。

校正 / 限制：该服务本身不是可直接替代当前 ASR 和 TTS 的语音管线。

### hexgrad/kokoro

固定源码：[dfb907a02bba](https://github.com/hexgrad/kokoro/tree/dfb907a02bba8152ca444717ca5d78747ccb4bec)。源码许可记录：源码 Apache-2.0；权重和音色许可单独核查；模型、素材、SDK/Core和服务许可另核。

**返回文本、音素和音频分段 — 部分**

上游价值：能获取音素文本供调试；当前也可分段输出音频

当前差距 / 采用成本：中文前端、模型与音质需实测；音素字符串不等于时间戳

- [kokoro/pipeline.py:292](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py#L292)：返回 graphemes、phonemes 和 output

**文本管线按块迭代输出 — 部分**

上游价值：方便段落音频增量处理

当前差距 / 采用成本：不能据此认定是真正持续流式文本输入或声学逐帧生成

- [kokoro/pipeline.py:361](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py#L361)：管线调用入口

重点核对：可用的音素序列。

校正 / 限制：音素输出不提供已验证的音素起止时间，不能直接用于精确口型同步。

### huggingface/speech-to-speech

固定源码：[5108a3eacea8](https://github.com/huggingface/speech-to-speech/tree/5108a3eacea81298a9dc62d5179abcacfb8119f1)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

当前对照：本地 MFCC 口型模板、单人声纹、浏览器 AEC 请求，后端无播放参考。

**带时间戳播放参考的 AEC — 缺失**

上游价值：提供实际采集和播放时间对齐的回声消除架构。

当前差距 / 采用成本：需设备时间戳、播放参考及双讲测试；浏览器后端当前不具备。

- [src/speech_to_speech/api/openai_realtime/echo_canceller.py:45](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/api/openai_realtime/echo_canceller.py#L45)：按播放时间排队参考帧，60 行按采集时间处理。

**音频时间轴口型事件 — 部分**

上游价值：可将预测口型与音频区间显式同步。

当前差距 / 采用成本：默认音素识别模型为英文（arguments_classes/w2v_stv_arguments.py:11），中文准确性与现有 MFCC 模板需对比，增加模型和时间同步成本。 此实现缓冲约0.5秒再推断，flush在音频转发前执行，可能引入额外等待；精细口型与首音延迟需权衡。

- [src/speech_to_speech/pipeline/visemes.py:6](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/pipeline/visemes.py#L6)：定义音频时间轴口型区间；api/openai_realtime/visemes.py:10 定义事件。
- [src/speech_to_speech/STV/w2v_stv_handler.py:38](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/STV/w2v_stv_handler.py#L38)：MIN_AUDIO_LENGTH为0.5秒
- [src/speech_to_speech/STV/w2v_stv_handler.py:128](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/STV/w2v_stv_handler.py#L128)：flush先推断口型再发送缓冲音频
- [src/speech_to_speech/arguments_classes/w2v_stv_arguments.py:11](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/arguments_classes/w2v_stv_arguments.py#L11)：默认音素检查点是英文

**流式说话人分离与跨话段跟踪 — 缺失**

上游价值：可标记多位说话人的活动区间。

当前差距 / 采用成本：需 Nemotron 模型与支持的 Transformers；上游警告 CPU 持续语音可能跟不上。说话人分离不等于本人声纹验证。

- [src/speech_to_speech/diarization/streaming.py:28](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/diarization/streaming.py#L28)：流式处理音频并追踪活动说话人，156 行保留跨话段缓存。

重点核对：同步设备参考 AEC；多说话人在线分离；经中文验证的音素时间口型事件。

校正 / 限制：旧报告遗漏口型事件与流式说话人分离；默认口型识别模型是英文。

### k2-fsa/sherpa-onnx

固定源码：[079a6f05d05a](https://github.com/k2-fsa/sherpa-onnx/tree/079a6f05d05a18bc6e993704a557c2f62c7a17a5)。源码许可记录：源码 Apache-2.0；每个模型许可单独核查；模型、素材、SDK/Core和服务许可另核。

**在线识别端点检测与 token 时间戳 — 缺失**

上游价值：可得到流式部分识别及端点判断，时间戳可用于文本对齐

当前差距 / 采用成本：需挑选准确的在线模型并测短语、数字、中文麦克风及打断策略

- [sherpa-onnx/python/sherpa_onnx/online_recognizer.py:1193](https://github.com/k2-fsa/sherpa-onnx/blob/079a6f05d05a18bc6e993704a557c2f62c7a17a5/sherpa-onnx/python/sherpa_onnx/online_recognizer.py#L1193)：is_endpoint 及流重置接口

**离线 TTS 生成回调 — 已具备**

上游价值：当前 VITS 已通过回调输出 PCM，降低等待完整 WAV 的首音时间

当前差距 / 采用成本：当前是 CPU 分段回调，非连续声学生成或流式文本输入

- [sherpa-onnx/python/csrc/offline-tts.cc:126](https://github.com/k2-fsa/sherpa-onnx/blob/079a6f05d05a18bc6e993704a557c2f62c7a17a5/sherpa-onnx/python/csrc/offline-tts.cc#L126)：生成时回调音频样本和进度

重点核对：可靠的在线部分识别和模型端点。

校正 / 限制：在线实验曾误识数字，不能替换 SenseVoice 最终结果；不宣称 NPU。

### kyutai-labs/moshi

固定源码：[e6a55d2722a6](https://github.com/kyutai-labs/moshi/tree/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362)。源码许可记录：源码 Apache-2.0 或 MIT；权重许可另核查；模型、素材、SDK/Core和服务许可另核。

**有状态语言模型逐步音频 token 生成 — 缺失**

上游价值：探索语音到语音交互和语音上下文建模

当前差距 / 采用成本：模型资源、中文质量和真实全双工延迟须实测

- [moshi/moshi/models/lm.py:786](https://github.com/kyutai-labs/moshi/blob/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/moshi/moshi/models/lm.py#L786)：流式模型 step

**模型 TTS 生成 — 非同类**

上游价值：可作为端到端架构研究参考

当前差距 / 采用成本：需要适配不同音频 token 和生命周期，不推断本机 NPU 支持

- [moshi/moshi/models/tts.py:497](https://github.com/kyutai-labs/moshi/blob/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/moshi/moshi/models/tts.py#L497)：TTS generate 入口

重点核对：端到端语音 token 对话。

校正 / 限制：代码逐步生成不证明本机中文全双工效果或性能。

### liampetti/fulloch

固定源码：[c7b08e736397](https://github.com/liampetti/fulloch/tree/c7b08e736397e2066b13c37fbea2e833e25cd5f0)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

当前对照：浏览器管理麦克风和 PCM 播放，官方 WebSocket 传输；物理 AEC 未测。

**浏览器 AEC 请求及播放取消 — 已具备**

上游价值：浏览器侧处理回声并及时清空计划播放。

当前差距 / 采用成本：本项目已有同类请求和中断；不同浏览器实际声学效果须实测。 当前已经有同类机制，不把其存在计作当前缺失；实际鲁棒性仍须测试。

- [server/static/js/browser-satellite.js:166](https://github.com/liampetti/fulloch/blob/c7b08e736397e2066b13c37fbea2e833e25cd5f0/server/static/js/browser-satellite.js#L166)：设置 echoCancellation 和 noiseSuppression；170 行起取消已安排播放。

**无界面卫星端指数退避重连 — 待验证**

上游价值：设备网络断开后可恢复连接。

当前差距 / 采用成本：当前官方浏览器传输的恢复及对话状态一致性需测试；不应创建第二设备所有者。

- [clients/headless/satellite.py:216](https://github.com/liampetti/fulloch/blob/c7b08e736397e2066b13c37fbea2e833e25cd5f0/clients/headless/satellite.py#L216)：连接失败后退避重试并限制最大间隔。

重点核对：断线后会话恢复验收；真实设备 AEC 测量。

校正 / 限制：旧报告缺少卫星重连细节；播放状态不等同已听文本 ACK。

### lipku/LiveTalking

固定源码：[c7269433a2b6](https://github.com/lipku/LiveTalking/tree/c7269433a2b6ecebcd9342445d2ecc882c98b0da)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

**音频视频时钟 — 非同类**

上游价值：适用于 WebRTC 像素视频音画对齐

当前差距 / 采用成本：需引入视频传输与媒体时钟，本机延迟未测

- [server/webrtc.py:69](https://github.com/lipku/LiveTalking/blob/c7269433a2b6ecebcd9342445d2ecc882c98b0da/server/webrtc.py#L69)：按音视频时间基递增时间戳并等待帧时刻

**音频特征队列 — 非同类**

上游价值：服务端特征可驱动视频头像

当前差距 / 采用成本：需模型、算力和视频头像链路

- [avatars/audio_features/hubert.py:24](https://github.com/lipku/LiveTalking/blob/c7269433a2b6ecebcd9342445d2ecc882c98b0da/avatars/audio_features/hubert.py#L24)：执行音频特征步骤并排队音频帧

校正 / 限制：本次依据当前 5c5ce43 能力重审；差异不表示统一性能优势。

### Live2D/CubismWebMotionSyncComponents

固定源码：[9e7a356fb551](https://github.com/Live2D/CubismWebMotionSyncComponents/tree/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4)。源码许可记录：Live2D Open Software；Core/SDK 另受 Proprietary/SDK 条款；模型、素材、SDK/Core和服务许可另核。

**模型专属音频→形状映射和后处理配置 — 部分**

上游价值：以motionsync3配置表达多个音频类别到多个Cubism参数的权重、缩放、阻尼和平滑，便于不同角色独立调校。

当前差距 / 采用成本：我们已有五个嘴参数映射及范围检查，但映射公式写在adapter.ts；当前皮肤没有motionsync3，需制作并验证映射。

- [Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json:17](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json#L17)：配置嘴参数及范围和平滑
- [Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json:117](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json#L117)：音频类别与模型形状映射
- [Framework/src/cubismmotionsyncdata.ts:140](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Framework/src/cubismmotionsyncdata.ts#L140)：按模型配置建立引擎映射列表

**官方CRI分析、混合和平滑接口 — 待验证**

上游价值：提供专门的音频分析与形状后处理接口，可作为替代声学分析器进行对照。

当前差距 / 采用成本：仓库不含Core；需另取Core/SDK、接受独立许可并适配模型。仅凭接口不能断言中文口型比wLipSync准确或延迟更低。

- [Framework/src/cubismmotionsyncprocessorcri.ts:25](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/Framework/src/cubismmotionsyncprocessorcri.ts#L25)：Analyze接收blendRatio/smoothing/audioLevelEffectRatio
- [README.md:33](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/README.md#L33)：Core不在本仓库
- [LICENSE.md:1](https://github.com/Live2D/CubismWebMotionSyncComponents/blob/9e7a356fb55148ea20f6e43f8f0b63f36bcc2be4/LICENSE.md#L1)：组件、SDK和Core的独立许可条件

重点核对：角色映射配置化；官方引擎的中文/延迟A/B仍未完成。

校正 / 限制：并非完整MIT开源依赖；源码组件与闭源Core/SDK/素材许可分开，不能把接口存在当作准确度优势。

### livekit/agents

固定源码：[652eee4ea809](https://github.com/livekit/agents/tree/652eee4ea809ee524fb0ada2383d06eebc3d93a0)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

当前对照：最终转写确认后打断，附和过滤；无客户端播放 ACK。

**自适应打断和误打断恢复 — 缺失**

上游价值：暂停后识别误打断并恢复播放，可能减少误停。

当前差距 / 采用成本：需要对应音频会话与中文噪声测试；替换 Pipecat 需要另一运行栈。 恢复路径还要求resume_false_interruption配置、timeout及输出audio.can_pause，不能假设所有输出后端可续播。

- [livekit-agents/livekit/agents/voice/agent_activity.py:5044](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/livekit-agents/livekit/agents/voice/agent_activity.py#L5044)：可启用误打断后恢复；agent.py:113 支持 adaptive 或 VAD 模式。

**播放完成位置和同步文本 — 缺失**

上游价值：可基于传输提供的播放状态改进被打断文本历史。

当前差距 / 采用成本：能力取决于具体输出实现，不等同证明物理扬声器已被听见；需客户端协议支持。

- [livekit-agents/livekit/agents/voice/agent_activity.py:3400](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/livekit-agents/livekit/agents/voice/agent_activity.py#L3400)：等待 playout 并读取播放位置及同步转写。

重点核对：已播放文本确认；经验证的误打断暂停恢复。

校正 / 限制：旧报告遗漏播放位置及同步文本；不能默认所有传输均提供设备级 ACK。

### modelscope/FunASR

固定源码：[fd1d4aa655ef](https://github.com/modelscope/FunASR/tree/fd1d4aa655effca86dc03b70a09db7e4e6409a10)。源码许可记录：源码 MIT；具体模型许可另核查；模型、素材、SDK/Core和服务许可另核。

**Paraformer 缓存分块及最终块标记 — 缺失**

上游价值：可在句尾前输出识别结果，支持更早的语义打断

当前差距 / 采用成本：需评估假打断、中文识别准确率及设备开销

- [funasr/models/paraformer_streaming/model.py:47](https://github.com/modelscope/FunASR/blob/fd1d4aa655effca86dc03b70a09db7e4e6409a10/funasr/models/paraformer_streaming/model.py#L47)：cache、chunk_size 和 is_final

**统一模型生成接口 — 部分**

上游价值：便于比较多种中文识别模型

当前差距 / 采用成本：新模型及 PyTorch 依赖较重，模型各自许可需核查

- [funasr/auto/auto_model.py:841](https://github.com/modelscope/FunASR/blob/fd1d4aa655effca86dc03b70a09db7e4e6409a10/funasr/auto/auto_model.py#L841)：AutoModel generate

重点核对：真实流式部分识别。

校正 / 限制：应继续保留 SenseVoice 最终识别，直到真实音频对比证明替换质量。

### moeru-ai/airi

固定源码：[11b8989f6dd7](https://github.com/moeru-ai/airi/tree/11b8989f6dd7f840cf6b15ce59e367656fb11ac6)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

**元音音频分析 — 已具备**

上游价值：按频谱驱动嘴型并在静音闭嘴

当前差距 / 采用成本：已有 wLipSync 与本地 VITS profile，泛化仍待验证

- [packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts:101](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts#L101)：选择胜出元音并按音量门控、平滑；并非完整概率分布

**流式语音调度 — 部分**

上游价值：可增量提交文本、组织分句和取消；不保证音频在句末前输出

当前差距 / 采用成本：当前本地 VITS 按句生成；需验证 provider 的事件与音频分块方式，不能假定消除句级等待。

- [packages/stage-ui/src/libs/speech/streaming-pipeline.ts:91](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/stage-ui/src/libs/speech/streaming-pipeline.ts#L91)：允许增量 appendText 输入
- [packages/stage-ui/src/libs/speech/streaming-pipeline.ts:358](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/stage-ui/src/libs/speech/streaming-pipeline.ts#L358)：默认在 sentence.end 合并并解码；bufferEntireSession 时等待整个会话

**表情队列 — 部分**

上游价值：可按输出任务组织表情

当前差距 / 采用成本：当前以 TTS 文本关键词近似，需播放时间对齐

- [packages/stage-ui/src/composables/queues.ts:60](https://github.com/moeru-ai/airi/blob/11b8989f6dd7f840cf6b15ce59e367656fb11ac6/packages/stage-ui/src/composables/queues.ts#L60)：将解析出的情绪加入队列

重点核对：流式语音调度；表情队列。

校正 / 限制：当前已有本地 VITS profile 和选择机制；泛化仍待验证。；上游权重采用胜出类别和平滑，不应描述为完整元音概率；wLipSync 1.3.1 MFCC 输出存在已测得的上游内存更新风险，需结合主审查。

### mrxz/wlipsync

固定源码：[177f3ac4095d](https://github.com/mrxz/wlipsync/tree/177f3ac4095dbad81be0a800a8c6f975abe4ae04)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

**播放音频的 MFCC 分类与时间平滑 — 已具备**

上游价值：在同等音量下仍可产生不同元音嘴形，且不依赖文本猜测。

当前差距 / 采用成本：当前已直接依赖1.3.1；其 worklet 发送胜出类别，前端再平滑成权重，不是原始分类置信度或完整音素概率。

- [src/main.c:123](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/src/main.c#L123)：从实际音频提取特征并评分分类
- [www/audio-processor.js:106](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/www/audio-processor.js#L106)：向主线程发送胜出类别和时间戳
- [www/audio-node.ts:85](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/www/audio-node.ts#L85)：将胜出类别映射为目标并平滑

**声音专属校准模板 — 已具备**

上游价值：模板可随声线更换，而非将某个说话人的样例当作通用中文模型。

当前差距 / 采用成本：本项目已有本地 VITS 模板和选择；E/O/U仍混淆。上游官方不含创建器，建议 Unity uLipSync 校准，本项目离线工具属于额外适配。

- [README.md:54](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/README.md#L54)：校准说明与外部 Unity 创建流程
- [www/types.ts:5](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/www/types.ts#L5)：每类可存 MFCC 校准数据

**预计算二进制 profile — 缺失**

上游价值：减少原始模板传输体积和初始化预计算。

当前差距 / 采用成本：当前两个模板作为JSON进入前端包；这是体积/初始化优化，不能提高发音分类准确率，优先级低于修复特征和校准。

- [www/parse.ts:10](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/www/parse.ts#L10)：解析预计算的二进制校准文件
- [tools/json2bin.js:17](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/tools/json2bin.js#L17)：使用同一上游WASM转换profile

重点核对：上游导出特征写入范围风险；更可靠的中文声线校准与独立发音评测；可选预计算profile。

**依赖风险：六类配置只更新六个MFCC槽位**

固定源码存在类别数量与系数数量混用；独立实例化已安装1.3.1 WASM，以六类配置和12槽哨兵运行execute后，前六槽更新、后六槽保留哨兵。当前本地模板同样为六类，应优先核查。

这证明了写入范围问题，不能证明它是所有E/O/U混淆的唯一原因；本轮未修补依赖、未改生产内存。

复现：node scripts/probe_wlipsync_mfcc.cjs；固定诊断快照 docs/WLIPSYNC_MFCC_PROBE.json

- [src/main.c:180](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/src/main.c#L180)：写入mfccOut的循环上界为类别数量profile.mfccCount
- [src/score/calc_cosine_similarity_scores.c:16](https://github.com/mrxz/wlipsync/blob/177f3ac4095dbad81be0a800a8c6f975abe4ae04/src/score/calc_cosine_similarity_scores.c#L16)：评分遍历MFCC_NUM个系数，常量为12

校正 / 限制：已具备声学口型，不再是默认音量开合；当前平滑权重不等于完整类别概率。

### ollama/ollama

固定源码：[a6d33251620e](https://github.com/ollama/ollama/tree/a6d33251620eef7629c73b09e672f2df243eb363)。源码许可记录：源码 MIT；模型许可单独核查；模型、素材、SDK/Core和服务许可另核。

**本地聊天与生成服务 — 非同类**

上游价值：可选择本地对话模型，不必依赖云端文本推理

当前差距 / 采用成本：运行服务与模型；中文和本地硬件性能待测

- [server/routes.go:3019](https://github.com/ollama/ollama/blob/a6d33251620eef7629c73b09e672f2df243eb363/server/routes.go#L3019)：ChatHandler

重点核对：本地 LLM 备选。

校正 / 限制：不提供完整识别或语音合成；不推断 NPU 支持。

### Open-LLM-VTuber/Open-LLM-VTuber

固定源码：[992309c0aa19](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/tree/992309c0aa19845960228f880013d4685fde93b5)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

**中断已听文本 — 部分**

上游价值：中断后可修正代理上下文

当前差距 / 采用成本：当前框架输出历史未获浏览器逐字播放确认；上游文本精度也需验证

- [src/open_llm_vtuber/conversations/conversation_handler.py:116](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/conversation_handler.py#L116)：中断处理接收 heard_response 并传给代理和历史

**客户端中断消息 — 部分**

上游价值：协议显式传递已听片段

当前差距 / 采用成本：需要播放器回执和文本音频对齐，不能直接保证逐字精确

- [src/open_llm_vtuber/websocket_handler.py:369](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/websocket_handler.py#L369)：从中断消息读取文本并分派

重点核对：中断已听文本；客户端中断消息。

校正 / 限制：本次依据当前 5c5ce43 能力重审；差异不表示统一性能优势。

### Open-LLM-VTuber/Open-LLM-VTuber-Web

固定源码：[d176e7df2366](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/tree/d176e7df2366952e3bacbf12cf9a8b18a4315932)。源码许可记录：Open-LLM-VTuber License 1.0；模型、素材、SDK/Core和服务许可另核。

**音频任务队列 — 已具备**

上游价值：有序播放与清队

当前差距 / 采用成本：当前由 Pipecat 官方播放器管理队列，不应重复造队列

- [src/renderer/src/utils/task-queue.ts:4](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/utils/task-queue.ts#L4)：按异步任务维护队列

**音频与口型停止 — 已具备**

上游价值：中断时清理播放和角色状态

当前差距 / 采用成本：需保持当前中断及销毁回归测试

- [src/renderer/src/utils/audio-manager.ts:20](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/utils/audio-manager.ts#L20)：统一停止当前音频与口型

**表情映射 — 部分**

上游价值：模型特定表情可配置

当前差距 / 采用成本：当前关键词近似表情，需定义配置与播放时序

- [src/renderer/src/hooks/canvas/use-live2d-expression.ts:57](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/hooks/canvas/use-live2d-expression.ts#L57)：依据模型默认情绪配置处理表情

**播放完成回执及中断文本 — 部分**

上游价值：明确告知服务端前端队列播放完成，并可在中断时回传播放任务粒度文本

当前差距 / 采用成本：任务开始即累积整段文本，故中途打断可能领先已听音频；需要更细音频文本对齐，不能视为逐字回执。

- [src/renderer/src/hooks/utils/use-audio-task.ts:237](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/hooks/utils/use-audio-task.ts#L237)：后端合成完成且前端任务队列完成后发送 frontend-playback-complete
- [src/renderer/src/hooks/utils/use-audio-task.ts:85](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/hooks/utils/use-audio-task.ts#L85)：播放任务开始时累积整段展示文本
- [src/renderer/src/hooks/utils/use-interrupt.ts:27](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/hooks/utils/use-interrupt.ts#L27)：中断时发送累积 fullResponse

重点核对：表情映射；播放完成回执及中断文本。

校正 / 限制：本次依据当前 5c5ce43 能力重审；差异不表示统一性能优势。

### openai/whisper

固定源码：[86098128c0b4](https://github.com/openai/whisper/tree/86098128c0b4f24f0e2aa2994de830614b474227)。源码许可记录：源码 MIT；权重许可另核查；模型、素材、SDK/Core和服务许可另核。

**词级时间戳对齐 — 缺失**

上游价值：可将转写词与时间对齐

当前差距 / 采用成本：推理成本和中文词粒度需实测；并非 TTS 音素时间戳

- [whisper/timing.py:279](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/timing.py#L279)：add_word_timestamps

**窗口式多语言转写 — 部分**

上游价值：提供识别质量比较；当前有 faster-whisper 回退

当前差距 / 采用成本：非原生实时部分转写，需额外模型

- [whisper/transcribe.py:38](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/transcribe.py#L38)：transcribe 及分段处理

重点核对：可验证的识别时间对齐。

校正 / 限制：词级对齐不等同生成语音音素时间戳。

### OpenBMB/MiniCPM-o

固定源码：[47e1fa75b45b](https://github.com/OpenBMB/MiniCPM-o/tree/47e1fa75b45b8c122ca2a52150762bf6183f1c5e)。源码许可记录：Apache-2.0; model terms separate；模型、素材、SDK/Core和服务许可另核。

**流式输入与生成 — 部分**

上游价值：统一模型可处理连续音频和生成

当前差距 / 采用成本：当前 ASR/LLM/TTS 分离，需模型权重和设备评估

- [web_demos/minicpm-o_2.6/model_server.py:466](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/web_demos/minicpm-o_2.6/model_server.py#L466)：流式 prefill 音频；524 行调用 streaming_generate

**说话时钟 — 待验证**

上游价值：有助流式输出节奏控制

当前差距 / 采用成本：该代码不足以证明真实全双工，需重叠输入输出和打断实验

- [web_demos/minicpm-o_2.6/model_server.py:419](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/web_demos/minicpm-o_2.6/model_server.py#L419)：根据说话时间戳计算等待时间

**4.5 全双工声明 — 待验证**

上游价值：若实际实现符合文档，可同时建模输入输出并主动决策发言

当前差距 / 采用成本：4.5 文档和远端模型代码/权重声明不能由本地 2.6 demo 源码证实；需获取模型、核对代码许可并在本机测试重叠输入输出、打断和延迟。

- [docs/minicpm_o4dot5_zh.md:25](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/docs/minicpm_o4dot5_zh.md#L25)：文档描述在线全双工编解码和毫秒时间线时分复用
- [docs/minicpm_o4dot5_zh.md:1189](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/docs/minicpm_o4dot5_zh.md#L1189)：示例使用 trust_remote_code 加载模型，并在 1204 行调用 as_duplex
- [docs/api.md:284](https://github.com/OpenBMB/MiniCPM-o/blob/47e1fa75b45b8c122ca2a52150762bf6183f1c5e/docs/api.md#L284)：API 文档声明 4.5 支持全双工实时交互

重点核对：流式输入与生成；说话时钟；4.5 全双工声明。

校正 / 限制：4.5 文档明确声明全双工，示例通过 trust_remote_code 加载模型并调用 as_duplex；固定归档中的 2.6 demo 不能证明 4.5 的实现或本机效果。

### OpenBMB/VoxCPM

固定源码：[4b8dd4440d33](https://github.com/OpenBMB/VoxCPM/tree/4b8dd4440d33396b3f429201f8af0529b4d2c601)。源码许可记录：源码 Apache-2.0；模型权重单独核查；模型、素材、SDK/Core和服务许可另核。

**模型生成步骤输出音频块 — 部分**

上游价值：生成中逐块返回波形；当前 VITS 亦有 callback 音频分段

当前差距 / 采用成本：中文质量、速度、流式文本输入和硬件要求分别验证

- [src/voxcpm/core.py:204](https://github.com/OpenBMB/VoxCPM/blob/4b8dd4440d33396b3f429201f8af0529b4d2c601/src/voxcpm/core.py#L204)：generate_streaming

**参考提示缓存条件生成 — 缺失**

上游价值：参考音频条件和可复用提示特征

当前差距 / 采用成本：模型授权、参考音频管理和推理资源

- [src/voxcpm/core.py:312](https://github.com/OpenBMB/VoxCPM/blob/4b8dd4440d33396b3f429201f8af0529b4d2c601/src/voxcpm/core.py#L312)：使用 prompt cache 的生成路径

重点核对：音色克隆与提示缓存。

校正 / 限制：流式音频生成不证明支持任意追加文本或音素时间戳。

### pipecat-ai/pipecat

固定源码：[de8998789d56](https://github.com/pipecat-ai/pipecat/tree/de8998789d5690073ddd1dafcec7268839af8153)。源码许可记录：BSD-2-Clause；模型、素材、SDK/Core和服务许可另核。

当前对照：已用 1.15 帧流水线、SmartTurn、按句 TTS、RTVI metrics。

**原生阶段指标和句子聚合 — 已具备**

上游价值：复用框架指标和合成生命周期。

当前差距 / 采用成本：本项目已实测服务端 TTS 首 PCM 与处理时长；并非实际播放延迟。

- [src/pipecat/pipeline/worker.py:185](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/src/pipecat/pipeline/worker.py#L185)：可启用指标；services/tts_service.py:85 定义句子及 token 聚合。

**空用户轮次恢复 — 部分**

上游价值：空话段造成中断时可触发重新回应。

当前差距 / 采用成本：重新生成而非续播；默认提示假设已听上下文，当前无播放确认，不能宣称安全续播。

- [src/pipecat/processors/aggregators/llm_response_universal.py:1704](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/src/pipecat/processors/aggregators/llm_response_universal.py#L1704)：空轮次可插入提示并重新请求 LLM。

重点核对：播放 ACK 驱动的已听历史；真实误打断恢复验收。

校正 / 限制：已有默认 SmartTurn 和指标；空轮次重生成不能等同暂停续播。

### pipecat-ai/pipecat-client-web

固定源码：[c6a0a68c8d56](https://github.com/pipecat-ai/pipecat-client-web/tree/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79)。源码许可记录：BSD-2-Clause；模型、素材、SDK/Core和服务许可另核。

当前对照：已使用官方客户端与 RTVI 消息。

**打断回调与事件 — 已具备**

上游价值：应用可对服务端打断统一响应。

当前差距 / 采用成本：仍需验证播放清空时序；回调本身不是音频已听确认。

- [client-js/client/client.ts:480](https://github.com/pipecat-ai/pipecat-client-web/blob/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79/client-js/client/client.ts#L480)：调用 onBotInterrupted 并发出 BotInterrupted 事件。

**类型化指标消息 — 已具备**

上游价值：复用标准指标协议。

当前差距 / 采用成本：客户端展示与统计需要明确指标边界。

- [client-js/rtvi/messages.ts:47](https://github.com/pipecat-ai/pipecat-client-web/blob/c6a0a68c8d569db7be37a2c85201bf41b3d7cc79/client-js/rtvi/messages.ts#L47)：定义 RTVI metrics 消息类型。

重点核对：实际播放进度与文本确认。

校正 / 限制：客户端打断回调不能证明扬声器已播放。

### pipecat-ai/pipecat-client-web-transports

固定源码：[5cc10220f45e](https://github.com/pipecat-ai/pipecat-client-web-transports/tree/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f)。源码许可记录：BSD-2-Clause；模型、素材、SDK/Core和服务许可另核。

当前对照：使用官方 WebSocket 传输和音频播放管理。

**打断消息处理 — 已具备**

上游价值：统一传输层处理播放打断。

当前差距 / 采用成本：需跨设备验证缓冲音频及时清除。

- [transports/websocket-transport/src/webSocketTransport.ts:234](https://github.com/pipecat-ai/pipecat-client-web-transports/blob/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f/transports/websocket-transport/src/webSocketTransport.ts#L234)：解析传入的 interruption。

**重连失败事件 — 部分**

上游价值：向调用者暴露无法重连的状态。

当前差距 / 采用成本：并不证明断线后的会话与未播放音频自动恢复；需故障注入测试。

- [transports/websocket-transport/src/webSocketTransport.ts:252](https://github.com/pipecat-ai/pipecat-client-web-transports/blob/5cc10220f45e16d2a027beddcbe6b26eb5b8dd4f/transports/websocket-transport/src/webSocketTransport.ts#L252)：监听 reconnect-failed 并报告连接错误。

重点核对：断网恢复及会话一致性验证。

校正 / 限制：重连失败事件不是完整恢复保证。

### pipecat-ai/pipecat-examples

固定源码：[7875d02bc071](https://github.com/pipecat-ai/pipecat-examples/tree/7875d02bc0714d59528b0c8797664308af960a3a)。源码许可记录：BSD-2-Clause；模型、素材、SDK/Core和服务许可另核。

当前对照：单会话 Pipecat 串行语音流水线，指标已启用。

**并行流水线与 VAD — 非同类**

上游价值：示范多目标并行处理。

当前差距 / 采用成本：本项目单路中文对话没有直接需求；并行引入资源与顺序管理成本。

- [daily-multi-translation/bot.py:79](https://github.com/pipecat-ai/pipecat-examples/blob/7875d02bc0714d59528b0c8797664308af960a3a/daily-multi-translation/bot.py#L79)：创建 VAD 处理器，95 行使用 ParallelPipeline。

**框架指标启用示例 — 已具备**

上游价值：与官方示例一致地获取处理阶段指标。

当前差距 / 采用成本：实际设备延迟仍需独立测量。

- [daily-multi-translation/bot.py:127](https://github.com/pipecat-ai/pipecat-examples/blob/7875d02bc0714d59528b0c8797664308af960a3a/daily-multi-translation/bot.py#L127)：启用处理和用量指标。

校正 / 限制：示例组合不等同已在本机测得性能优势。

### pipecat-ai/smart-turn

固定源码：[4786657e242d](https://github.com/pipecat-ai/smart-turn/tree/4786657e242dfe77dd138699ac564ee074a2a543)。源码许可记录：BSD-2-Clause（模型权重许可另查）；模型、素材、SDK/Core和服务许可另核。

当前对照：Pipecat 默认 LocalSmartTurn v3.2 CPU 已加载。

**音频轮次结束预测 — 已具备**

上游价值：在 VAD 基础上辅助判断轮次是否完成。

当前差距 / 采用成本：当前已启用；中文语料准确率及本机时延仍需独立评测。

- [record_and_predict.py:173](https://github.com/pipecat-ai/smart-turn/blob/4786657e242dfe77dd138699ac564ee074a2a543/record_and_predict.py#L173)：处理分段音频并在 192 行输出完整性及概率。

**延迟与吞吐基准 — 部分**

上游价值：可建立轮次检测性能基线。

当前差距 / 采用成本：需代表性中文数据及本机实测，不可直接引用上游数字。

- [benchmark.py:372](https://github.com/pipecat-ai/smart-turn/blob/4786657e242dfe77dd138699ac564ee074a2a543/benchmark.py#L372)：报告 p50、p90、平均延迟和吞吐量。

重点核对：中文轮次准确率与时延基准。

校正 / 限制：旧版 defer adoption 错误；当前已加载模型。

### QwenLM/Qwen3-ASR

固定源码：[7c6daf77a242](https://github.com/QwenLM/Qwen3-ASR/tree/7c6daf77a2421100f5fb066495372c00129d39ff)。源码许可记录：源码 Apache-2.0；权重按对应模型卡；模型、素材、SDK/Core和服务许可另核。

**状态化 PCM 分块识别 — 缺失**

上游价值：可能在说话期间展示部分文本、提前判断打断

当前差距 / 采用成本：需要中文真实麦克风误识、端点、资源与延迟评测

- [qwen_asr/inference/qwen3_asr.py:657](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py#L657)：streaming_transcribe 接受 PCM 和状态

**可选强制对齐 — 缺失**

上游价值：生成字符或词的音频时间跨度

当前差距 / 采用成本：额外对齐模型和耗时，不能视作 TTS 音素时间戳

- [qwen_asr/inference/qwen3_forced_aligner.py:395](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_forced_aligner.py#L395)：给定转写执行强制对齐

重点核对：部分转写；转写与音频强制对齐。

校正 / 限制：模型设备与 NPU 能力未在本机验证。

### QwenLM/Qwen3-Omni

固定源码：[e42358531255](https://github.com/QwenLM/Qwen3-Omni/tree/e4235853125589c789f06a2dd83e9f4126df5e9d)。源码许可记录：源码 Apache-2.0；模型权重按模型卡；模型、素材、SDK/Core和服务许可另核。

**音频输入多模态推理示例 — 缺失**

上游价值：可探索语音音色情感等超出纯转写的理解

当前差距 / 采用成本：模型规模、中文效果和硬件性能需单独验证

- [web_demo_captioner.py:50](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/web_demo_captioner.py#L50)：音频描述生成

**自动设备映射与多模态处理 — 待验证**

上游价值：可作为多模态架构候选

当前差距 / 采用成本：示例不证明当前机器 NPU 或实时全双工可用

- [web_demo_captioner.py:20](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/web_demo_captioner.py#L20)：模型 device_map 和音频处理

重点核对：原生多模态音频理解。

校正 / 限制：演示代码不能证明全双工中文表现或设备延迟。

### QwenLM/Qwen3-TTS

固定源码：[022e286b98fb](https://github.com/QwenLM/Qwen3-TTS/tree/022e286b98fbec7e1e916cb940cdf532cd9f488e)。源码许可记录：源码 Apache-2.0；权重按模型卡；模型、素材、SDK/Core和服务许可另核。

**参考音频克隆 — 缺失**

上游价值：个性化音色生成

当前差距 / 采用成本：需验证授权、模型、资源与中文质量

- [qwen_tts/inference/qwen3_tts_model.py:470](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L470)：generate_voice_clone

**文本描述设计音色 — 缺失**

上游价值：可根据文字控制声音特征

当前差距 / 采用成本：额外模型与 GPU/CPU 延迟评估

- [qwen_tts/inference/qwen3_tts_model.py:637](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L637)：generate_voice_design

**非流式文本接口的模拟设置 — 非同类**

上游价值：避免误把参数命名当作实时生成优势

当前差距 / 采用成本：需寻找并单独验证真正流式后端

- [qwen_tts/inference/qwen3_tts_model.py:513](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L513)：明确不启用真正流式输入或生成

重点核对：语音克隆；文字音色设计。

校正 / 限制：该审计接口明确不提供真正流式文本输入或流式生成。

### QwenLM/Qwen3.5

固定源码：[2ea10dc72582](https://github.com/QwenLM/Qwen3.5/tree/2ea10dc725823bf7c3e21ce8557cbe15245132ae)。源码许可记录：仓库 Apache-2.0；模型版本许可独立核查；模型、素材、SDK/Core和服务许可另核。

**模型系列介绍与规模选择 — 非同类**

上游价值：可供选择本地中文对话模型

当前差距 / 采用成本：外部运行时、权重许可和中文延迟需另行评测

- [README.md:34](https://github.com/QwenLM/Qwen3.5/blob/2ea10dc725823bf7c3e21ce8557cbe15245132ae/README.md#L34)：固定源码归档只有说明和许可，无推理实现

重点核对：可选本地对话模型。

校正 / 限制：README-only，无法引用该仓库实际语音实现，不声称存在实时语音或 NPU 能力。

### snakers4/silero-vad

固定源码：[066409f3d9db](https://github.com/snakers4/silero-vad/tree/066409f3d9db45a30d21dfcbf9147826ffdd7052)。源码许可记录：源码 MIT；模型许可另核查；模型、素材、SDK/Core和服务许可另核。

**状态化流式 VAD — 已具备**

上游价值：当前 Pipecat 使用 Silero 切分语音，避免整段连续识别

当前差距 / 采用成本：需要真实环境调试语音边界，不提供说话人身份

- [src/silero_vad/utils_vad.py:591](https://github.com/snakers4/silero-vad/blob/066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/utils_vad.py#L591)：VADIterator

**离线语音区间时间戳 — 部分**

上游价值：可离线检查起止边界

当前差距 / 采用成本：区间为语音活动，不是文字或音素强制对齐

- [src/silero_vad/utils_vad.py:281](https://github.com/snakers4/silero-vad/blob/066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/utils_vad.py#L281)：get_speech_timestamps

校正 / 限制：VAD endpointing 和在线 ASR 模型的部分识别与端点机制不同。

### suzuran0y/Live2D-LLM-Chat

固定源码：[b333789c0962](https://github.com/suzuran0y/Live2D-LLM-Chat/tree/b333789c0962cd6244330120ec24634f8a5a70a8)。源码许可记录：Apache-2.0；模型、素材、SDK/Core和服务许可另核。

**WAV 输入校验 — 已具备**

上游价值：可拒绝损坏输入

当前差距 / 采用成本：当前有录入格式校验；具体边界需逐项比较

- [packages/contracts/protocol.py:16](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/packages/contracts/protocol.py#L16)：检查 RIFF 长度并用 wave 验证音频

**ASR worker 分离 — 已具备**

上游价值：独立进程边界有利服务隔离

当前差距 / 采用成本：当前 ASR 已通过独立 HTTP 语音进程隔离；不能将进程分离列为缺口。

- [workers/asr/worker.py:39](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/workers/asr/worker.py#L39)：worker 调用识别引擎

**结构化 worker 帧 — 部分**

上游价值：显式区分完成、错误与音频块确认，便于监控和背压

当前差距 / 采用成本：当前 Pipecat 事件及 HTTP 过程已有部分状态；需逐项比较语义后再决定，不必复制整套协议。

- [packages/contracts/protocol.py:12](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/packages/contracts/protocol.py#L12)：定义 chunk-ack、completed、error 等请求与事件类型
- [packages/contracts/protocol.py:75](https://github.com/suzuran0y/Live2D-LLM-Chat/blob/b333789c0962cd6244330120ec24634f8a5a70a8/packages/contracts/protocol.py#L75)：读取并校验 worker 协议帧

重点核对：结构化 worker 帧。

校正 / 限制：当前 ASR 已位于独立 HTTP 语音进程，worker 分离并非缺失。

### SYSTRAN/faster-whisper

固定源码：[2a3a857737d1](https://github.com/SYSTRAN/faster-whisper/tree/2a3a857737d17d974f30d818ebec69ce11929e5c)。源码许可记录：源码 MIT；转换模型许可另核查；模型、素材、SDK/Core和服务许可另核。

**分段 Whisper 转写和词级时间戳 — 部分**

上游价值：当前已有 CPU fallback；启用词级对齐可扩展转写时间信息

当前差距 / 采用成本：性能和中文对齐质量需实测

- [faster_whisper/transcribe.py:254](https://github.com/SYSTRAN/faster-whisper/blob/2a3a857737d17d974f30d818ebec69ce11929e5c/faster_whisper/transcribe.py#L254)：转写接口及 word_timestamps 参数

**转写时语音活动过滤 — 部分**

上游价值：可在批处理转写中去掉静音；当前已有上游 VAD 分段

当前差距 / 采用成本：重复 VAD 参数需校准，非原生实时部分识别

- [faster_whisper/transcribe.py:289](https://github.com/SYSTRAN/faster-whisper/blob/2a3a857737d17d974f30d818ebec69ce11929e5c/faster_whisper/transcribe.py#L289)：vad_filter 参数

重点核对：词级时间戳输出。

校正 / 限制：当前虽有 fallback，但其词级时间戳尚未暴露。

### TacoTakumi/HermesConsole

固定源码：[55d8c732482c](https://github.com/TacoTakumi/HermesConsole/tree/55d8c732482cfbab398cfcab68d8eea08146d2ba)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

当前对照：浏览器请求 AEC，尚无真实扬声器到麦克风的产品验收。

**物理设备 AEC 验收门槛 — 缺失**

上游价值：检测真实回声路径而非仅合成数据。

当前差距 / 采用成本：Android 硬件专用；需为目标 Windows 浏览器、音频设备设计等价测试。

- [app/src/androidTest/kotlin/com/hermesconsole/app/AecHardwareGateTest.kt:46](https://github.com/TacoTakumi/HermesConsole/blob/55d8c732482cfbab398cfcab68d8eea08146d2ba/app/src/androidTest/kotlin/com/hermesconsole/app/AecHardwareGateTest.kt#L46)：通过设备扬声器与麦克风测试回声，133 行检查硬件 AEC。

**可重复打断语音样本 — 部分**

上游价值：降低人工语音测试的波动。

当前差距 / 采用成本：须补充真人、双讲、中文短附和和噪声样本。

- [scripts/make-bargein-speech.py:3](https://github.com/TacoTakumi/HermesConsole/blob/55d8c732482cfbab398cfcab68d8eea08146d2ba/scripts/make-bargein-speech.py#L3)：生成固定语音用于可重复打断测试。

重点核对：目标设备的真实 AEC 及双讲门槛。

校正 / 限制：Android 设备测试结果不能外推至本机。

### TacoTakumi/VoiceManager

固定源码：[256d573cbd69](https://github.com/TacoTakumi/VoiceManager/tree/256d573cbd6981da29f51dc66faabcebb83d8eab)。源码许可记录：MIT；模型、素材、SDK/Core和服务许可另核。

当前对照：分段 SenseVoice STT，增量 PCM TTS；无播放进度 ACK。

**增量 STT 中间结果与最终结果 — 缺失**

上游价值：无需等待整段语音结束即可获得部分文本。

当前差距 / 采用成本：依赖具体流式后端、模型和运行环境；需验证中文、CPU/NPU 和声纹门禁次序。

- [src/voicemanager/pipeline/audiocpp_stt.py:14](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/pipeline/audiocpp_stt.py#L14)：音频事件产生增量文本，FLUSH 输出最终结果；35 行映射 interim 与 final。

**客户端播放边界与麦克风样本时钟 — 缺失**

上游价值：可对齐播放与插话事件。

当前差距 / 采用成本：需客户端主动上报边界；不能仅凭边界证明每个字被用户听到。

- [src/voicemanager/transport/turn_engine.py:45](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/transport/turn_engine.py#L45)：以麦克风采样计数关联播放起止和送出的回复。

**有界队列与溢出丢弃 — 待验证**

上游价值：避免慢速旁路阻塞麦克风接收。

当前差距 / 采用成本：需制定丢帧指标和降级策略；丢弃可能影响轮次检测。

- [src/voicemanager/transport/turn_engine.py:1039](https://github.com/TacoTakumi/VoiceManager/blob/256d573cbd6981da29f51dc66faabcebb83d8eab/src/voicemanager/transport/turn_engine.py#L1039)：非阻塞入队并处理队列满；对应状态在 855 行。

重点核对：真增量 STT；播放边界确认；队列压力指标与恢复策略。

校正 / 限制：旧报告未充分说明流式 STT、播放边界及背压；这些能力依赖特定后端与协议。

### THUDM/GLM-4-Voice

固定源码：[eb00ce9142e8](https://github.com/THUDM/GLM-4-Voice/tree/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a)。源码许可记录：源码 Apache-2.0；模型许可另核查；模型、素材、SDK/Core和服务许可另核。

**语言模型音频 token 流输出 — 缺失**

上游价值：探索语音 token 端到端对话

当前差距 / 采用成本：多模型部署，资源及中文语音对话质量待测

- [model_server.py:83](https://github.com/THUDM/GLM-4-Voice/blob/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a/model_server.py#L83)：generate_stream 逐 token 输出

**语音 flow 流推理 — 部分**

上游价值：可逐步解码生成语音；当前已有 VITS 回调分段

当前差距 / 采用成本：需要端到端模型适配及实测，不推断全双工或 NPU

- [flow_inference.py:97](https://github.com/THUDM/GLM-4-Voice/blob/eb00ce9142e8d98b0ed7c57cd47e0d6d5dce9a1a/flow_inference.py#L97)：stream_inference

重点核对：端到端语音 token 生成。

校正 / 限制：流式 token 和语音解码不自动证明低延迟全双工。

### TMElyralab/MuseTalk

固定源码：[0a89dec45a01](https://github.com/TMElyralab/MuseTalk/tree/0a89dec45a0192b824e3cf4daf96c239440c5ed8)。源码许可记录：MIT; model terms separate；模型、素材、SDK/Core和服务许可另核。

**音频特征与帧切片 — 非同类**

上游价值：音频条件驱动像素脸视频

当前差距 / 采用成本：当前为可编辑 Cubism 参数；模型与 GPU 依赖，本机性能未测

- [scripts/realtime_inference.py:244](https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py#L244)：提取 Whisper 音频特征并按 fps 切片

**视频帧输出 — 非同类**

上游价值：适合真人视频头像合成

当前差距 / 采用成本：需视频合成和输出时钟，不能直接替代 Cubism

- [scripts/realtime_inference.py:212](https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py#L212)：消费结果队列并处理视频帧

校正 / 限制：MuseTalk 有实时推理入口；生成像素视频而非 Cubism 参数，本机延迟未测。

### vllm-project/vllm

固定源码：[14d147a7a05d](https://github.com/vllm-project/vllm/tree/14d147a7a05d29d011a67ed1f1f819c03546dafe)。源码许可记录：源码 Apache-2.0；模型许可独立；模型、素材、SDK/Core和服务许可另核。

**异步模型请求与增量生成 — 非同类**

上游价值：集中式多请求 LLM 服务可扩展吞吐

当前差距 / 采用成本：需服务器、兼容模型和硬件；Windows/NPU 未测

- [vllm/v1/engine/async_llm.py:740](https://github.com/vllm-project/vllm/blob/14d147a7a05d29d011a67ed1f1f819c03546dafe/vllm/v1/engine/async_llm.py#L740)：异步 generate

校正 / 限制：异步 LLM token 生成不是 ASR 或 TTS 实时能力。

### vllm-project/vllm-omni

固定源码：[1200aa7379ff](https://github.com/vllm-project/vllm-omni/tree/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9)。源码许可记录：源码 Apache-2.0；模型许可独立；模型、素材、SDK/Core和服务许可另核。

**双工客户端发送 PCM 流 — 部分**

上游价值：为双向音频提供客户端协议；当前已有独立识别与合成的交互

当前差距 / 采用成本：特定后端和模型必须验证实际双工、中文质量和中断

- [vllm_omni/clients/duplex.py:801](https://github.com/vllm-project/vllm-omni/blob/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9/vllm_omni/clients/duplex.py#L801)：stream_pcm

**异步多模态生成 — 缺失**

上游价值：统一多模态模型服务入口

当前差距 / 采用成本：服务器和硬件依赖高，模型能力不可一概而论

- [vllm_omni/entrypoints/async_omni.py:150](https://github.com/vllm-project/vllm-omni/blob/1200aa7379ffd264baff6faf192e3a3ca2cd7ad9/vllm_omni/entrypoints/async_omni.py#L150)：async generate

重点核对：统一多模态双工模型。

校正 / 限制：客户端流接口不保证任意模型实时双工或 NPU 可用。

### wwbin2017/bailing

固定源码：[2f7dc881b684](https://github.com/wwbin2017/bailing/tree/2f7dc881b684c50fb0c612361a34b44bd5626aea)。源码许可记录：源码 MIT；模型与服务条款单独核查；模型、素材、SDK/Core和服务许可另核。

**FunASR 识别后端接口 — 部分**

上游价值：演示后端替换，当前已有本地识别抽象

当前差距 / 采用成本：需核对具体模型和分块语义

- [bailing/asr.py:36](https://github.com/wwbin2017/bailing/blob/2f7dc881b684c50fb0c612361a34b44bd5626aea/bailing/asr.py#L36)：FunASR 适配类

**Kokoro 合成后端 — 缺失**

上游价值：提供另一种音色和音质选择

当前差距 / 采用成本：新增前端、模型和中文音质评估

- [bailing/tts.py:202](https://github.com/wwbin2017/bailing/blob/2f7dc881b684c50fb0c612361a34b44bd5626aea/bailing/tts.py#L202)：KOKOROTTS 类

重点核对：可选 Kokoro 音色。

校正 / 限制：多个适配器并不证明流式文本、对齐、中文或 NPU 性能。

## 不能从此次审查推出的结论

- 无同机统一A/B，不能认定某个完整项目“语音逻辑最好”或一定比我们更快。
- 连续PCM采集、分块音频输出、模型接收流式文本、端到端模型全双工是不同能力，不能混称“真流式”。
- 浏览器报告AEC开启不等于外放效果通过；声纹筛选不等于分离重叠说话或去掉噪声。
- 口型有声学分类不等于中文每字精确；带时间的英文viseme事件也不自动适用于中文。
- NPU设备存在、支持某后端或模型能编译都不等于本项目NPU识别质量/延迟合格。
- 本次只读审查和报告，不将候选方案描述为已移植的新功能。
