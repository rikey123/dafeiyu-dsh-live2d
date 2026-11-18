# DSH 原生聊天与数字人适配

本轮以本机 DSH `0.2.2-rc.1` 的 Session Controller、Conversation Factory 和 Slot 合同为准，不修改 DSH 安装源码。

## 所有权

新增的共同兴趣、安静后主动搭话及连续直接看画面模式见 [COMPANION_PRESENCE.md](COMPANION_PRESENCE.md)。语音环境提示优先说明先自然回应、再执行等待操作，耗时任务优先交给原生子智能体；没有程序强制分派或新任务队列。完整上游人格原文不变。

- DSH 拥有会话、原生日志、人格、记忆、工具权限、任务和子智能体。普通输入通过 `sessionController.prompt(mode: queue)` 接纳；插件不创建第二个普通 Agent、不排自己的任务队列。
- 语音打断/停止仅停止声音与迟到的播报片段（包含已接纳但尚未开始输出的请求）；不会抑制之后无关的父会话通知。关闭语音订阅、切换面板或插件卸载，不会取消已提交的 DSH 工作。原生输入框的显式 Stop 仍是 DSH 的任务停止操作。
- 系统提示仅添加实时语音环境背景。身份与人格仍来自 DSH 人格插件；原应用 `system_prompt` 不再覆盖普通 DSH 会话。
- `dafeiyu_harness.sessions` 的旧表保留用于会话归属及兼容隔离 preview；普通聊天不再从 `played` 投影读取历史。播报确认不是主会话历史。兼容文本读取使用 DSH 的 `isAppendSurfaceEvent` / `deriveEventMessage`，不将压缩替换副本当作新聊天。

## 前端

保留 Live2D 舞台、HUD、主题、设置、语音控制及对话区外壳。宿主注入 `nativeConversation.mount(container, sessionId, target)`；`target` 为 `messages` 或 `composer`。

宿主持有一个 DSH Session reference。DSH 主 React 树通过原生 `SessionProvider` 与 `conversation.content` Factory 提供完整会话；Factory 的局部 `views` 座位将 `conversation.session` portal 到记录区域，完整原生 composer 则 portal 到控制台。没有复制 ChatView、Lexical、附件上传、审批、交付物或插件内容解析器。

两个原生座位拥有独立 ShadowRoot，镜像运行时样式并映射本应用主题 token，避免重置舞台样式。切页时卸载可编辑 occurrence，但应用、语音连接和 Session reference 保留；草稿由 DSH 的会话状态保存，回页重新挂载同一原生状态。不会后台保留第二份可编辑输入框。

输入区视觉恢复原版控制台：外框 42px，内部单行 40px、14px 字号，沿用两套舞台主题的边框、透明底色与强调色。仍是同一个 DSH 原生编辑器，不自行提交输入、不复制 Lexical、不接管快捷键、附件、命令或任务。文件入口与发送按钮保留；模型、权限、统计等低频控件通过“更多聊天选项”展开，Escape 可收回。附件、运行活动、任务队列、审批等原生扩展仍保留，多行内容向上增长；不是将原生功能删除来做静态仿制。样式以 rc1 的 `data-composer-*` 边界和少量结构性 CSS-module 后缀定位，不硬编码构建哈希。运行时原生 SVG 图标按引用镜像进对应 ShadowRoot，避免加号等图标跨 shadow 引用失效。

原生注册内容可直接呈现；新增内容类型不需要给本插件增加消息类型分支。复杂工具轨迹仍遵从 DSH 的原生折叠与权限规则。

## 私有语音传输

桥仅绑定 loopback，使用每次启动生成的 Bearer，不向浏览器公开。浏览器仍通过经 DSH owner 认证的同源路由与语音服务通信。

| 路由 | 用途 |
| --- | --- |
| `POST /v1/voice/turns` | 提交普通语音转写；返回 `{accepted: true, request_id}`，不等待模型整轮 |
| `GET /v1/voice/events?session_id=...` | 会话级 SSE，跟随父会话所有公开 assistant 步骤及后续回复 |
| `POST /v1/voice/state` | 注册/注销临时语音环境，不触发模型调用 |
| `GET /v1/voice/context?session_id=...` | MOSS 只读取 DSH persona prefix/suffix、`soul:persona`、独立的语音环境背景及公共聊天文本，不导出完整工具/运行时提示词 |
| `POST /v1/voice/observations` | MOSS 语音观察经原生 context inbox 接纳，不唤醒另一个模型任务 |

SSE 使用 `id:`，支持 `Last-Event-ID`。重连缓存只保存有限的输出传输片段（每会话最多 4096 条/2 MiB、断订阅后最多 60 秒），不是任务或记忆存储。过期游标返回 `reset`，不能重新提交原问题。初连不重播已有历史，15 秒心跳。事件包括 `ready`、`response.start/text/end/error`、`conversation.user`、`turn.end`。只传公开正文，不传推理、工具结果内部文本或原始供应商错误。

原生输入框提交的文字同步到连接内声学上下文及字幕，不重复提交。

主动屏幕评论和用户说话中接话仍用隔离的 preview；普通任务不会因 preview 的结束或取消而被停止。取消插件添加的屏幕工具 guard、第 2 步拒绝和屏幕文字防护提示，所有工具权限交回 DSH。B 站登录、配置及其他操作不再被组合插件统一拒绝，旧的 `allowBilibiliActions:false` 也不再保留此封禁；原插件自动刷站/发帖开关不因此被自动开启。

短评论的字数设置仅用于提示词建议，完整表达优先；不再按标点、字符数切断文本，也不再为 preview 固定 `maxTokens:256`。模型、推理设置和供应商默认预算仍跟随 DSH。连接/超时/资源上限保留，但不是语义质量判断或强制截句。

只有浏览器确认已播报的 preview 前缀，才作为来源明确的 `notice` 经 `agent.inject` 进入 DSH 的原生 context inbox，并立即 flush 持久化；不伪造人类提问、不触发新任务、不另建记忆。notice 包含主动评论类型、发生时间、触发场景、实际累计播报内容、生成结束及打断状态。第一次确认附上触发该评论的原生历史截图引用，后续确认只更新文字；图片字节沿用 DSH 附件存储。旧请求没有截图元数据时只记录已知事实，不补造画面。重复 ACK/持久化重试不重复注入。用户请求的新鲜屏幕图像仍走 DSH 原生附件接纳。

工具/任务/Agent 的失败继续由 DSH 处理和展示；语音订阅仅结束已经开始的公开文本片段，不伪造音频错误、兜底台词或模型重试，不因任务失败关闭订阅。之后 Agent 的公开说明与子智能体回报仍可正常朗读。旧桥的 `response.error` 任务事件也按普通结束处理；真正的文本流缺帧 `VOICE_STREAM_GAP`、桥连接/游标丢失、麦克风及 TTS 故障仍属于语音诊断。底层模型彻底不可用时不能保证 Agent 还能生成说明，插件不会冒充它编造回复。

MOSS 连接时读取当前 DSH 人格和公共文本上下文，登记语音环境；捕获状态及断连清理同步给宿主。前台转写（含明确修订）与完整确认播放的回答以来源明确的原生 notice 入 context inbox，空闲模型不会被唤醒；这些不是伪造的模型 assistant 消息。notice 在 DSH 下个接纳步骤进入正式上下文，不能将待处理 inbox 当作已完成聊天 turn。中断的 MOSS 音频不靠时长推算已听文字。MOSS 跟随同一会话的公开事件，委派读取超时/取消不取消 DSH 任务，迟到的父会话结果仍可同步；不再发送本地人格或拼接的历史给 DSH 作为第二套上下文。

## 验证与边界

### 默认人设与语音环境

默认人设改用 `YUsaltyfish/dsh-onebot-qq` 的完整「蓝色大肥鱼」示例，原文及 MIT 许可保存在 `personas/blue-whale/`，固定提交、来源路径、字数和 SHA-256 记入 `source.json`。安装器读取原文建立原生 `soul-md` 卡，不再生成自写的简短人设。现有实例通过 DSH 原生配置界面切换，保留其他卡片及其会话选择；不重新安装 QQ 插件、不增加记忆系统。

语音环境不是人设的一部分：连接开启后，DSH 动态附加一对一实时语音、文字与语音共用聊天、图片/文件展示、耗时工作可交子智能体的背景；关闭连接后撤下。MOSS 通过私有 context 接口的 `environment` 字段接收同一背景，与完整人格一起交给语音服务，不从本地配置另造人格。

语音背景进一步说明：语音里的查询和操作同样需要实际处理；决定执行时应调用工具，进展和结果按真实执行情况汇报，而不是只口头承诺。主动屏幕评论及接话 preview 在语音环境有效时也取得同一背景。没有新增关键词强制路由、自动重试任务、第二套子代理调度或工具限制；完整「蓝色大肥鱼」人格原文不变。

### DSH 自主看当前共享画面

`view_current_screen` 是注册给 DSH 的原生无参工具。模型可为“看这个”等指代自己决定调用，不必等 System One 识别意图；已有本轮图片时无需重复查看。工具只读取当前会话已经在浏览器授权的画面，不会自动打开共享或麦克风，也不能点击桌面。设置启用屏幕陪玩、连接就绪、视觉模型可用及手动共享仍是前提。关闭 System One 或自动按需截图，不妨碍工具；自动陪玩与文字意图预判仍按原设置运行。

调用经固定、鉴权的 loopback 网关请求浏览器新截一帧，使用 DSH 原生图片接纳、存储与工具输出，不把 base64 填成文本。委派子智能体可经 DSH 不可变的 `subagent` 父会话关系使用同一共享；普通分支和无关会话不能拿其他会话画面。停止共享、切换流或断连使等待截图失效；不会拿旧图冒充实时画面。普通语音打断只影响声音，不取消已经由 DSH 接纳的工具任务。

新增验证：插件的真实 `defineTool` schema 注册及 `LocalAttachmentStore` 图像解码/持久化测试不调用模型。`scripts/serve_screen_tool_acceptance.py` / `scripts/check_dsh_screen_tool.cjs` 使用真实编译前端、Edge、RTVI/Pipecat 网关及原生工具附件，但输入为合成 canvas、模型为离线元数据夹具；验证新帧、子智能体归属、System One 关闭、撤销共享和断连清理。夹具使用 5000ms 截图预算以容纳 headless 软件渲染，不改生产默认值，不证明实际模型决策质量或真人端到端延迟。

- `plugins/dsh/test/native.test.mjs`：原生 admission 所有权、会话后续输出、断订阅不取消、重连游标、早期错误、完整日志、兼容多步骤回复。
- `scripts/check_dsh_native_conversation.cjs` 与 `scripts/fixtures/dsh-native-host.mjs`：隔离 DSH 的真实浏览器验收。原生消息/Factory/编辑器是真实实现，模型输出为离线插入的测试事件；settings 和语音服务使用替身/不启动。验证 Markdown、代码块、表格、窄屏及切页草稿，没有真实模型、麦克风或屏幕采集。另验证真实宿主的 persona assembly 与自定义 notice 的原生 inbox 持久化、不唤醒模型；演示用 surface 追加只在隔离夹具进行。
- 夹具必须显式设置 `DAFEIYU_NATIVE_ACCEPTANCE=1`，不能装入用户 profile。日志中的 owner URL 不可打印或提交。
- 离线测试与 UI 夹具不证明实际付费模型、远程 TTS、MOSS-Live 或外部插件业务成功；这些需要用户在已有配置与权限下验收。

2026-11-15 本轮结果：Python 全套 462 passed / 1 skipped，插件 60 passed，前端 200 passed；TypeScript、独立版与 DSH 构建通过。Python 仍有 Pipecat 弃用及测试替身协程警告，Vite 独立版仍有大包提示。真实隔离宿主浏览器报告无 page error；模型资源未复制、语音服务被禁用，因而夹具的预期 404 / 503 / WS 连接错误不能当作正式语音成功。报告保存在 `E:/Dafeiyu/qa/dsh-native-20261115/`，不得公开包含认证入口的 host 日志。
