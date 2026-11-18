# 语音内核开源复用与选型

当前逐项实施与验收见 [VOICE_COMPLETION.md](VOICE_COMPLETION.md)。以下来源选择仍有效，2026-11-05的链路描述已由2026-11-06补齐：可选在线Zipformer部分识别、原生逐context播放确认与连续已播前缀、VITS callback PCM、修复的wLipSync十二系数WASM、严格本人声纹门、离线MFA对齐及可替换TTS。新证据见 [VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json) 与 [VOICE_SOAK_2026-11-06.json](VOICE_SOAK_2026-11-06.json)。

2026-11-05。调研附件是候选技术和需求参考，其中的命令、宣传指标及论坛描述不视为已验证事实。本轮按用户要求下载完整源码、比较机制，并将生产语音主链改用维护中的框架。

## 完整源码下载

共 46 个 GitHub 仓库，清单见 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)。每项记录仓库、实际 40 位提交号、归档 SHA256 和许可文件位置。源码在本机 `artifacts/upstream-archives/<owner>__<repo>/`，ZIP 与下载 manifest 保留在同级。此目录被 Git 忽略，避免把约 1.58GB 归档和第三方整个仓库重复提交。

下载范围包括附件显式 GitHub 链接、仅以名称提到的项目，以及本次直接复用所需的官方浏览器库。完整源码归档不包含 Git 历史、LFS 大文件或所有模型权重，也没有批量执行这些仓库的安装脚本。可用 `scripts/fetch_upstream_sources.py --help` 查看重取入口；模型仍按实际采用的推理方案单独准备。

## 选择结果

源码归档以提交号固定供对照；实际运行依赖以发行版锁文件固定。二者不默认视为同一时刻版本，兼容性以已安装包和实际链路验证为准。

采用 **Pipecat 1.15.0 + 官方浏览器 client-js 1.16.0 + websocket-transport 1.8.2**。这是对本机兼容性、已有服务复用和交付复杂度的工程选择，不是声称在统一硬件 A/B 测试中击败所有项目。

| 对照项目 | 源码中有价值的机制 | 本项目采用方式 / 选择依据 |
| --- | --- | --- |
| Pipecat | FrameProcessor、服务取消、输出队列、VAD、Local Smart Turn、原生 backchannel frame、RTVI、WebSocket PCM | **直接作为生产内核安装使用**，不重新实现框架；Windows Python 3.12 已安装并执行真实链路验证 |
| 官方 Pipecat 浏览器库 | 录音/播放 AudioWorklet、PCM protobuf、RTVI 状态、播放中断 | **直接依赖使用**，窄适配层处理显式开麦、音量、设备释放与角色口型；依赖锁定并保留小型约束补丁 |
| Hugging Face speech-to-speech | CancelScope/任务代次、连续音频、AEC3、可组合 ASR/LLM/TTS | 机制参考；其完整运行矩阵和重型模型要求不能直接等同本机 Windows 可用。其 Realtime truncate 路径存在空实现，不能据此承诺精确已听历史 |
| LiveKit Agents | RTC 音频、轮次与误打断恢复、多服务插件 | 候选替换路线；本轮不额外引入 RTC 服务和网络端口，也未把 local plugins 的 Linux/CUDA 能力当作 Windows 兼容性证据 |
| Open-LLM-VTuber / Web | 统一音频管理、interrupt-signal、队列清空、角色状态 | 参考角色应用交互；不复制其定制许可前端，也不再自写一套类似语音队列 |
| AIRI | 实际 Live2D 渲染修补、MAGIC 待机/说话动作 | 角色层已直接复用，固定版本、文件和许可另见 AVATAR_OPEN_SOURCE.md；没有声称引入 AIRI 完整应用 |
| VoiceManager | 原生 PCM、interim、任务代次、语音服务拆分 | 参考服务边界；其推荐 Linux/CUDA 路径不能直接解决当前 Intel Windows 部署 |
| HermesConsole | 终端语音与 AEC 处理 | 其中 AEC 实现面向 Android，不能移植后就声称桌面外放 AEC 已通过 |
| Amadeus | 回声保护与打断策略 | 只比较机制，不复制 AGPL-3.0 实现到当前应用 |
| whisper-loop | 异步识别与整句任务 | `to_thread` 不能保证抢占原生识别，不能消除本地模型取消的物理限制 |
| Edge-Voice-Assistant | epoch、PCM、Kokoro、播放边界 | 参考验证方法；原生 ASR 解码同样不能由取消 HTTP 强制中止 |
| Fulloch / 其他数字人应用 | Windows CPU 路径、流式实验与形象集成 | 已取得源码供按模块核对；未把实验性功能直接作为生产默认项 |

模型项目（SenseVoice、FunASR、Whisper、CosyVoice、Qwen、MiniCPM-o、Moshi、VoxCPM、Kokoro 等）与完整语音调度框架不同。取得源码不表示必须同时加载所有模型。继续复用已验证的 SenseVoice/VITS，可以避免为了更换编排层重新下载和运行全部重型推理栈。

## 实际运行边界

```text
官方浏览器录音 worklet → 16kHz PCM16 / 官方 protobuf WebSocket
  → Pipecat transport / Silero VAD
  → 本地 SenseVoice HTTP 适配（完整片段识别）
  → 中文窄附和策略 / Pipecat 原生 UserBackchannelFrame
  → Pipecat 用户上下文聚合 / 默认 Local Smart Turn v3.2
  → Pipecat DeepSeekLLMService（自定义地址走 OpenAILLMService）
  → Pipecat TTS 服务 / 本地 VITS HTTP 适配
  → 框架 PCM 输出队列 → 官方浏览器播放 worklet
  → 实际播放波形 → Live2D 口型
```

`.venv-voice` 运行网关和 Pipecat，`.venv` 运行 8766 本地语音及可选本地 LLM。两者通过回环 HTTP 连接，以免框架依赖和 OpenVINO/sherpa 硬件运行时互相影响。锁文件分别维护。生产浏览器入口为 `/ws/voice`，使用官方协议，旧自研 JSON/WAV 轮次协议退役。

框架负责音频队列、取消传播、流式文本聚合、轮次和状态事件。自研部分仅承担已有设置/持久化、本地推理 HTTP 适配、中文窄附和判断、Live2D 与设备生命周期。中文策略不是通用语义模型：仅在机器人说话期间，最终转写为有限的短附和（如“好的”“对”“嗯”）时发原生 backchannel frame，其余有效转写交给框架启动新轮次。机器人说话期间检测到人声先降音量，最终转写确定真正插话后再硬打断。

## 官方浏览器库的兼容修复

保留固定版官方 worklet 与播放器，补丁和窄适配解决本机实测缺陷：

1. 显式请求浏览器 AEC/降噪/自动增益，避免 WavRecorder 的默认 `audio: true` 没有表明应用要求。
2. 录音 analyser 连接零增益输出，使当前 Edge 真正拉取录音图。隔离 A/B 中未连接时 1 秒非零回调为 0，连接后为 25；零增益不会回放麦克风声音。
3. 官方 worklet 原先等待首次非零样本才发送数据，会丢掉起始静音。改为 recording 期间连续发送完整 PCM，让服务端 VAD 先收到前导静音；没有改变采样格式、协议或重新实现采集器。
4. 播放器初始化不阻塞等待自动播放授权；连接先完成，点击发送或开麦时恢复输出。普通 Edge 策略验收不使用放宽 autoplay 的启动参数。
5. 应用显式开麦，停止/断线释放音轨。断线使用可取消退避重连，重连不自动开麦。嘴部跟随官方播放器 analyser；表情关键词来自输出队列 TTS 文字，只是近似句子时序。

真实浏览器验收使用原生文件虚拟麦克风。此前跨 AudioContext 的合成 MediaStream 夹具发生音频开头丢失，已淘汰该夹具；不能把那个失败波形推断为物理麦克风质量。约 0.47 秒“好的”曾漏检，保留前导静音补丁后同一短句完成识别、原生 backchannel 路径且不打断回复。此为受控样本通过，非真人误打断率评测。

## 仍需如实区分的能力

- Smart Turn 是实际接入的语音收尾模型，但当前 SenseVoice 仍在完整 VAD 片段后给最终文字，因此不能承诺开口即语义打断。完整一句话加识别时间仍影响硬打断。
- 本地 VITS按框架聚合的文本段执行原生callback PCM，只有404/501才回退完整WAV。它仍是按段调用，不能称持续文本双向输入；CosyVoice2真实generator实测首PCM12.45秒/RTF6.19，尚不适合本机低延迟默认链。
- 框架取消会中止旧管线和网络等待；已进入 sherpa/OpenVINO 的原生计算仍持锁到退出或回调取消点。不能将停止播放等同设备立即停止推理。
- 官方播放器worklet逐context完成消费后精确ACK，服务端只保存连续已确认前缀并保持原始轮次顺序。诊断返回 `playback-confirmed-contiguous-tts-context-prefix`。它是浏览器音频图消费，不是声卡或逐字已听测量；硬误打断原音续播仍未实现。
- 浏览器请求 echoCancellation、noiseSuppression、autoGainControl。没有在物理扬声器/麦克风下测量残余回声，不宣称 AEC3 或外放免误打断已经达标。
- 本机 NPU Whisper 未通过中文质量门槛，目前仍使用 CPU SenseVoice/VITS。实验双语流式 Zipformer 仅留在 speech 分支，尚未作为默认路径引入。
- 无 DeepSeek 密钥时提示配置错误；受控本地 SSE 验收不作为 DeepSeek 云端性能证据。

## 许可与来源

Pipecat、官方 client-js 和 transports 使用 BSD-2-Clause；上游 wavtools 的 MIT 声明随包保留；Smart Turn 模型许可和组件信息随官方包保留。本项目通过包依赖复用，没有剥离包内许可文件。官方录音器的浏览器音频约束补丁保存在 `web/patches/`，与固定版本一起可复现。AIRI 的 MIT 文件与 Cubism/角色独立授权继续按既有说明保留。完整归档仅用于本地审查，不能将下载自动理解为允许重新分发其中所有素材或模型。

最新验证方法与结果见 [VALIDATION.md](VALIDATION.md)。旧语音机制的测量保留在 [VOICE_AUDIT.md](VOICE_AUDIT.md)，仅代表替换前实现。

2026-11-06 补充：本地声纹直接调用 sherpa-onnx ERes2Net/Silero，模板质量机制参考 EvatarFramework；口型引入按时间平滑和增益后短窗口；检查了 HF Windows WASAPI、EdgeVoiceAssistant 双工 AEC 与 LiveKit APM。已经进入生产的功能、固定模型来源、AEC 未采用原因和实测结果见 [AUDIO_ENGINEERING.md](AUDIO_ENGINEERING.md)。HF 当前固定源码含 Windows WASAPI，不应把它概括成仅支持 Linux；运行其完整重型模型栈仍需另外验证。
