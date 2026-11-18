# 语音与打断机制审计（2026-11-05）

> 历史报告：以下测量针对替换前的自研 JSON/WAV/epoch 管线。新语音内核为 Pipecat 与官方浏览器客户端；当前方案见 [VOICE_OPEN_SOURCE.md](VOICE_OPEN_SOURCE.md)，新验收见 [VALIDATION.md](VALIDATION.md)。不要将旧播放回执、持续时长打断或延迟数字套用到新框架。

**结论：基础语音插话链路可运行，可靠性问题已修复一批；目前还没有达到调研文档要求的自然轮替、附和不中断、外放稳定和低延迟恢复。** 不能把本地停止播放、网络请求取消和底层模型停止计算当成同一件事。

调研附件作为需求和候选方案参考，不直接采用其中的模型名称、性能数字或命令作为事实。本次审查实际前后端、本地语音服务、依赖源码与固定版本上游资料，并执行隔离测试。主分支集成，`feat/frontend`、`feat/backend`、`feat/speech` 三个 Git worktree 分别负责实现与回归。

## 当前真正运行的链路

```text
浏览器持续采集（请求浏览器 AEC、降噪与自动增益）
  → 实际 Silero v5 / AudioWorklet
  → 累计约 650ms 静音，提交完整的 16k PCM16 语音片段
  → sherpa-onnx SenseVoice INT8 CPU 整段识别
  → DeepSeek 兼容接口的流式文本
  → 按标点或最长 60 字切片，与 LLM 输出并行
  → sherpa-onnx 中文 VITS CPU，每片生成完整 WAV
  → 浏览器逐片解码、播放，音频分析值驱动口型
```

本地 ASR/TTS 都真实运行，但这不是流式 ASR 或模型原生流式 TTS。云端 LLM 发送文本，不接收连续麦克风音频。NPU 识别此前未通过中文质量检查，目前仍使用 CPU。

打断分两步：Silero 初步检出语音后把播放增益降至原来的 25%；满足 `minSpeechMs=320` 的持续语音后立即清空播放、发送 interrupt。服务端递增 epoch、取消生成和 HTTP 请求，浏览器拒绝旧 epoch 的迟到音频。未达到确认时长的 VAD misfire 可以恢复音量；**已经确认的打断没有语义复核或恢复旧回复的路径**。

## 本轮实测及其边界

### 真实浏览器、虚拟麦克风

`scripts/check_voice_turns.cjs` 在实际生产前端运行，加载真正的 Silero ONNX 与 AudioWorklet；使用 Web Audio 产生的虚拟麦克风流，WebSocket 对端受控。没有调用云端模型，也没有使用物理麦克风或测试房间回声。

合入主要修复后的单次结果，记录于 `artifacts/voice-audit/browser-turns.json`：

| 场景/指标 | 结果 | 能证明什么 |
| --- | --- | --- |
| 虚拟输入开始 → 播放增益降低 | 约 159ms | 实际 Silero 触发了第一阶段降音量 |
| 虚拟输入开始 → 浏览器调用停播 | 约 420ms | 实际持续语音触发本地停播；不是扬声器声学停止时刻 |
| 2.492s 输入缓冲结束 → 完整片段上传 | 约 599ms | 本样本静音收尾的实际开销；缓冲末尾不等于最后一个发声音素 |
| 插话后的旧代 WAV | 拒收 | 没有再启动旧声音 |
| 打断后下一次发言 | 上传成功 | 同一 VAD 实例仍能继续工作 |
| 约 0.793s 的“对，好的。” | **触发 interrupt** | 时长策略不能区分附和和真正换话题 |
| 权限拒绝后重新开启 | 成功 | 实际 VAD 尚未取得节点时销毁没有报错，可以重新初始化 |
| 断线后重连、人工重开语音 | 成功 | 旧轨道结束，新 VAD 的发言上传正常 |

这是包含最终 VAD 资源清理补丁的复测结果。此前几次运行的降音量约 80–101ms、停播约 360–381ms；这些少量事件计时不是 P50/P95、真人误打断率或物理 AEC 性能。合成的附和样本能复现问题，不构成中文语料评测。“嗯嗯”在本机 VITS 的一次输出仅约 74ms，不足以作为有效的人声附和样本，因此没有拿它的未打断现象宣称通过。

### 真实 ASR/TTS、受控模型输出

`scripts/audit_voice_pipeline.py` 使用生产 `Conversation` 实现、临时数据库、真正的本地 HTTP ASR/TTS 和受控 OpenAI SSE 模型输出；播放回执由脚本模拟。主应用的会话、设置和密钥不被修改。

独立执行结果在 `artifacts/voice-audit/pipeline.json`：

| 指标 | 单次结果 |
| --- | --- |
| 输入转写 | “你好，请简单介绍一下你自己。” |
| 完整 PCM 提交 → 第一段 WAV 收到 | 约 1.028s |
| 网关 interrupt 任务完成 | 约 38ms |
| 取消长片段合成后，下一条短文本 → WAV | **约 3.549s** |
| 取消后旧代音频 | 0 条 |
| 历史 | 仅保存已确认的第一片，新一轮正常完成 |

这个测试说明“停住旧声音”和“下一轮马上开始”仍有差距。sherpa 回调可以取消后续合成片段；**已经进入原生推理的单个片段仍可能运行数秒，占有模型锁**。排队取消和回调取消已改善问题，不能宣称实现了任意时刻抢占推理。上述 1.028s 是受控模型链路数据，不是 DeepSeek 云端延迟；3.549s 也不是统计分位值。

本轮另一次组件样本在当时系统负载下，9/26/156 字 TTS 分别约 0.557/1.694/10.516s，生成音频约 1.51/4.48/28.93s；对应 ASR 约 0.189/0.320/1.407s。仅作长任务占用的量级说明，不作稳定速度承诺。短句、长句韵律与真人识别质量仍需另测。

## 与固定版本开源实现对照

对照是源码或上游说明的机制比较，没有在相同硬件上完成这些完整应用的 A/B 跑分。没有因为项目名称就推定它自动解决中文附和、回声或模型抢占。

| 开源来源 | 核对到的机制 | 当前项目与它的关系和差距 |
| --- | --- | --- |
| Open-LLM-VTuber-Web | `use-interrupt.ts` 调用本地停播和口型清理、清空任务队列、发送 `interrupt-signal`；`audio-manager.ts` 统一持有当前声音引用 | 我们的本地停播、清队列、epoch 拒收具有对应机制，并增加按完整播放片段确认历史。本次核对文件不能证明其有中文语义附和能力。没有复制其定制许可前端 |
| Hugging Face speech-to-speech | 固定版本 Realtime 说明中，`CancelScope` generation、流式处理逐 token 检查 stale、带代次音频输出、队列 flush；本地客户端另有 AEC3 音频进程 | 我们有 epoch 和队列取消，但模型输出仍按完整 WAV，ASR 整段识别；没有接入它的语音核心和显式 AEC3 播放参考链路 |
| Pipecat | 固定版本示例把 `SileroVADAnalyzer` 与 `MinWordsUserTurnStartStrategy(min_words=3)` 接入轮次管理 | 我们目前只用持续时长确认。示例体现声学检测与轮次策略可分离，但“3 个词”不能直接当作中文附和解决方案，需要中文转写、明确规则和实测 |
| LiveKit Agents | `test_false_interruption_resume.py` 测试误打断暂停/恢复，并等待 end-of-turn 决策，防止恢复定时器与真正提交轮次竞争 | 我们在确认后直接销毁旧播放，无法恢复；没有对应的可暂停输出和语义轮次生命周期 |
| AIRI | 已复用固定版本的 Live2D 渲染补丁、MAGIC 动作及配置，详见 AVATAR_OPEN_SOURCE.md | 这是形象部分的实际复用，不代表继承了 AIRI 整套语音对话编排 |

固定来源及可复查链接：

- [Open-LLM-VTuber-Web / use-interrupt.ts](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/hooks/utils/use-interrupt.ts)、[audio-manager.ts](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/renderer/src/utils/audio-manager.ts)。后端与前端分仓、许可分开核验。
- [HF speech-to-speech / Interruption Handling](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/src/speech_to_speech/api/openai_realtime/README.md#interruption-handling)、[echo-cancellation.md](https://github.com/huggingface/speech-to-speech/blob/5108a3eacea81298a9dc62d5179abcacfb8119f1/docs/echo-cancellation.md)。Windows 客户端 AEC 需要 WASAPI、收发匹配的采样率，且有时钟漂移等限制；不是打开一个选项就保证效果。
- [Pipecat / interruption-config 示例](https://github.com/pipecat-ai/pipecat/blob/de8998789d5690073ddd1dafcec7268839af8153/examples/turn-management/turn-management-interruption-config.py)。
- [LiveKit / false interruption resume 测试](https://github.com/livekit/agents/blob/652eee4ea809ee524fb0ada2383d06eebc3d93a0/tests/test_false_interruption_resume.py)。框架、语义检测模型各自许可需单独核验。

本轮下载的对应文件保存在忽略目录 `artifacts/voice-audit/references/`；它们是比较材料，没有加入应用运行时。

## 已修复的确认缺陷

1. 用户从 AI 播放期间开始讲话，但 AI 恰好在确认语音前自然结束时，原先可能丢掉整段用户发言。现在确认语音后仍提交该发言。
2. 麦克风启动、停止、断线竞争可能遗留采集或异步回调。现在有启动代次、停止清理，断线停止采集，迟到回调失效；固定 vad-web 版本及可复现依赖补丁，修复尚未初始化节点时 destroy 报错造成的模型资源泄漏。
3. 前端可以积累超过后端 30s 限制的完整语音。现在约 29s 主动停止并提示；不会偷偷截断上传。**这仍不是连续长讲话支持，超长未提交内容需要重说。**
4. WAV 解码或播放启动失败原来只写 console，服务端可能一直等待 ack。现在通知 `playback.failed`，清空旧响应并保留此前已听历史。
5. 除 4 条待合成文字外，原来已发出的音频没有播放背压。现在最多 4 个未确认音频片段，完整播放回执释放容量。限制按片段数，尚未按音频秒数或总字节预算。
6. LLM 在已播放一部分之后出错时，已听历史可能迟至下一次 interrupt 才保存。现在处理已确认或稍后确认两种情况。
7. 两个窗口可以同时向同一会话写历史。现在单进程部署中拒绝同会话的第二个活动 WebSocket，断开后可重连。
8. 本地语音的已取消排队任务原先继续等待模型锁并照常执行。现在每类最多 3 个在途请求，等待超时、断连检测及取消检查；运行中的任务持锁到原生退出，避免并发破坏引擎；sherpa 回调尽早停止后续片段。
9. 单个 SSE 增量包含超长且末尾带标点文本时，原先可绕过“60 字分句”边界。现在大增量和逐字流都保留完整文本且每片最多 60 字。
10. 旧浏览器全链路脚本仍等待 Haru 模型、并写入实时设置。现在等待实际模型加载标记，只读检查设置诊断，不覆盖用户配置。

## 仍阻碍自然体验的项目

| 优先级 | 缺口 | 对用户的影响 | 建议路线 |
| --- | --- | --- | --- |
| 高 | 附和与真正插话的语义区分、确认后的误打断恢复 | “对，好的”也可能永久切断回复 | 复用成熟编排的暂停/提交/恢复生命周期，接入中文转写和轮次策略，测试附和语料；不能只增加时长阈值 |
| 高 | 原生单片段推理不能即时停止 | 旧声音停了，新回答仍可能等数秒 | 比较可取消的流式 TTS 或受支持的子片段回调；缩短合成片段需要兼顾韵律，不能靠提前放开锁 |
| 高 | 外放 AEC 未验证 | AI 自己的声音可能被当成插话，音量反复波动 | 先做实际外放/双讲测试；必要时接入带播放参考的成熟 AEC 或本机音频桥，核验设备时钟和延迟 |
| 高 | 没有语义结束判断 | 650ms 思考停顿可能被抢答，快说完又需额外等待 | 采用适合中文的语义轮次组件并与 VAD 配合，比较慢说、犹豫和连续修正 |
| 中 | 完整语音段识别、整片 WAV 合成 | 首声需要等识别和整片合成，长句慢 | 对照 sherpa 流式识别和成熟流式 TTS 适配；保留单一音频所有权 |
| 中 | 没有时间上限的首短语刷新，下一 WAV 在上一片结束后才解码 | 无标点模型输出首声延后，句间可能有解码空隙 | 加时间预算的分句/缓冲机制，预解码或音频时钟调度，测真实 underrun 与句间间隙 |
| 中 | 只按完整片段保存听到的内容 | 被打断片段中已播的一部分不会留在上下文 | 后续增加播放进度与文本/音频对齐；不能直接按字符比例假装知道已听文本 |
| 中 | 长讲话上限和断线后人工重开语音 | 不能无缝长讲话，断线中内容不保留 | 采用连续流式传输及明确的重连轮次；当前保护性停止需在 UI 明示 |
| 中 | 没有播放回执超时监测 | 后台休眠或客户端不回执会让本轮等待，虽有数量上限仍需人工打断/重连 | 加可观测的播放进度与超时恢复，区分缓冲、播放和休眠 |
| 中 | 本地 VITS 声线/韵律、粗粒度情绪、没有角色声音评测 | 有声可用，未证明具有角色所需的自然表达 | 固定中文文本对比音色、韵律、实时率及资源占用，再换模型 |

升级时优先选择**一套**成熟语音编排核心做适配验证，保留现有 DeepSeek、Live2D 和本地设置，不同时拼接多套采集、播放及取消控制。HF 的取消/本机音频路线、Pipecat 的轮次策略和 LiveKit 的恢复状态机提供不同参考；当前尚未完成其中任何一套完整语音核心的集成，不能把此次源码比较表述成已经替换完成。

## 验收状态

本轮前端测试、Python 回归、生产构建、真实 Silero 虚拟麦克风测试和真实本地 ASR/TTS 取消恢复测试均有执行记录。VAD 生命周期单元测试使用模拟回调，浏览器测试使用真实 VAD，二者不能混称。测试数与最终提交见 VALIDATION.md。

以下门槛仍未通过：DeepSeek 官方真实语音对话性能、真人连续 20 轮及 30 分钟对话、耳机/扬声器双场景、短附和误打断率、物理双讲 AEC、噪声及方言识别、设备拔插与网络故障完整恢复。现有离线模型 20 轮首 WAV 数据不包含 VAD 收尾、浏览器和声学延迟，也不是本次云端结果。

复测入口为 `scripts/check_voice_turns.cjs` 与 `scripts/audit_voice_pipeline.py`。前者需要 Playwright 路径、Edge、本地服务，以及现有 `artifacts/live-smoke/input.wav`、`reply-1-2.wav` 测试样本；后者需要本地语音服务和 `input.wav`。它们不请求云端 LLM、不写实时设置。完整云端 UI 脚本 `scripts/test_ui.cjs` 另需有效配置，不能在缺少密钥时列为通过。
