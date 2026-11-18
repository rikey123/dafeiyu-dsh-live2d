# 语音功能前端到推理审计（2026-11-14）

> **2026-11-14 当前状态：MFA 运行功能已退役。** 本文涉及 MFA 的实现、安装、命令、测试和结果均为历史记录，不是当前可选功能；相关启动/安装/浏览器时间轴验收入口已经移除。当前仅使用实时 PCM 口型，见 [实时口型](REALTIME_LIPSYNC.md)。E 盘历史环境与权重未自动删除。下文旧“当前”描述不再代表现行状态。

> **后续修复补充（同日）**：MFA 已改为 Windows 原生 CPU，环境、模型和缓存位于 E 盘；真实前端 GPU/CPU 对齐播放、依赖缺失错误、CPU 对齐取消恢复均验证通过。下文“MFA 本机不可用”和“未修复”的描述保留为修复前的历史证据，不再代表 MFA 当前状态。实测等待时间、复现方法及边界见 [MFA_NATIVE.md](MFA_NATIVE.md)。独立的 GPU 合成取消/立即续说缺陷及外部云端未验收结论没有因此消失。

## 结论

**当前不能把所有可选模式称为可用。** 本次用户的无音频错误已定位到 MFA 运行时缺失，另外实测发现 GPU 停止/立即续说的生命周期缺陷。没有用自动降级掩盖问题，没有修改用户生产设置，也没有安装 WSL 或调用付费服务。

- 基础听说链路：真实 Edge、正式 `web/dist`、本地 ASR、真实本地 TTS、protobuf、Web Audio worklet、Live2D 与播放 ACK 已跑通。
- 本机不可用：MFA 离线对齐。
- 已复现缺陷：GPU 合成中停止后立即提问，以及播放刚开始就停止后立即续说，均可能返回 503 和无音频。
- 外部服务未验收：MOSS-Live、真实供应商 TTS API 没有独立凭据。API 协议模拟器成功不能证明供应商可用。
- 本轮只增加/完善隔离验收工具和报告；**以上生产缺陷尚未修复**。最后已停止项目推理与隔离 QA 进程，不占用项目 GPU worker；原生产设置仍选 MFA，直接原样启动仍会失败。

## 1. 用户这次错误的因果链

用户报出的上下文：`7dda0ab0-9c9c-4a04-9379-b41499965026`。

生产设置快照只列非敏感字段：

```json
{"tts_mode":"gpu","gpu_tts_model":"gpt_sovits","tts_alignment":"mfa","conversation_mode":"duplex","streaming_asr_preview":false}
```

`G:/dafeiyu/data/logs/8765.log` 中，2026-11-14 **08:00:27.132（日志原始时间）**先出现：

```text
本地语音合成失败: All connection attempts failed
```

08:00:27.133 才出现该上下文的 `completed with no audio`。该上下文对应“今天想聊点什么？”，不是首句“你好呀，很高兴见到你。”。前一个上下文也以同样原因失败。

实际流程见 `G:/dafeiyu/speech/pipecat_services.py` 的 `LocalSpeechTTS._run_tts_frames`：

```text
GPU 8770 生成 WAV 成功
  → 转成供对齐使用的 PCM
  → 请求 MFA 8771 /v1/align（失败：没有监听服务）
  → 尚未向前端输出 PCM
  → 框架记录 completed with no audio
```

`G:/dafeiyu/data/logs/8770.log` 的实际推理及 HTTP 200、隔离浏览器复现的 **0 音频帧**、关闭对齐后的正常播放共同证明：**这次不是 GPU 合成器返回了空 WAV，而是它后面的强制对齐步骤阻断输出**。

### MFA 为什么没有起来

启动器 `G:/dafeiyu/scripts/optional_voice.py` 对 MFA 执行 `wsl.exe -d Ubuntu --exec python3 ...`。本机实查：

- `Microsoft-Windows-Subsystem-Linux = Disabled`；
- `VirtualMachinePlatform = Disabled`；
- 没有注册 WSL 发行版，Ubuntu 不存在；
- `wsl.exe --status` 失败；执行 Ubuntu 中的 Python 仅返回 WSL 帮助，退出码非零；
- `G:/dafeiyu/models/mfa-mandarin` 虽然有下载的模型/词典，但不等于有可运行的 Linux/Python/MFA 环境。

`8771.log` 中的启动失败信息还存在 WSL 输出编码问题，监督器会重复尝试；不能因文件存在或单元测试通过而说本机 MFA 可用。

### 工程层面的缺口

1. 保存 MFA 选项没有完整依赖准入，语音会话也没有在推理前清楚拒绝不可用的对齐链路。
2. `tts.ready` 可以只反映 GPU 模型就绪；独立 `optional.mfa` 的失败没有合并为整条输出链的不可用状态。
3. 合成和对齐共用“本地语音合成失败”错误，缺少失败阶段；后来的通用 no-audio 又覆盖前端更有用的原因。
4. 连续无音频还会触发框架连续失败保护，不应让用户不断重试来碰运气。

**关闭 MFA 可以恢复实时口型基础播放，但这只是禁用不可用功能，不是修好了 MFA。本轮未擅自替用户关闭。**

## 2. 独立复现：停止之后为什么又无音频

这是新发现的问题，和 MFA 是两条不同的失败路径。测试明确将对齐设为 `off`。

### 首块 PCM 之前停止，然后立即提问

从前端发送文字，轮询到真实 GPU 正在合成且尚未收到 PCM，点击“停止”，150ms 后立即发送下一句：

- 停止后 GPU health 为 `state=unloaded, ready=false, resident=false`；
- 下一句 HTTP **503**，前端 **0 音频帧**；
- 随后框架报 no-audio；
- 等待后台重新预热到 `ready` 后，同一前端连接可再次播放，实测 65,280 samples，并收到 ACK。

### 已开始播放时停止，然后立即点击“继续刚才的回答”

worklet 确认已经消费 PCM，再点击停止和继续：

- 前端发送了真实 `voice.stop` 以及 `voice.playback.stopped`（已消费 2,816 samples）；
- 续说时 sidecar 已进入重新加载，返回 **503**，无音频；
- 所以不能把“停止按钮能让声音停下”当成整套打断/续说功能可用。

### 源码机制

`G:/dafeiyu/server/model_tts_sidecar.py`：未完成的 `ModelHost.stream` 在 finally 中 `stop()` 销毁 worker。显式 GPU 模式由后台 reaper 或新请求触发重新准备；尚未准备完成时 `synthesize` 返回 409/503。`LocalSpeechTTS` 没有协调这个恢复窗口。前端仍允许立即提交新轮次，因此后台即使有预热机制，也不能保证这次新回复有声音。

**CPU 对照**：同样在首块 PCM 前停止，worker 也卸载，但 CPU 按需路径能在下一句重新加载并完成播放及历史入库。该次下一句约 **11.845 秒**完成播放 ACK；这是可以恢复，不是快速恢复。

尚未把该 GPU 缺陷推广成“所有声学插话都必然失败”：本次严格复现的是按钮停止/立即续说。真人双讲、回声消除和自然打断时延仍需专门测试。

## 3. 逐项前端检查

“通过”指该列所述边界，不代表声学效果、真人身份准确率或云端供应商均已验收。

| 功能 | 本轮结果 | 实际验证范围 / 限制 |
| --- | --- | --- |
| GPT-SoVITS GPU | 基础输出通过 | 真实 CUDA、预热、CUDA Graph、前端 PCM 消费和 ACK；热播放样本约 3.779 秒完成 |
| IndexTTS-2.5 GPU | 基础输出通过 | UI 切换模型、旧服务释放、新模型预热、播放和 ACK；本次准备 112.750 秒，随后播放样本约 4.205 秒完成 |
| MOSS-TTS-Nano CPU ONNX | 基础输出通过 | UI 保存、真实 ONNX CPU、播放和 ACK；CPU 模式下 GPU 服务已停止 |
| 自动 GPU/CPU | 两条路由通过 | GPU URL 故意不可达时真实 CPU 输出；恢复 GPU URL 后真实 CUDA 输出；不调用付费兜底 |
| 轮流说话 pipeline | 保存及回复通过 | 正式前端设置、实际输出；未声称真人双讲体验已验收 |
| 本地 duplex 管线 | 基础链路通过，恢复有缺陷 | ASR + 受控 LLM + 所选 TTS；不是原生全双工语音模型；GPU 停止后立即续说失败 |
| MFA 对齐（实验） | **本机不可用，复现成功** | 真实 GPU WAV 成功但 MFA 连接失败、前端零音频；缺 WSL/Ubuntu/MFA 运行时 |
| 更快响应插话（实验） | 入口与数据链路通过 | UI 启用、文件麦克风、真实最终 ASR、回复 PCM、在线识别器确实加载；提前打断收益、真人噪声鲁棒性未测 |
| 本人声纹筛选 | 管理入口通过，识别效果未验收 | 真实 CPU 声纹模型、上传两段音频、录入、开关保存、删除；隔离档案；不是真人接受/拒绝率测试 |
| 两种实时口型声线 | 初始化及播放通过 | AIRI / local-vits 均能初始化；Live2D 实际嘴参数变化；local-vits 不是新 GPU 声线专用标定，音素分类准确率未测 |
| TTS API 缺密钥 | 明确报错，模式当前不能合成 | 能收到独立 TTS 密钥提示，但后续通用 no-audio 会覆盖它 |
| TTS API 协议 | **仅本机模拟供应商通过** | 真实 SDK → 受控 PCM HTTP 接口 → 正式浏览器播放；不代表真实供应商鉴权、音色、计费和网络可用 |
| MOSS-Live + DeepSeek | **真实云端未验证** | 模式可保存、禁用文字输入；无独立 MOSS 密钥，前端明确显示配置错误；没有进行付费探测 |
| GPU 首块前停止/立即再问 | **失败** | sidecar 503、零音频；待预热恢复后可播放 |
| GPU 播放中停止/立即续说 | **失败** | 真实 worklet 消费后停止、续说仍 503 |
| CPU 首块前停止/立即再问 | 恢复通过但慢 | 卸载后重新按需加载，真实播放、ACK、助手历史入库 |

上述播放耗时使用固定短句、受控本机 LLM，从测试提交到播放确认计时，**不是生产 DeepSeek 首字/首声时延，也不是声卡实际出声测量**。Index 与 GSV 不是同一轮硬件负载下的统计基准。

### 两个验收脚本误判已经纠正

- 声纹 checkbox 由 HTTP 保存完成后更新；Playwright `.check()` 的即时状态断言误报失败。改为 click 后等待后端和 UI 状态，复测成功。
- MOSS 未配置时在 RTVI pipeline 创建前以 WebSocket 1008 关闭。最初脚本只等 RTVI error，误以为没有提示；改为检查真实 `.notice` 后确认前端显示“请配置 MOSS-Live 与 DeepSeek 密钥，并关闭本地声纹筛选”。**这是错误提示通过，不是 MOSS 云端通过。**

快速切换模式的一次人工式探测曾观察到口型 worklet `AbortError` 回退提示；本轮两种声线正常初始化/播放均通过，尚未隔离该快速重连时序，不能宣称任何切换时序都无问题。

## 4. 后续修复验收要求

1. **MFA 能力准入与阶段错误**：检查运行时、服务、模型；保存/启动给明确失败原因；输出链 ready 要包含对齐依赖。不可静默改模式或把实时口型回退说成 MFA 成功。
2. **取消与模型驻留协调**：先取消本轮输出，按明确协议取消/排空推理；确需销毁 worker 时，新轮次必须进入有界等待/明确准备态，不能直接把瞬时 409/503 变成整轮无音频。不能靠延迟前端点击或无限重试通过测试。
3. **错误关联**：保留本轮最早的有用诊断及阶段，避免通用 no-audio 覆盖；不输出密钥、请求头和供应商私密响应。
4. **云端与声学效果**：只有取得用户独立凭据并明确允许付费测试后，才验收 MOSS 听说、DeepSeek 委派及真实 TTS API；真人麦克风/AEC/旁人声纹和音质另列验收，不用合成录音替代。

以上是针对本项目实测缺口的修复标准，不是已经实现的能力。

## 5. 证据、工具与复现

证据均放在 **`E:/Dafeiyu/verification/feature-audit`**：

- `browser-audit.json`：第一批 13 项，保留原始失败，不覆盖历史；
- `browser-audit-Owner-voice-MOSS-Live.json`：声纹复测、尚未纠正断言时的 MOSS 记录；
- `browser-audit-MOSS-Live-Stop.json`：正确的 MOSS 缺密钥边界，以及两个真实 GPU 停止失败；
- `browser-audit-CPU-stop.json`：CPU 停止恢复对照及历史入库；
- `audit-summary.json`：按 case 名合并最新结果，同时保留每次尝试与来源；
- `wsl-prerequisites.json`、`moss-missing-key.png`、隔离 speech/gateway stdout/stderr；
- `stopped-state.json`：结束时项目及 QA 端口均无监听、相关进程为空。

工具：

- `G:/dafeiyu/scripts/serve_voice_acceptance.py`：隔离 Store、受控流式 LLM、标记清楚的 API PCM fixture；
- `G:/dafeiyu/scripts/audit_model_services.py`：使用监督器环境管理该隔离 Store 的真实 TTS；
- `G:/dafeiyu/scripts/check_feature_audit.cjs`：真实 Edge、正式前端、真实本地模型、失败后继续下一项；存在失败最终退出码非零。测试结束转到无密钥 API 配置以释放隔离 GPU，不调用 API，也不改变生产设置。

启动前提：先停止生产监督器；8766 ASR 应启用在线识别与声纹能力，并将声纹存储指向 E 盘隔离档案；正式 `web/dist` 已构建。网关测试用 `.venv-voice`，模型管理子进程用带 pywin32 的 `.venv`。不得占用正在服务用户的外部模型进程。

```powershell
Set-Location G:/dafeiyu
$env:TEMP='E:/Dafeiyu/cache/tmp'; $env:TMP=$env:TEMP
$env:PYTHONIOENCODING='utf-8'
# 先满足上述 ASR/隔离档案前提；在单独终端启动隔离网关。
.venv-voice/Scripts/python.exe scripts/serve_voice_acceptance.py --tts-mode gpu --gpu-tts-model gpt_sovits --manage-model-services --reply '你好，很高兴和你聊天。' --api-audio-fixture E:/Dafeiyu/verification/gpu-preload-first-request.wav
# 另一终端；可用 AUDIT_CASE_FILTER 仅选部分 case，报告将另存。
node scripts/check_feature_audit.cjs
```

fixture WAV 必须是实际存在的 24kHz 单声道 PCM16；麦克风/声纹 fixture 位于证据目录。浏览器使用文件麦克风，不冒充用户真实硬件。停止时先通知隔离 model manager 的 stop-file 并等待 owned worker 退出，再关闭其网关和 ASR；不要按进程名全局杀 Python。

本轮重新运行了 MFA / ASR preview / 模式策略 / MOSS 边界相关单元测试：**55 passed**，另通过两个 Python QA 脚本编译检查及 Node 语法检查。单元测试的假上游不能代替本机运行时和前端验收。
