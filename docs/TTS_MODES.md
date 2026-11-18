# 语音模式与独立模型服务

本地 GPU 可选择 GPT-SoVITS v5 turbo 或 IndexTTS-2.5；另有 MOSS-TTS-Nano 100M ONNX CPU 和独立 API TTS。自动模式在选定的 GPU 服务和 CPU 服务中选择，不调用收费 API。CosyVoice、VITS 的旧源码保留供迁移与历史测试，启动器不再加载它们。

## 模式与架构

| 配置 | 运行路径 | 服务地址 | 设备要求 |
| --- | --- | --- | --- |
| `tts_mode=gpu` | `gpu_tts_model=gpt_sovits` 使用 v5 turbo FP16 四步合成；`index_tts` 使用 IndexTTS-2.5 BF16 + KV cache | loopback:8770 | 实际 CUDA；不静默退回 CPU |
| `tts_mode=cpu` | 官方 `OrtCpuRuntime` + ONNX 音频编解码器 | loopback:8772 | 只允许 CPUExecutionProvider，不安装 torch |
| `tts_mode=api` | 默认 DeepSeek 官方原生 `/v1/tools/tts` WebSocket；旧 OpenAI-compatible `/audio/speech` 可显式选择 | 云端 | 24kHz 单声道小端 PCM16 |
| `tts_mode=auto` | 每次回复前根据本地健康状态选择 | 两个本地服务 | GPU 失败不重播当前回答，下一次回复用 CPU |

`conversation_mode` 决定语音交互方式：

| 配置 | 语音路径 | 后台模型与条件 |
| --- | --- | --- |
| `duplex`（默认） | 本地 ASR → DeepSeek → 所选 TTS；播放时继续收音，支持说话打断 | 使用现有 LLM 设置 |
| `pipeline` | 同上；播放期间向 VAD 输入等长静音，保留手动停止 | 使用现有 LLM 设置 |
| `moss_live` | 云端 MOSS-Live 实时语音模型，音频输入输出，不传视频 | MOSS 前台语音 + client delegation 调用现有 DeepSeek；需要独立 MOSS 密钥 |

`moss_live` 已接入真实的语音模型协议，并非把 ASR/TTS 流水线改名。前台 MOSS 可以直接处理简单对话，复杂任务交给 DeepSeek；因此不能宣称每一句输出都由 DeepSeek 生成。该模式使用 MOSS 的语音输出，语音会话绕过本地 ASR/TTS，并停止启动器拥有的 TTS sidecar，保留之前保存的 `tts_mode`，切回流水线后恢复。它不加载本地 MOSS-Live 权重；若要求完全本地语音模型，需要另行评估模型与显存。

在设置中选择“MOSS-Live 全双工”，填写独立密钥（或在被忽略的 `.env` 配置 `MOSS_API_KEY`），可选择 `moss-live-1.0` 或固定版本 `moss-live-1.0-2026-11-02`，并可填写平台支持的 voice ID。该模式只接受麦克风语音；文字输入与文字续说按钮停用，切回流水线后可输入文字。声纹锁定与该云端模式不兼容，切换时明确拒绝冲突配置。密钥只保存在后端，查询只返回是否已配置；健康查询不创建收费会话。

`/api/voice/config` 和 `/api/status` 区分语音模型名称、配置状态与探测状态：本地流水线的 `speech_to_speech_model` 为 null，MOSS 模式返回实际选择的模型。已配置密钥不表示云端实测通过。已完成使用模拟云端的真实 FastAPI/Pipecat/protobuf 传输测试；独立密钥、收费连接、浏览器麦克风和声学打断仍需实机验证。

### MOSS-TTS-Nano 内置音色

设置中选择 CPU、自动或跟随启动策略后，“MOSS 内置音色”提供按语言/性别分组的下拉列表，不再手填 ID。“默认”明确显示实际模型的第一个音色，当前为 Junhao。选择后需要保存，其他模型和云端语音的音色不受影响。原先重复的通用“声音”输入框已移除。

2026-11-14 本机安装的官方 ONNX 模型 `browser_poc_manifest.json` 含 18 个预置音色；下表仅转录清单名称，不是音质、身份授权或跨语言效果承诺：

| 分组 | ID 与模型原始名称 |
| --- | --- |
| 中文男声 | Junhao（欢迎关注模思智能）、Zhiming（京味胡同闲聊）、Weiguo（说书） |
| 中文女声 | Xiaoyu（明星）、Yuewen（机车）、Lingyu（深夜电台） |
| 英文男声 | Trump（Trump）、Adam（English News）、Nathan（The Quiet Motion of the World） |
| 英文女声 | Ava（The Bitter Lesson）、Bella（A Gentle Reminder） |
| 日文女声 | Soyo（Soyo）、Saki（Saki）、Mortis（Mortis）、Umiri（Umiri）、Mei（Togawa）、Anon（Anon）、Arisa（Arisa） |

列表不写死在前端：网关 `GET /api/tts/voices` 优先读取所保存的 MOSS 服务 `GET /v1/audio/voices`。默认受管理 CPU 服务因 GPU 模式而未启动时，读取 `DAFEIYU_MOSS_MODEL`（默认 E 盘）的实际模型清单；不启动模型、不占显卡、不发起合成或收费请求。自定义端口服务不可用或清单无效时不套用另一套本机音色。只返回 ID、名称、分组和默认 ID，不暴露本地路径、参考音频编码或密钥。限制清单大小、数量、重复 ID、模型身份与代理请求时限，拒绝重定向。

读取失败时明确显示错误并可刷新；已有未知 ID 显式标为不可用，不静默改成默认。更改服务地址后先保存，再重新打开设置读取对应清单。本功能仅适用于本地 ONNX CPU MOSS，不将这些 ID 用于 MOSS-Live。

验证：后端 190 项通过、1 项跳过；前端 110 项通过，构建成功。真实 Edge 的分组枚举、Lingyu 选择/保存/刷新/真实 CPU PCM 播放/ACK/历史，以及清单失败后保留与重试恢复均通过（3 组用例）。没有逐个试听全部 18 个音色，也未据此宣称音质验收；LLM 为隔离本地固定回复，未调用收费 API。复现：隔离 CPU 网关就绪后运行 `node scripts/check_moss_voices.cjs`；报告与清单快照位于 `E:/Dafeiyu/verification/moss-voices/`。核对上游固定源码 README 与实际运行时的 `list_builtin_voices()`；本轮 Hugging Face 远程清单下载超时，当前列表以已安装模型为准。

## 独立环境与准备

运行时、源码、模型和大文件缓存全部放在 `E:/Dafeiyu`，后端设置与网关仍在项目目录。不要在系统 Python 或网关环境中安装模型依赖。

```powershell
.venv\Scripts\python.exe scripts/prepare_tts_models.py --kind moss
.venv\Scripts\python.exe scripts/prepare_tts_models.py --kind index
```

MOSS 环境在 `E:/Dafeiyu/runtimes/moss-tts`，使用 Python 3.12。Index 环境在 `E:/Dafeiyu/runtimes/index-tts-py311`，按官方 `<3.12` 要求使用 Python 3.11 和 CUDA 12.8 PyTorch 2.8。脚本通过 E 盘 uv 自动准备解释器；源码固定到已核对的提交，ModelScope 官方模型文件逐一验证大小和 SHA-256，并记录版本元数据；成功安装后冻结实际依赖到运行时目录。`--skip-models`、`--skip-runtime` 分别用于分阶段安装。默认普通依赖索引为阿里云，`--index-url` 可覆盖；PyTorch 使用独立官方 CUDA 索引。

GPU 主路线固定 2.5，当前接入的是官方原生 BF16。社区 Faster IndexTTS2 / TRT 主要针对 2.0，不能把它贴成“2.5 社区加速版”。没有完成本机 benchmark 前，不承诺首音、RTF 或加速比例。后续 vLLM 服务需独立验证 Windows/WSL、版本与取消接口后再注册。

IndexTTS 还需要有权使用的参考录音：在被忽略的 `.env` 配置 `DAFEIYU_INDEX_PROMPT_WAV=E:/.../reference.wav`。MOSS 默认使用官方 manifest 的首个内置音色，也接受其中的 voice ID；GPU 使用固定参考录音，不会把 MOSS 的 voice ID 传过去。除模型包外，Index 上游可能要求 w2v-BERT、BigVGAN、CAMPPlus 等辅助权重，应按上游辅助权重准备工具准备；未齐全时首次真实合成失败会明确记录，不能仅以主模型下载完成宣称可用。

## 生命周期与取消

`scripts/run.py` 根据保存的路由同步服务；切换为 CPU/API 会停止启动器拥有的 GPU 服务；MOSS-Live 模式停止启动器拥有的本地 TTS 服务，基础 ASR 服务保留供状态查询和切回本地模式。对外部服务只借用，不擅自终止。每个 sidecar 只绑定 `127.0.0.1`，独立运行时由 Windows Job 包含，退出时释放子进程。ASR 服务不再加载旧 VITS。密钥只留在网关配置，生成的 sidecar 文件只含白名单本地路径与线程数，子进程环境过滤密钥字段。

显式 `gpu` 模式在保存启用或项目按已保存配置启动时，立即在后台 spawn worker 加载模型，并以短句真实预热参考音色、推理缓存及支持的 CUDA Graph。预热 PCM 直接丢弃，不播放、不写聊天记录、不调用 DeepSeek 或付费 API。只有 CUDA 预热成功才报告 `ready=true`，模式期间常驻显存，不因空闲卸载；切换 CPU/API/MOSS-Live 或退出时释放受管理服务。界面区分加载中、预热中、就绪和失败；失败后可点“重新准备 GPU 模型”，按钮按已保存配置执行，不会并行重复加载。

健康查询本身不会触发加载；`configured` 只表示文件已发现。`state=unloaded|loading|warming|ready|error`，`preload` 表示启用预加载策略，`resident` 仅在模型实际存活且就绪时为真，`warmed_up` 来自真实推理。自动 / CPU 模式仍按需加载；仅这些非驻留 worker 使用空闲回收：Index/MOSS 默认 180 秒，GPT-SoVITS 默认 900 秒，`DAFEIYU_GSV_IDLE_SECONDS` 可在 60–3600 秒内配置。GPU 自动准入使用有时限的 nvidia-smi 空闲显存探测（至少 6GiB 是准入策略，不是测得的模型需求）；准入不等于已完成推理。worker 使用有界管道，MOSS 回调桥接队列最多 4 块。每个服务只接受一个合成请求，加载 / 预热期间冲突返回 409，未就绪时返回 503，不将冷加载转嫁给首条用户请求。

HTTP 在拿到第一块真实音频后才发送 200；模型加载失败返回 503。取消、断连、超时、输出超限或 worker 失败都会结束当前 worker，避免残留 GPU 计算。显式 GPU 模式在取消后后台重新准备；模型失败保留错误，需显式重试，避免反复失败占用设备。自动 / CPU 模式在下一次请求时按需重载。服务端请求上限 2000 字、加载或合成有 180 秒期限、最大 15MB PCM。模型加载过慢会给出明确失败；不是无限等待。已开始播放后发生错误，不切换 provider 重播同一句。

## 端点与音频

本地独立模型服务提供 `GET /health`、`POST /v1/audio/speech`（WAV/PCM）、`POST /v1/audio/speech/stream`（仅 PCM）。请求为 `{input,voice,response_format}`。流式头固定 `X-Audio-Sample-Rate:24000`、`X-Audio-Channels:1`、`X-Audio-Format:pcm_s16le`。Index 原生 22050Hz、GPT-SoVITS 原生 48000Hz 按流有状态重采样到 24kHz；MOSS 按 codec 元信息解码、转单声道并重采样。复用现有 Pipecat context、播放 ACK、取消与历史确认逻辑。

API 模式继续使用独立密钥、零自动重试、无自动收费 fallback、有界音频与协议检查。状态只检查配置，不调用收费合成。远程基础地址仅 HTTPS，loopback 可 HTTP；切换 API 地址必须重新填写或明确清除原密钥。WAV/Ogg/FLAC、JSON 和大端 audio/L16 不得伪装为 PCM。

### DeepSeek 官方 TTS（2026-11-14 接入）

在设置选择「API · DeepSeek TTS」→「DeepSeek 官方 TTS」，独立填写 DeepSeek 开放平台 API Key。DSH 的网页登录凭据不等于 API Key；插件不读取 DSH 凭据文件，也不偷偷复用模型登录。后端基础地址默认为 `https://api.deepseek.com/v1`，原生适配器使用 `wss://api.deepseek.com/v1/tools/tts`，不是 OpenAI `/audio/speech`。提供 `stella`（海星女声，默认）和 `tide`（暗潮男声）；可配置过滤 Markdown、总请求超时。官方没有 `model`、语速参数，因此 DeepSeek 面板不提供这两个无效选项，也不向云端发送旧字段。

复用现有 Pipecat 逐句文本聚合、上下文取消、播放 ACK、System One/陪玩主动发言和实际播放 PCM 口型，不替换 DSH harness/记忆。每个朗读文本段建立一次 WebSocket 会话，发送 `text` → `finish_text`，边收二进制 PCM 边播放，必须收到 `finish/code=success` 才算成功；正常关闭但缺少完成事件也作为失败。这里并未把多个 Pipecat 文本段合并为单个持续 token 输入会话，不承诺比 HTTP 更低的端到端延迟。

总期限在每次跨 task 读取时重新扣减；连接、读取、输出大小和队列有上限，输出块不超过 100ms。打断会关闭连接，不续传、不自动重试、不在出错后换供应商重播。拒绝握手重定向，错误信息不回显供应商正文、close reason 或密钥。合成前校验官方文本字符/UTF-8 上限，空音频、半采样、容器头、无效控制事件及中途断流明确失败。状态轮询仍为 `verification=not_probed`，不会收费试音。

只对未修改且没有密钥的旧 OpenAI 模板切换为 DeepSeek 默认值；已有密钥、定制地址/模型/音色/语速的设置一次性标记为 `openai_compatible`，保留原服务和密钥，不自动转发。此前已选本地 GPU/CPU 等模式的用户不会被自动改成付费 API 模式。新适配器的协议、PCM、超时、断流、打断、密钥迁移和 UI 使用本机模拟供应商测试；真实云端音质和延迟必须在填写独立密钥后实测，不能将模拟 PCM 当作官方验证。

官方参考：<https://api-docs.deepseek.com/zh-cn/api/tts/>、<https://api-docs.deepseek.com/zh-cn/guides/tts>。

2026-11-14 验证：后端/语音回归 468 项通过、1 项跳过；前端 149 项通过，普通与 DSH 构建成功。真实 Edge 的音色/过滤设置保存重载、原生协议接收音频 → worklet 消费 48,000 采样 → ACK → 历史确认、停止关闭上游且不重连、内容审核失败脱敏提示四项通过；供应商和 LLM 均为 loopback fixture，PCM 是明确标注的合成测试音，不是官方声音。官方 WebSocket 未授权连接返回 HTTP 401，仅证明网络和入口可达，未发送文字、未使用密钥、未合成，不代表账号授权或真实 TTS 验收。报告在 `E:/Dafeiyu/verification/deepseek-tts/browser.json`。

复现浏览器原生协议验收（第二个终端运行 Node 检查脚本，PCM WAV 必须为 24kHz 单声道 16 位）：

```powershell
$env:TEMP='E:/Dafeiyu/tmp'; $env:TMP=$env:TEMP
G:/dafeiyu/.venv-voice/Scripts/python.exe G:/dafeiyu/scripts/serve_voice_acceptance.py --deepseek-api-fixture --api-audio-fixture E:/Dafeiyu/verification/deepseek-tts/synthetic-fixture.wav --reply "原生接口测试。"
node G:/dafeiyu/scripts/check_deepseek_tts.cjs
```

口型统一使用浏览器实际播放 PCM 的实时 wLipSync/MFCC，失败时明确显示音量口型回退；不再提供 MFA 选项，也不等待完整 WAV 后对齐。旧的 `tts_alignment` / `mfa_url` 会在数据库打开时自动清理，旧客户端提交这些字段返回 422。声学分类不等于精确音素时间轴；默认通用模板尚未针对当前声线校准。见 [REALTIME_LIPSYNC.md](REALTIME_LIPSYNC.md)。

## MOSS-Live 会话与播放回执

网关通过 `wss://api.mosi.cn/v1/realtime` 连接官方服务，以 `delegation.type=client` 附着会话，并验证服务器确认了委托模式和 PCM 格式。输入持续发送 16kHz PCM16（包括静音），输出为 24kHz PCM16。浏览器沿用现有 Pipecat protobuf 通道和播放回执，不直接获得云端密钥。

只有浏览器真正消费的音频才向上游确认播放；打断时先停止播放器，再报告未确认首块的实际消费量，已确认块不重复累计。传输层补齐的静音不计入云端原始音频进度。回复的最终文字与整段音频消费都完成后才保存助手历史；输入修订只更新本会话对应的用户消息。

委托执行有去重和取消，最多两个并行任务，单次不超过 60 秒，并尊重平台更短的期限；使用现有 LLM 端点和密钥，不另设聊天模型。输出音频、待播回复、消息大小、委托记录和 websocket 队列均有上限，断线与会话退出会关闭云连接并取消委托。

## 本机实测记录（2026-11-12）

MOSS CPU 使用同一 worker 连续合成“你好，我是大飞鱼，很高兴和你聊天。”，第一次包含模型加载，第二次复用模型。冷启动首块 PCM 7.976 秒、总耗时 9.124 秒、音频 3.52 秒；热启动首块 PCM 0.338 秒、总耗时 1.774 秒、音频 4.08 秒，RTF 0.435。随机生成导致时长不同；这只是单条样本，不是延迟保证，且不包含网络、播放器、ASR 或 LLM。已检查非空非静音，仍需人工试听。SenseVoice CPU 回读冷启动样本与原文一致，热启动样本将“大飞鱼”识别成同音的“大飞宇”，其余内容一致；回读不能替代人工音质验收。报告和 WAV 位于 `E:/Dafeiyu/verification/moss_tts-smoke*.{json,wav}`。

IndexTTS 2.5 使用 RTX 5080（16GB）、官方 BF16 与 KV cache，在同一 worker 连续合成同一文字。实际返回 `device=cuda`、`backend=native-bf16`。冷启动首块 PCM 115.638 秒、总耗时 115.669 秒、音频 3.311 秒；热启动首块 PCM 1.420 秒、总耗时 1.482 秒、音频 3.509 秒，RTF 0.422。冷启动包含首次导入、模型加载和合成，明显慢于热运行；空闲卸载或取消后再次生成可能需要重新加载。两份音频均已检查非空非静音，SenseVoice CPU 回读均与原文一致，仍需人工试听。这也是单条样本，不包含 ASR、DeepSeek、网络或浏览器播放，不能作为端到端延迟保证。当前没有采用仅适配 IndexTTS 2.0 的社区 TensorRT 优化，也没有将其性能归于 2.5。报告和 WAV 位于 `E:/Dafeiyu/verification/index_tts-smoke*.{json,wav}`。

```powershell
E:/Dafeiyu/runtimes/moss-tts/Scripts/python.exe scripts/smoke_tts_models.py --kind moss_tts --runs 2
E:/Dafeiyu/runtimes/index-tts-py311/Scripts/python.exe scripts/smoke_tts_models.py --kind index_tts --prompt-wav E:/path/to/reference.wav --runs 2
```

脚本不读取 `.env`，Index 参考录音必须通过参数或已导出的环境变量提供。脚本结束或异常都会回收模型 worker。

## GPT-SoVITS v5 turbo GPU 模式

运行 `python scripts/prepare_gpt_sovits.py`，将独立 Python 3.11 / PyTorch CUDA 12.8 环境、固定源码和模型放到 `E:/Dafeiyu`。上游源码固定为 RVC-Boss/GPT-SoVITS 的 `6d51ffceafbf240145619af4c92408a6e54b7924`，下载记录保存权重仓库 revision、文件尺寸和 LFS SHA256，下载后校验。不安装训练 WebUI、额外 ASR 或第三方推理整合包。源码的固定资源目录通过 E 盘目录联接指向模型目录，原有目录先保留备份。

在设置中选“本地 GPU”，将“GPU 语音模型”选为“GPT-SoVITS v5 turbo”。为兼容已有配置，服务地址字段仍叫 `index_tts_url`，界面显示“GPU 语音服务地址”；两种 GPU 模型共用 8770 端口，启动器只运行所选模型。保存切换会关闭旧语音连接，释放受管理的旧模型进程，再启动新服务。外部服务必须通过所选模型名称验证，不能把 Index 服务当成 GPT-SoVITS 复用；外部进程不会被停止。CPU/API/MOSS-Live 配置保持独立。

在 ignored `.env` 配置 `DAFEIYU_GSV_PROMPT_WAV` 与 `DAFEIYU_GSV_PROMPT_TEXT`，录音须为有权使用的 3–10 秒音频，文本与录音匹配。当前适配使用中文路径、FP16、四步扩散、上游参考缓存与静态 KV cache CUDA Graph 自回归路径，不要求 Windows FlashAttention。健康状态中的 `ar_backend`、`cuda_graph_active` 来自实际推理，未加载时不会宣称优化已生效。`return_fragment` 按标点分段并保序返回；这是按句生成，不是 codec 级逐 token 音频流。原生 48kHz PCM 连续重采样到浏览器使用的 24kHz。

服务保留同样的单请求准入、有界 IPC/PCM、断线/超时/取消回收机制。服务端总期限 180 秒，GPU 客户端读超时 185 秒，避免客户端先于服务端的明确错误关闭。截图中的 RTF 衡量总合成耗时与音频时长之比；首块 PCM 和包含 ASR/DeepSeek 的端到端等待需要分别测量。


2026-11-12 RTX 5080 实测，使用与 Index 记录相同的测试文字与参考录音：冷启动首块 PCM 30.997 秒、总耗时 32.238 秒、音频 2.96 秒；两次热运行首块 PCM 分别为 0.833 / 0.402 秒，总耗时 1.948 / 1.304 秒，音频 4.12 / 3.40 秒，RTF 0.473 / 0.384。三次均实际返回 `device=cuda`、`ar_backend=torch_static_cuda_graph`、`cuda_graph_active=true`；非空非静音检查通过，SenseVoice CPU 回读三次均与原文一致，人工音质验收仍需用户试听。对比之前 Index 热首块 1.420 秒与冷总耗时 115.669 秒，仅能说明这几个本机样本首次出声改善；没有测得截图中的 0.13 RTF，也不把合成延迟当成完整对话延迟。

首次实测还发现上游语言检测器在每个短语上尝试联网获取大模型，再回退到依赖自带的小模型，产生秒级额外等待。适配器现显式配置依赖内置 `lid.176.ftz`、禁用回退并复用检测器；校验后重新测速的日志中无模型下载请求。该配置用于中文伙伴的语言切分，不宣称额外语言的发音质量已验收。

报告与音频保存在 `E:/Dafeiyu/verification/gpt_sovits-smoke*.{json,wav}`。复现实测：

```powershell
E:/Dafeiyu/runtimes/gpt-sovits-py311/Scripts/python.exe scripts/smoke_tts_models.py --kind gpt_sovits --prompt-wav E:/path/to/reference.wav --prompt-text "参考录音的准确文本" --runs 3
```

随后通过已启动的真实服务执行 `Pipecat LocalSpeechTTS → loopback HTTP → CUDA worker`：冷首块 PCM 27.156 秒、总耗时 28.428 秒；热首块 PCM 1.089 秒、总耗时 2.234 秒、音频 3.76 秒。该链路包含适配器、健康身份检查及本机 HTTP，仍不包含 ASR、DeepSeek 或浏览器实际播放。它比独立 worker 的热样本慢，不能用后者替代完整使用体验。报告为 `E:/Dafeiyu/verification/gsv-live-adapter-{cold,warm}.json`；服务保持加载，健康返回 `ready=true`、`device=cuda`、`cuda_graph_active=true`。

## GPU 启用即预热验收（2026-11-14）

RTX 5080、已保存 GPT-SoVITS GPU 模式：启动后未发送任何合成请求即自动完成加载与真实短句预热，准备耗时 20.235 秒，状态为 `ready=true, device=cuda, warmed_up=true, resident=true, cuda_graph_active=true`。之后首条 HTTP 合成首块 PCM 为 1.469 秒，总耗时 2.766 秒，音频 3.08 秒，前后准备时间不变（未重新冷加载）。这是单条本地 TTS HTTP 样本，不是 ASR/DeepSeek/浏览器端到端延迟保证。

随后只保存切到 API（不调用付费合成），受管理 GPU 服务停止；切回 GPU 后，无合成请求即依次观察到 `loading → warming → ready`，本次模型准备耗时 18.078 秒，CUDA Graph 实际生效。最终恢复原 GPU 配置并保持就绪。可在已运行且已保存 GPU 配置的项目上复现：

```powershell
.venv/Scripts/python.exe scripts/check_gpu_preload.py --verify-mode-switch
```

脚本不调用 LLM/付费 TTS/麦克风；模式切换测试会关闭现有语音连接。证据与非空非静音 WAV 默认保存到 `E:/Dafeiyu/verification/gpu-preload.json`、`gpu-preload-first-request.wav`，脚本的后台准备等待上限 240 秒，服务本身每次准备期限仍为 180 秒。音质仍需用户试听。
