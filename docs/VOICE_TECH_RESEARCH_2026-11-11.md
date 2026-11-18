# 大肥鱼语音技术选型调研

调研日期：2026-11-11。目标环境：Windows、RTX 5080 16GB、中文实时 Live2D 陪伴。本文属于技术调研，不表示已部署或已在本机完成候选模型的性能验收。网页、模型卡、价格和免费政策可能更新，实施时须记录模型 revision、代码 commit 和下单页面。

## 1. 建议与现有基线

优先安排三条互相独立的路线：

1. **本地低延迟 TTS**：现有 CosyVoice3-0.5B 为基线，对比 Qwen3-TTS-0.6B 官方实现与 faster-qwen3-tts，以及 VoxCPM1.5-0.6B / Nano-vLLM。不能仅凭参数量或上游 4090 数据决定更换。
2. **低资源 CPU TTS**：先测 MOSS-TTS-Nano 0.1B 的官方 ONNX 路线，再评估 ZipVoice-Distill 123M；保留现有 VITS 作可用性基线。蒸馏、ONNX 和更小参数量不等于已达到本机实时要求。
3. **全双工会话**：本地先验证 MiniCPM-o 4.5 的完整 GGUF 部署；API 先研究 MOSS-Live。全双工应成为会话后端，不能仅新增一个 TTS 音色选项。

IndexTTS2.5 / IndexTTS2 TensorRT 作为音色、情绪与加速专项；API 同时保留低价固定音色和高表现力音色，不能只按广告最低价选供应商。

本项目已有真实 GPU 验收记录 `docs/COSYVOICE3_RTX5080_ACCEPTANCE_2026-11-08.json`：单条热启动样本首音 **1.437 秒**、总生成 **1.89 秒**、输出 **3.84 秒**音频，标准 RTF 约 **0.492**；冷样本首音约 **36.094 秒**。记录报告实际 CUDA、fp16 和约 3.66GB reserved 显存。它只是一次语音链路验收，不能当作 p50/p95、端到端麦克风响应或所有文本的性能结论。单样本暴露出冷启动和首音延迟值得优先优化。

## 2. 本地 TTS 候选

统一采用 **RTF = 合成耗时 / 音频时长，越小越好**。某些仓库把倒数也称为 RTF，本文不混用。首个网络包、首个非静音 PCM、首个可播放音频和用户听到声音是不同指标。

| 候选 | 规模与主要能力 | 可核实的上游信息 | 对本项目的判断 |
| --- | --- | --- | --- |
| CosyVoice3 | 现有 Fun-CosyVoice3-0.5B；中文、克隆、持续文本输入 | 本机已有上述单样本 CUDA 验收 | 必须保留基线；优先检查预热、文本分块、播放缓冲与 MFA 是否影响首音 |
| Qwen3-TTS | 0.6B / 1.7B；克隆、预设音色、音色设计依具体 checkpoint 而定 | 官方模型与社区推理实现均可获得；faster 项目有 Windows 指南 [S1–S2] | 首批测试 0.6B，分别测官方和社区实现；不要把不同 checkpoint 的能力直接合并 |
| faster-qwen3-tts | 同权重推理优化，CUDA Graph、参考音频缓存、减少 Python 开销 | 当前 README 的 4090 表：0.6B 首块 156ms、1.7B 174ms；chunk=8。Windows 4060 表分别为 413/460ms，均是作者测试，不是本机成绩 [S2] | 有潜力；不代表本机首音。先确认是完整文本输入后流式音频，还是支持真实增量文本输入；官方/社区版本分开固定 |
| VoxCPM1.5 | 0.6B 骨干，中英双语、克隆、流式、44.1kHz | 官方 4090 表：原生标准 RTF 0.15，Nano-vLLM 0.08，标注显存约 6GB [S3] | GPU 首批候选；适合和现有 0.5B 横向比。Windows 加速栈需要独立验证 |
| VoxCPM2 | 2B，30 种语言、48kHz | 同表原生 RTF 0.30、加速 0.13，约 8GB [S3] | 多语音质路线；低延迟优先时排在 1.5 后面，显存还要留给其他组件 |
| MOSS-TTS-Nano | 0.1B，含中英的多语种、零样本克隆、48kHz 双声道、Apache-2.0 | 官方已提供流式与 ONNX CPU 路线；Apple M4 CPU 演示不能证明 Windows CPU 实时 [S4] | CPU 首批候选；测长短句稳定性、线程数、常驻内存和首音 |
| ZipVoice / ZipVoice-Distill | 123M，中英零样本；蒸馏减少采样步骤 | 官方提供标准版、Distill 与 Triton 运行目录，Apache-2.0；不预设其为真正增量文本流式 [S5] | 很值得做轻量补充；参数小不代表低首音，需核对具体流式入口与 Windows 依赖 |
| IndexTTS2.5 | 约 0.8B GPT 骨干（不含全部辅助模型）；五语言、情绪与克隆 | 官方模型卡称重新设计声学部分、相对 2.0 加速，并支持 vLLM；使用 bilibili Model Use License [S6–S7] | 质量与情绪专项，不预先认定它是实时对话最快方案 |
| IndexTTS2 TensorRT | 2.0 权重的 TensorRT / TensorRT-LLM 加速 | 已并入官方仓库的社区后端；**当前引擎只支持 2.0，不能给 2.5 直接套用** [S8] | 独立 E 盘运行时，优先 Linux/WSL 可行性验证，避免污染现有 CosyVoice 环境 |

### IndexTTS 官方与社区加速应如何理解

官方仓库目前收录了源自 MuyangDu/index-tts（Faster IndexTTS-2）的 TRT 后端。官方文档的 4090 表给出：2.0 原生 FP16 平均标准 RTF **0.3263**，2.0 TRT FP16 **0.1365**，同代约 **2.39 倍**；2.5 原生 BF16 **0.2035**。这些数字可以说明 2.0 TRT 有加速价值，但不能证明 2.5 TRT 已可用，也不能推导 5080 的首音延迟。[S8]

TRT 文档的验证环境涉及 Python 3.12、TensorRT 10.11、TensorRT-LLM 0.21、torch 2.7.1/cu128、OpenMPI。应将其当成需要固定依赖和引擎构建流程的部署项目；不能把社区视频中的倍数直接搬到 Windows 主环境。许可还须检查模型协议及参考声音的授权。[S6–S8]

### 参数规模和上游指标的额外校核

这些 0.xB 多数是骨干规模，tokenizer、声码器、KV cache 与编译缓存还会占显存。VoxCPM 官方版本表的 1.5 为 0.6B backbone，而其另一张评测表写 0.8B；不能将二者当成完全相同的总参数口径。faster-qwen3-tts 当前将播放时长/合成耗时称作 RTF，例如 4090 的 0.6B 为 4.78 倍实时；换成本文标准 RTF 约 0.209。其 streaming baseline 来自社区流式或动态缓存路径，不能称为官方原生首音对照。模型论文宣称支持流式与发布 Python API 是否暴露增量文本接口，也须分别核实。[S1–S3]

### CPU 社区优化观察

`audio.cpp` 探索以 C++/ggml 统一多种语音模型，是值得追踪的 CPU 路线。[S22] Reddit 作者展示过 Qwen3-TTS 的 CPU 使用经验；这类讨论也揭示一个问题：**整段生成快于播放，并不等于第一句话很快开始**。相关机器、量化、线程和句长不同，不与本机数据直接比较。audio.cpp 现已提供 Windows、CUDA、CPU 等后端及统一服务接口，值得加入第二批运行时对照；仍需逐模型验证声码器、采样和流式结果一致性。首批 CPU 先测官方 Nano/ZipVoice，避免同时引入过多变量。[S22,C4]

## 3. 全双工：独立的会话架构

| 方案 | 查到的发布形态 | 本机适用性 | 关键问题 |
| --- | --- | --- | --- |
| MOSS-Live | 官方实时 WebSocket API、客户端/服务端演示，持续听说、打断与工具调用 [S9] | 可作为云端会话后端；本轮未找到公开本地权重和完整本地推理入口 | 不将 API 演示说成本地部署；未核实 Live 的公开单价，不借用普通 TTS 价格 |
| MiniCPM-o 4.5 | 9B 全模态架构；官方提供 GGUF 全双工部署文档 [S10–S11] | 完整 GGUF 指南给出 NVIDIA 最低 12GB、推荐 16GB；5080 16GB 值得验证，不保证能与游戏/本地 LLM 共存 | 必须下载并验证完整视觉、音频编码器、语言模型与语音解码链；单个语言 GGUF 能跑不等于全双工能跑 |
| NVIDIA PersonaPlex / Kyutai Moshi | 公开全双工研究模型与推理代码 [S12–S13] | 可作架构与交互参考；中文品质、显存和当前 Windows 路线均需额外验证 | 本项目优先中文与易部署，因此暂不列首批 |

MiniCPM 标准 PyTorch 演示与 GGUF 部署是不同运行路径；不能拿高显存 PyTorch 要求否决整个 16GB 方案，也不能只凭 GGUF 的内存表宣称本机已完成全双工。GGUF 指南同时覆盖半双工和全双工，验收时必须启用真正的全双工模式。[S10–S11]

工程上建议新增 `conversation_backend = pipeline | moss_live | local_omni`，与现有 `tts_mode` 分开。该名称是设计建议，不是已实现配置。经典流水线仍由 ASR→LLM→TTS 组成；全双工后端需要同时管理连续输入输出、回声消除、播放进度、打断、工具调用和历史提交。复用现有 Live2D 音频输出与口型接口，但重新验证会话状态机。

## 4. TTS API：按中文真实用量比较

以下金额是 **10 万个普通汉字正文**的示意成本，不做美元汇率换算。排除标点、数字读法展开、SSML、克隆建音色、并发、包月及税费；具体计数规则不明的服务按“10 万计费字符”列明，不能承诺就是 10 万汉字的账单。报价以本次查询到的当前产品页为依据，不作为合同报价。

| 服务 | 当前公开口径 | 同量估算 | 选型意义与限制 |
| --- | --- | --- | --- |
| 腾讯云精品音色 | 当前购买页按量后付费 **0.3 元/万字符** | 约 **3 元/10 万计费字符** | 固定音色低成本首选候选；不是大模型克隆音色的价格。以具体音色 ID 验证支持能力 [S14] |
| 腾讯云大模型音色 | 当前页大模型低用量档 **1.2 元/万字符**；超自然 2.0 **2.5 元/万**；超自然 1.0 低用量档 **6.5 元/万** | 分别约 **12 / 25 / 65 元/10 万计费字符** | 音色档位不能混比；资源包可能更便宜，但需承担预付和过期风险 [S14] |
| 百炼 CosyVoice | 北京价目表：`v3.5-flash` **0.8 元/万字符**、`v3.5-plus` **1.5 元/万**；`v3-flash` **1 元/万**、`v3-plus` **2 元/万**；一汉字计二字符 | 10 万普通汉字约 **16 / 30 / 20 / 40 元** | 国内 API 重点候选；不同地域、版本、实时接口、复刻建音色收费分开核对 [S15] |
| 百炼 Qwen TTS | 北京 `qwen3-tts-flash` **0.8 元/万字符**；`qwen3-tts-flash-realtime` **1 元/万**；一汉字计二字符 | 10 万普通汉字约 **16 / 20 元** | 预设音色、复刻和设计音色是不同入口；VC/VD 型号需另核价 [S15] |
| MiniMax Turbo / HD | 官方分别 **2 / 3.5 元/万计费字符**；**一个汉字计两个字符** | 10 万普通汉字约 **40 / 70 元** | 需为声音表现力做盲听；中文预算不能直接照每万字符广告价 [S16] |
| Fish Audio S2.1 Pro | 当前付费版 **15 美元/百万 UTF-8 字节**；普通汉字常为 3 字节 | 约 **4.50 美元/10 万普通汉字** | 当前 `s2.1-pro-free` 标注免费但限流；限额及可用性需在控制台实测，不承诺无限免费 [S17] |
| Inworld TTS 2 | 当前 on-demand Realtime TTS-2 Flash **15 美元/百万字符**，Realtime TTS-2 **25 美元/百万字符** | **1.50 / 2.50 美元/10 万计费字符** | 海外成本候选；页面同时有订阅与企业档，不能混用最低套餐单价；大陆网络和中文品质需测 [S18] |
| 小米 MiMo-V2.5-TTS | 当前官方介绍页仍标注系列 API **限时免费**；本次最终页面未给出统一结束日期和账户限额 | 当前适用活动内为 0；长期单价未核实 | 适合试用；须确认账户、地域、限流和活动有效期，不承诺永久免费 [S19] |
| 硅基流动 | 文档提供语音合成能力与模型列表 [S20] | 本轮未确认当前目标模型的稳定公开结算价 | 可作为统一接入候选，价格必须按具体模型与控制台确认，不引用旧帖价格 |
| 火山/豆包语音 | 官方文档有流式语音合成、不同版本与资源包 [S21] | 本轮未获得足够明确、同档位的当前价格证据，不进入最低价排名 | 中文品质对照候选；先确认具体产品、音色、双向流式与资源包口径 |

**价格校核说明**：本轮检索过程中出现过旧版本价格、聚合页面和不同套餐口径，尤其是腾讯、百炼与 Inworld。上表采用最后核对的当前产品档位。最终核对到百炼“语音合成”节的统一字符规则：该节按每万字符计费的模型，一个汉字计两个字符；MiniMax 也明确采用这一规则。两家上表均已据此换算。购买前用一段已知字数的中文短文核对实际扣量。Fish 旧 S2 迁移价格不作为新接入的长期预算。

对本项目的选择：**固定音色极低成本优先腾讯精品音色；国内大模型优先比较百炼与腾讯对应档位；当前零成本试验关注 MiMo 和 Fish 免费档；海外按量关注 Inworld。**这只是筛选顺序，最终按国内实测 p95 首音、音色盲听与真实账单决定。不要为便宜将密钥交给来源不明的中转站。

## 5. 社区、B站和论坛检索的作用与局限

本轮覆盖了官方仓库、模型卡、中文开发者社区、B站、V2EX、Reddit/LocalLLaMA。社区内容用于找部署坑、候选优化和主观听感；性能与价格尽量回到作者仓库和厂商官方页。没有完整观看全部视频；部分 B站页面有访问限制，只核对可见标题、简介、日期或官方 README 的视频链接。

- **B站官方 IndexTTS2.5 演示**：适合听情绪、韵律和多语种，不能从剪辑视频计算首音或吞吐；由官方仓库链接到 `BV1uvMk6ZEdK`。[C1]
- **linux.do 的免费 API / 本地中文 TTS 讨论**：同时提及 Qwen、CosyVoice、Index 等候选；帖内也有把 Base 与 VoiceDesign 能力写反的内容，说明社区标签必须回到官方模型卡核对。[C2]
- **Reddit 的 audio.cpp 作者帖**：CPU 与量化方向的线索，适合跟踪实际运行时更新；作者单机结果不等于独立复现。[C4]
- **V2EX 的 MiMo 听书集成与体验帖**：作者介绍限免接入，也有用户认为风格控制不够准确；均是产品实践或主观反馈，旧活动政策以当前官方页替代。[C5,C8]

另查到 B站 2026-08-15 的 IndexTTS2.5 本地整合包与 2026-08-24 的 V32 二次封装；标题宣传 CPU/8GB 和强制断句，不代表获得可复现的模型内核加速。优先检查是否公开代码、原始参数与测试脚本，再决定是否采用。[C6–C7]

可转化为验收用例的问题：生成成功但音频不可播放、长句尾部缺失、数字多音字错读、流式分段导致韵律断裂、用户打断后仍继续计费、清理未完成便启动下轮，以及 GPU 被其他应用占用时的准入行为。帖子只能提出待验证问题，不能证明每个模型都存在这些缺陷。

## 6. 工程接入建议

项目已有 `auto/cpu/gpu/api/legacy` 和 Pipecat 播放确认、取消机制，见 `docs/TTS_MODES.md` 与 `docs/PROTOCOL.md`。下一步建议延伸为“模式决定运行位置，provider 决定具体引擎”，避免每加一个模型就复制一套模式判断。

每个 provider 需要明确声明：真实增量文本输入、音频分块输出、原始采样率/编码、取消语义、音色复刻、情绪、时间戳、实际设备。区分 `text_streaming` 和 `audio_streaming`，不能因为 HTTP 流式返回就标成双向流式。

当前 `speech/api_tts.py` 使用 OpenAI SDK，要求 `/audio/speech` 返回 **24kHz 单声道 PCM16LE 裸流**，并关闭自动重试。“兼容 OpenAI”本身不能证明可直接接入：WebSocket 鉴权与事件、WAV/MP3 容器、16/44.1/48kHz 输出、大小端和取消均需 provider adapter。重采样使用有状态流式处理，保持跨 chunk 连续；TTS 适配器输出仍接入现有播放与实时口型。

所有本地候选使用 E 盘独立环境与模型缓存；GPU 同时只保留一个候选常驻，切换前等待原进程/worker 清理。显存准入同时看实际剩余显存，不能只看显卡总量。健康状态分别报告“运行时可用、模型加载、实际设备、最近一次合成”。首次安装不自动下载其他模型，回环监听沿用现有约定。

API 实现连接复用、超时、背压与有限队列；用户打断时立即停止本地播放并关闭上游请求。已经产生计费或输出音频的请求不自动重试；付费 API 不作为自动模式的隐式兜底。错误日志只记脱敏状态、耗时、用量和上下文 ID，不记密钥与原始授权头。克隆声纹和参考音频的授权单独管理。

## 7. 建议的测试与实施顺序

### 第一阶段：首音与 CPU 保底

- 固定 100 条中文样本，覆盖 5–20 字短句、50–100 字解释、长文、数字日期金额、英文混读、多音字、情绪；参考音频与随机种子尽可能统一。
- 对现有 CosyVoice、Qwen3-0.6B 官方/加速、VoxCPM1.5 各测冷启动和热启动。记录采样率、precision、checkpoint、chunk、提示音频长度、是否编译、参考缓存与峰值显存。
- CPU 首测 Nano ONNX，再视结果测 ZipVoice-Distill，并与现有 VITS 盲听。记录 CPU 型号、线程数与内存，不用 Apple 的结果推算本机。
- 首音分别记：请求发出→首个非静音可播放 PCM、LLM 首 token→扬声器首次播放、用户说完→扬声器首次播放；报告 p50/p95，不能只报最好样本。
- 同时测标准 RTF、长句掉速、分段接缝、ASR 回读字符错误率与人工盲听。ASR 回读不能代替音色和自然度评价。

### 第二阶段：API 小额对照

- 使用同一语料和同等音色能力，分别测腾讯精品、百炼候选、MiMo 活动档、Fish 免费/付费、Inworld；MiniMax 作表现力对照。
- 核验一段已知汉字数文本的实际扣量，记录数字归一化、克隆费、最小消费、免费有效期、并发、429 和地域。先限额再试，不在调研阶段发起付费请求。
- 测国内实际网络的 p50/p95，不采用厂商内部延迟替代。验证返回音频可解码、非空、长度合理，失败后不反复付费重试。

### 第三阶段：Index 专项与全双工

- Index2.5 原生/vLLM 与 Index2.0 原生/TRT 分别形成同权重对照；不要将不同代、不同精度混成一个倍数。
- MiniCPM GGUF 先验完整音频链路和显存，再验全双工；MOSS-Live 先获取正式价格与数据政策，再做 API 试验。
- 对同时说话、回声、短插话、连续打断、工具执行中打断、断线重连、播放进度与历史一致性作专项测试。
- 建议进行 100 次随机打断，分别记录“本地停止发声”和“上游停止生成/计费”；150ms 本地停播可作候选验收目标，**不是已经达到的成绩**。
- 最终在 ASR、LLM、Live2D 共存及其他应用占用显存的条件下复测。出现显存不足或清理超时要明确报错/按既有本地策略处理，不宣称 NPU 推理或悄悄转付费服务。

本轮仅阅读、检索和编写文档，没有下载候选模型、调用收费接口、启动推理或更改项目运行配置。

## 8. 来源索引

以下均为本轮调研参考入口；网页可变，实施与采购时重新固定版本、核价。

### 官方模型、作者仓库与部署文档

- [S1] Qwen3-TTS：https://github.com/QwenLM/Qwen3-TTS
- [S2] faster-qwen3-tts：https://github.com/andimarafioti/faster-qwen3-tts ；Windows 指南：https://github.com/andimarafioti/faster-qwen3-tts/blob/main/WINDOWS_SETUP_GUIDE.md
- [S3] VoxCPM：https://github.com/OpenBMB/VoxCPM ；Nano-vLLM：https://github.com/a710128/nanovllm-voxcpm
- [S4] MOSS-TTS-Nano：https://github.com/OpenMOSS/MOSS-TTS-Nano
- [S5] ZipVoice：https://github.com/k2-fsa/ZipVoice
- [S6] IndexTTS 官方仓库：https://github.com/index-tts/index-tts
- [S7] IndexTTS2.5 官方模型卡：https://huggingface.co/IndexTeam/IndexTTS-2.5
- [S8] Index 官方 TRT 后端：https://github.com/index-tts/index-tts/blob/main/backends/trt/README.md
- [S9] MOSS-Live：https://github.com/OpenMOSS/MOSS-Live ；实时场景文档：https://platform.moss.cn/en/docs/scenarios/moss-live/
- [S10] MiniCPM-o：https://github.com/OpenBMB/MiniCPM-o
- [S11] 官方链接的 GGUF 全双工指南：https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/demo/web_demo/WebRTC_Demo/README.md
- [S12] PersonaPlex：https://github.com/NVIDIA/personaplex
- [S13] Moshi：https://github.com/kyutai-labs/moshi
- [S22] audio.cpp：https://github.com/0xShug0/audio.cpp

### 官方 API 与价格

- [S14] 腾讯当前购买/计费档位：https://cloud.tencent.com/document/product/1073/34112 ；计费概述：https://cloud.tencent.com/document/product/1073/34185
- [S15] 阿里云百炼模型价格：https://help.aliyun.com/zh/model-studio/model-pricing
- [S16] MiniMax 定价：https://platform.minimax.cn/docs/pricing/overview
- [S17] Fish Audio 定价与限流：https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits
- [S18] Inworld TTS 当前按量价与套餐：https://inworld.ai/tts ；https://inworld.ai/pricing
- [S19] 小米 MiMo-V2.5-TTS：https://mimo.xiaomi.com/mimo-v2-5-tts
- [S20] 硅基流动语音合成文档：https://docs.siliconflow.cn/cn/userguide/capabilities/text-to-speech
- [S21] 火山语音官方文档入口：https://www.volcengine.com/docs/6561/1359370

### 中文社区、B站与海外论坛线索

- [C1] 官方 IndexTTS2.5 B站演示：https://www.bilibili.com/video/BV1uvMk6ZEdK/
- [C2] linux.do 免费 API / 自部署中文 TTS 讨论（2026-02-20）：https://linux.do/t/topic/1630432
- [C4] Reddit / LocalLLaMA audio.cpp 作者讨论：https://www.reddit.com/r/LocalLLaMA/comments/1ufpnm6/audiocpp_12_audio_models_qwen3tts_pockettts_vevo2/
- [C5] V2EX MiMo 听书集成实践：https://v2ex.com/t/1200931
- [C6] B站 IndexTTS2.5 本地整合包（2026-08-15；核对标题与简介）：https://www.bilibili.com/video/BV1Vibk6SERt/
- [C7] B站 IndexTTS-V32（2026-08-24；核对标题与简介）：https://www.bilibili.com/video/BV1cshP6hEQy/
- [C8] V2EX MiMo 风格体验：https://v2ex.com/t/1202294
- [C9] Reddit audio.cpp 近期更新讨论：https://www.reddit.com/r/LocalLLaMA/comments/1x0q91x/audiocpp_recent_updates_you_might_have_missed/

社区链接不是价格或性能结论的最终依据。无法访问的正文、未完整观看的视频和未公开的部署条件都不当成已经验证的事实。