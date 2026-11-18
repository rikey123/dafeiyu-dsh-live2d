# DSH 迁移功能验收矩阵

基线为 `G:/dafeiyu` 的当前工作区源码（包括未提交变更），不是本 worktree 的旧 HEAD。DSH 迁移由集成者实施；下表是验收要求，不表示迁移已经完成。除下述记忆例外，原有功能、前端样式和交互均需保留，具体协议以当前 `docs/PROTOCOL.md` 为准。

**用户明确的记忆例外：**插件模式完全跟随 DSH 当前配置，不保留或迁移原应用记忆逻辑，不额外安装记忆 MCP，不导入旧 `memories`，也不把本地 memory 拼接进模型上下文。移除原手动记忆面板及其接口属于授权变更，不算功能损失。验收时应检查实际配置和调用链，以确认没有上述额外迁移或注入；不得为此读取用户聊天、旧记忆内容或密钥。会话和播放确认历史仍需保留，它们不属于这项例外。

本次说明审计依据 2026-11-14 主工作区已集成的插件和脚本，以及本机实际安装的 **DSH 0.2.2-rc.1** 包。安装、运行与回滚命令见 [DSH_PLUGIN.md](DSH_PLUGIN.md)。主集成者已通报特定短文字语音链路及浏览器 smoke 通过，证据和未覆盖范围见下方；不等于整张矩阵或真人语音全链路通过。

| 用户能力及源码线索 | 迁移验收要求 |
| --- | --- |
| 前端：`web/src/App.tsx`、`style.css`、`ui/` | 比较固定及窄窗口截图，验证中文文案、控制、面板、状态、错误、键盘操作和偏好；插件模式移除手动记忆面板是唯一已授权的界面例外。 |
| DSH 原生面板：`plugins/dsh/src/client.js`、`web/src/embed.tsx` | 注册 `main` / `sidebar.panellist`，通过浏览器原生 `attachShadow({mode:'open'})` 建立 ShadowRoot，无 iframe；同源资源在 `/dafeiyu/` 下加载。面板失活或页面隐藏时卸载 App、释放音频；恢复面板不得自动开启麦克风。 |
| 会话与文字：`server/main.py`、`storage.py`、`App.tsx` | 在隔离数据目录验证创建、切换、删除会话（DSH 原生为 archive，不承诺永久删除 trace），文字输入、流式回复、停止、刷新和会话隔离；历史遵循播放确认规则。原生 create/read/archive 已有下方 smoke 结果，其他边界不能据此自动通过。 |
| 人格与模型设置 | 人格提示及语音设置保存恢复；插件使用 DSH 当前模型选择、原生工具权限和会话持久化，模型变更在请求边界生效，不从 gateway 使用独立版 LLM 地址和密钥；独立版原有模型设置仍保留。已确认会话历史进入上下文，不拼接原应用本地记忆。 |
| DSH 记忆归属与旧库边界：`server/dsh.py`、`server/main.py`、`plugins/dsh/src/harness.mjs` | 记忆完全跟随 DSH 已有配置；旧记忆面板不显示、不发起旧 memory CRUD，已认证的旧接口返回 410。DSH 会话从原生持久化与插件投影获得，不读取或导入旧 SQLite 聊天和 memories；语音、人格等设置仍可使用原配置库，不能把这描述成完全不打开 SQLite。 |
| 密钥、来源、服务状态 | GET 仅暴露密钥已设置标志；空值保留、显式清除，非法输入不泄漏；默认回环绑定，分别显示配置、实际加载、设备和未探测状态。 |
| GPU GPT-SoVITS / IndexTTS：`tts_policy.py`、`model_tts_sidecar.py` | 验证各自模型身份、真实 CUDA 预热和驻留、模型切换、24k PCM 播放确认、加载失败及繁忙提示。当前保存的 GPT-SoVITS-v5-turbo 已通过一次短文字输入到浏览器播放确认的真实链路；不扩展为 IndexTTS、其他模型或切换/失败/停止续说边界已通过。 |
| MOSS-TTS-Nano CPU voices：`tts_voices.py`、`MossVoicePicker.tsx` | 目录来源、预设选择、保存与重连、目录不可用提示；真实 CPU ONNX 输出及播放确认另验。目录存在不等于推理就绪。 |
| TTS 路由与 API：`tts_policy.py`、`speech/api_tts.py` | legacy/auto/cpu/gpu/api 优先级；GPU 不可用时按协议在下一回复切 CPU，不重播已听片段、不自动转付费；独立 API 地址、模型、音色、密钥、速度及超时，用本地模拟对端覆盖 PCM、错误和取消。 |
| MOSS Live：`moss_live.py` | 受控对端验证 attach、会话配置、16k 输入/24k 输出、转写归属、LLM 委派及去重取消、播放 chunk 回执、停止和历史；音频专用，owner/SystemOne 冲突明确拒绝。 |
| duplex / pipeline：`pipecat_voice.py`、`conversation.py` | duplex 播放期间保留输入和打断，pipeline 播放期间输入静音；均使用所选 LLM/TTS，切换重连且不自动开麦。 |
| 本人声音：`OwnerVoice.tsx`、`speech/speaker.py` | 2–5 条样本录入、质量与一致性检查、启用和删除；失败不覆盖旧模板；非本人或不确定不进入识别、LLM、历史；重连不自动开麦。声纹不是身份认证。 |
| 流式 ASR 和中文插话：`streaming_asr.py`、`pipecat_turns.py` | 实验开关和模型不可用提示；稳定有意义的部分结果可提前打断，仅最终结果入历史；附和不抢话，owner 筛选时不提前打断。 |
| SystemOne：`systemone.py`、`systemone_pipeline.py` | 两供应商独立密钥、音频开关、超时、置信度与插话阈值；模式互斥、失败回退、取消及超时；情绪、表情、动作使用语义白名单，按播放 epoch 生效，手动设置优先。 |
| 主动接话：`systemone_initiative.py`、`systemoneSettings.tsx` | 默认关闭；七参数边界、保存、重置、变更重连；仅 duplex + SystemOne + 非 owner 生效；每段最多一次、冷却、等待保护、有限探测和短句限制；停止、断连、新发言及关闭采集取消过期待决工作。 |
| Live2D、衣装、背景、主题、口型：`Avatar.tsx`、`avatar/`、`ui/` | 衣装、手势、表情、背景动画、主题与偏好保存恢复；听取/思考/说话驱动、手动优先；实际 PCM 驱动 AIRI/local-vits 口型，停止、溢出、重连归零。 |
| 播放确认历史：`playback.py`、`web/src/playback.ts`、`voice.ts` | 仅 worklet 实际消费的连续上下文进入助手历史；验证 start/boundary/ACK、采样率、重复、越界、乱序、截断、停止、重连与队列上限；生成文字不能冒充已播放文字。 |
| 连接与设备：`voice.ts`、`microphone.ts`、`reconnect.ts` | 初始不开麦；设备选择、权限失败、停止与重连；过期异步操作失效、输出队列上限、降音、错误提示和中断恢复。 |
| 启动与服务：`scripts/run.py`、`voice_services.py`、`doctor.py` | 本机启动、状态、预热、切换和退出只管理所属进程；清晰报告不可用；指标不包含对话内容，不把预测、CPU 回退或未测延迟说成 GPU/NPU 推理。 |
| 安装、卸载与回滚：`scripts/dsh_plugin.ps1`、`plugins/dsh/src/runtime.mjs` | 用显式 rc1 `bin.js`；Build 输出到 `web/dist-dsh`，Prepare 生成临时 overlay，Install/Uninstall 只管理已有 profile 的插件标记块并保存备份，不用模板整体覆盖 profile 或重配 provider/MCP/memory。当前 Start 源码已检测已安装的 managed block 并跳过重复 overlay；持久 Install + 重启尚待实测。重复操作、原空补丁恢复及其他配置保留需在合成 profile 上验证；源码留在 G 盘、模型和环境保持原位置。只加载插件不启动本地语音，首个已认证 API/WS 请求才触发，正常由进入面板产生；独立版回滚前释放 8765，保留旧数据。 |
| 历史工具：`speech/README.md`、`optional_voice.py` | 区分当前接口与历史研究；MFA 现已从生产对齐协议退役，不能因历史文件存在就声称它是当前可选功能。 |

七参数默认值及范围：意愿 `threshold` 0.9 [0.8, 0.99]；最少听取 `min_speech_ms` 3000 [1500, 15000]；冷却 `cooldown_s` 20 [10, 120]；等待保护 `wait_threshold` 0.2 [0, 0.5]；最大回复字数 `max_reply_chars` 48 [8, 80]；探测间隔 `probe_interval_ms` 3000 [1500, 10000]；最多探测 `max_probes` 3 [1, 6]。整数项拒绝非整数，概率必须有限。`systemone_interrupt_threshold` 是另一个插话参数。

## 静态检查和证据边界

运行 `python scripts/check_dsh_feature_parity.py --baseline G:/dafeiyu --target <迁移工作树>`。脚本只读取显式列出的源码，使用 Python AST 对比符号、设置字段、HTTP/WebSocket 路由及 `voice.*` 事件，比较关键前端文件哈希。原应用手动记忆的三个路由及其明确列出的符号被排除，其他功能不被豁免。缺失文件、语法错误和其他结构差异列为 `gaps`。

共享前端文件发生差异时列入独立的 `reviews`，需要人工区分授权的记忆面板删除和其他样式、交互变化；单凭哈希不能判断差异原因，不能将其自动认定为功能损失或通过。有缺口或待复核时退出 1，均无时退出 0。输出不包含源码内容。相同符号或事件仍可能是空壳；此脚本不能证明功能等价、DSH 配置正确、未导入记忆或未注入上下文，必须审查实际迁移实现并运行相应隔离测试。

DSH 架构迁移也可能改变内部符号和共享前端文件；结构差异需对照本矩阵逐项复核，不能将当前主工作区与自身比较的零差异当作迁移证据。安装文档中的命令针对集成后的 `G:/dafeiyu`，本审计 worktree 可能缺安装脚本和近期功能，不应从旧分支执行安装。

建议依次进行静态审查、隔离数据目录下的单元和协议 fixture、浏览器及视觉检查，再单独安排真实设备与外部服务测试，记录环境、设备、样本数和 P50/P95。模拟服务不能证明真实供应商可用，健康状态不能证明真实推理或声学效果。

## 已验证：真实 DSH / 浏览器 smoke 与短文字语音链路

以下记录主集成者于 **2026-11-14** 通报的真实运行结果。本审计只读核对主工作区的脚本与代理实现，不重跑模型、GPU 或浏览器 smoke，不读取入口日志、用户会话正文或凭据；运行结果和计数来自主集成者，不冒充本审计独立复测。

`scripts/check_dsh_plugin.cjs` 默认不提交模型提示词；显式设置 `DSH_TEST_LIVE_TURN=1` 才提交一次短文字输入，可能消耗真实 LLM 配额并运行当前本地 TTS。两种模式均禁止麦克风采集；主集成者报告两种模式均通过。源码也已修复 WS 升级响应漏转 `Sec-WebSocket-Extensions` 导致 Chromium 1006 的问题。

| 已验证项目 | 本次结果及严格范围 |
| --- | --- |
| 真实运行环境 | 已安装的 DSH **0.2.2-rc.1**、真实用户 profile；不是 mock harness 或仅健康检查。 |
| 特定 LLM → GPU TTS → 浏览器链路 | `deepseek-flash` → 当前保存的 **GPT-SoVITS-v5-turbo**；浏览器收到 **55 PCM frames / 107735 wire bytes**。这只证明本次所选模型的短文字输入路径，不代表其他模型或语音输入通过。 |
| 播放确认与原生历史 | worklet 确认消费/播放后，DSH 原生会话出现 **7 字 assistant 已播 prefix**；不记录正文。wire bytes 不是 PCM 样本数、时延或实际扬声器声学测量；worklet 回执也不代替真人听感验收。 |
| 原生会话 | native create/read/archive 通过；不等于永久删除、任意并发隔离或全部切换/恢复边界已测。 |
| 面板生命周期 | inactive 释放音频资源，reactivation 后再次 ready；不等于 DSH 父进程退出时全部服务进程树已收敛。 |
| 不自动开麦、记忆例外 | **0 麦克风请求、0 前端旧 memory 请求**，已认证旧 memory 路由 **410**；这些观测不单独证明内部从未读旧库或全部上下文注入路径，仍需保持源码/配置边界审查。 |
| 浏览器与同源资源 | **0 浏览器 error / 0 资源失败**，普通及 live smoke 通过；不替代全量样式/交互回归、鉴权负例或真人设备测试。 |

## 仍待验收与收敛工作

- **真实设备与其他语音模式：**真实麦克风/流式 ASR、声学 AEC、owner 声纹、duplex/pipeline、真人打断与主动接话七参数、SystemOne 情绪/表情/动作和实际听感仍待真人验证。短文字输入不能证明上述链路。
- **其他模型及外部服务：**IndexTTS、MOSS CPU voices、其他 TTS 路由/API、远端 MOSS Live 和其他 LLM/TTS 供应商仍需逐项实测，不将本次成功推广为全部付费 API 已通过。历史 `docs/FEATURE_AUDIT_2026-11-14.md` 曾报告 GPU 停止后立即续说可能返回 503；本次短文字 smoke 不覆盖该边界，是否修复仍需复测。
- **安装与退出的补充实测：**集成后已通过持久 Install + Start（无重复 overlay）及真实面板 smoke；实际 Uninstall 与安装前备份哈希完全一致，随后已重装。Windows EOF、supervisor 强杀、borrowed 不受影响的进程树 fixture 和真实 DSH 意外退出后的全部自建服务释放通过。证据见 `DSH_ACCEPTANCE_2026-11-14.md`。standalone 实际切回运行仍待独立验收，不用构建或 fixture 替代。
- **全量迁移：**矩阵中的视觉/交互、会话隔离、HTTP/WS 鉴权负例、取消/背压、模型切换与错误恢复等，仍按各自证据逐项验收；没有时延测量、P50/P95 或 NPU 推理结论。不宣称全部功能或真人语音全链路成功。
