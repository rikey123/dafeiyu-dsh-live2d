# DSH 原生数字人插件

**独立发行版（2026-11-16）：**对外安装请先阅读 [DSH_RELEASE.md](DSH_RELEASE.md)。发行版是包含预编译前端和语音后端的标准 npm / `dsh.bundle` 包，使用外部 `DAFEIYU_HOME`；不依赖下文的开发机路径、现成虚拟环境或手工源码 patch。下文的源码安装和历史验收仅供开发与迁移参考。

说明核对日期：2026-11-15。以下命令对应集成后的 `G:/dafeiyu` 当前源码；审计分支的旧 HEAD 不一定包含安装脚本、插件和前端构建入口。本文记录安装方法、实现边界、已通报的特定短文字语音链路结果和待验收项目，不是全部功能或真人语音全链路成功报告。

**原生聊天迁移更新：**现用 DSH Session Controller 与完整 Conversation Factory，细节及本轮验证边界见 [DSH_NATIVE_CONVERSATION.md](DSH_NATIVE_CONVERSATION.md)。下方 2026-11-14 验收保留为历史记录，不能当成本轮改动后的付费模型验收；旧 smoke 脚本中失活释放音频、纯文本输入的断言也不再适用。

## 架构与边界

```
DSH main / sidebar.panellist
  └─ 原前端 App（浏览器原生 ShadowRoot，无 iframe）
      └─ 同源 /dafeiyu/api/* 与 /dafeiyu/ws/voice
          └─ DSH Connection 的 cookie / Host / Origin 准入
              └─ 私有令牌 → Python 语音 gateway（127.0.0.1）
                  ├─ 原 ASR、音色、TTS、口型、声纹、全双工、System One / 主动接话
                  └─ 随机回环端口 + Bearer → 插件原生 DSH Agents adapter
                      └─ DSH model selection、harness、tools / permissions、session persistence
```

普通会话通过 DSH 原生 `sessionController.create/prompt/resolveAgent` 接纳，主界面使用完整原生聊天内容与编辑器；不在插件中重写 agent loop，不从语音 gateway 直连原来的 LLM 地址。不改 DSH 安装源码。原生 harness 保留完整聊天与工具执行 trace；播放确认仅服务于声学状态及隔离 preview，不截断原生会话历史。停止声音、断开语音或切页不会取消已经接纳的 DSH 任务。

`plugins/dsh/src/client.js` 是 DSH ModuleLoader 的 closure-factory 浏览器半面；它从同源 `/dafeiyu/entry.js` 加载原应用，再由 `web/src/embed.tsx` 调用 `host.attachShadow({mode:'open'})`。这是原生 ShadowRoot 中的独立 React root，不使用 iframe；ShadowRoot 隔离样式，不作为脚本安全边界。前端、WASM、Live2D 和音频资源均由 `/dafeiyu/` 路由提供，API 和 WebSocket 也使用该前缀，避免误用 DSH 自身的 `/api`。

**记忆例外：**用户要求不保留本项目记忆逻辑。插件禁用旧 memory CRUD 和上下文拼接，不导入 SQLite 的旧 memories，不安装任何新的记忆 MCP。跟随 DSH 当前配置。数字人的 persona、音色、声纹和 UI 偏好不等于聊天记忆，仍保留。独立版及用户旧数据库作为回滚保留，不删除。

“不读旧库”在此明确指：不查询旧 SQLite 的聊天/记忆内容来建立 DSH 会话，不导入旧 `messages` 或 `memories`，不将本地 memory 注入模型上下文。DSH 自有配置决定其记忆能力；没有配置记忆功能时，插件也不额外安装。当前 Python 仍打开原配置库以读取语音、人格等设置，因此不能声称完全不打开 SQLite。插件会话经 bridge 读写 DSH 原生持久化及插件所属投影；旧记忆面板移除，已认证的旧 memory API 返回 410。独立版原有记忆功能不因插件卸载而删除。

DSH 原生“删除会话”是 archive，不声称永久删除原生 trace。插件只列出自己拥有的会话，不扫描/显示用户其他 DSH 会话。

## 本机版本

按本机实际 **DSH 0.2.2-rc.1** 的安装包接口适配，不把研究仓库的较新接口当作已安装接口。rc1 的 WebRoute 不自动鉴权，HTTP / WebSocket 均必须先 `ctx.connection.admit(req)` 并验证 owner。没有 DSH cookie 的访问应返回 401，非法 Host / Origin 返回 403；Python 的 API / WS 再校验独立随机插件令牌。密钥不进入前端或 URL。

本机 rc1 的 CLI 入口位于 `%APPDATA%/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules/@deepseek-ai/dsh/lib/bin.js`。脚本未传 `-DshBin` 时按入口文件修改时间选择候选，不保证选择 rc1；下面显式固定已核对的安装路径。Loader 支持 profile patch 中以绝对文件路径加载 Host 入口，并从入口所属 `package.json` 的 `dsh.client` 与 `exports["./client"]` 发现浏览器半面，无需把项目复制进 C 盘 runtime。

## 源码安装 / 启动

在项目根目录的 PowerShell：

```powershell
Set-Location -LiteralPath G:/dafeiyu
$dshBin = Join-Path $env:APPDATA 'dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules/@deepseek-ai/dsh/lib/bin.js'
if (-not (Test-Path -LiteralPath $dshBin)) { throw '找不到已核对的 rc1 安装入口' }
./scripts/dsh_plugin.ps1 -Action Build -DshBin $dshBin
./scripts/dsh_plugin.ps1 -Action Prepare -DshBin $dshBin
# 未持久安装时使用临时 overlay；已安装时 Start 不重复叠加。
# 不改现有 profile；另一端口不停止原 DSH。
./scripts/dsh_plugin.ps1 -Action Start -Profile web -Port 3081 -DshBin $dshBin
```

前提是已有 DSH 的 `web` profile、Node 和 npm，以及原项目的前端依赖、`.venv` / `.venv-voice` 和所需本地语音模型。目标 profile 名称不同时替换 `web`。`-DshHome` 默认取 `DSH_HOME`，未设置时取 `%USERPROFILE%/.dsh`；若现有 DSH 使用自定义 home，各次操作都传入同一个 `-DshHome <实际目录>`。脚本不会替用户创建或重配 provider、MCP 或记忆。Build 运行 `npm.cmd run build:dsh` 和插件隔离测试；Prepare 只在项目 `.runtime/dsh-plugin.patch.yml` 写入插件路径及非敏感配置，不启动语音或推理。

若本机 PowerShell 策略禁止执行 `.ps1`，不需要修改系统执行策略。已持久安装的 profile 可以直接从原 DSH 启动器打开，或使用已安装 CLI（目录避开项目根 `.env` 的 bootstrap 配置冲突）：

```powershell
Set-Location -LiteralPath G:/dafeiyu/.runtime/dsh-launch
node $dshBin --profile web --no-open --port 3080
```

Start 在前台启动 DSH，并使用 `--no-open`；在该实例的入口打开页面并完成 DSH 自身认证后，在侧栏选择“大肥鱼”，不要直接打开私有 gateway 的 8765 页面。不要复制或公开带认证信息的入口、日志或 cookie。另一个 DSH 端口不隔离 profile 数据和固定的语音端口 8765。Start 检查目标 profile 的 managed block 标记：已安装时不追加 `--patch`，未安装时使用临时 overlay；不要再手工给已安装的 profile 叠加同一插件。此去重已通过安装脚本 fixture，并已实测持久 Install 后由 Start 启动真实 profile、打开面板及完成语音 ready。

仅加载插件会注册路由和随机回环 bridge，不创建 Python 语音 supervisor。正常在进入面板后，App 发起首个已认证 API / WS 请求，才由 `runtime.ensure()` 启动本插件拥有的本地服务；已认证的手工 API 调用也会触发该机制。启动不会自动开麦。手动选择 GPU 策略时，本地服务启动后仍按原策略预加载和预热，因此进入面板也可能占用 GPU；预热/健康状态本身不是推理证据。本次特定 GPT-SoVITS 短文字链路另有真实播放确认结果，见下方验收记录。

面板失活或页面隐藏只暂停视觉渲染，不停止交互（2026-11-15 更新）。DSH rc1 的 `main` 是 keyed slot，切到其他面板会卸载页面组件；插件因此在自身生命周期内保留**唯一一个** ShadowRoot 宿主与 App，页面组件只负责接入/移出宿主。`active` 仅表示可见性，不再 `root.render(null)`。对话显示、输入草稿、未保存设置、抽屉和 Live2D 模型/纹理得以保留；不改 DSH 源码，不新增自己的记忆系统。

切页保留同一 WebSocket、AudioContext、进行中的回复以及已经授权的麦克风/屏幕共享，声纹录制也按原时限继续；不重新申请权限、不重建会话、不把字幕标记为中断。断线重试不受面板可见性限制，但真实断线仍释放失效采集，不自动重开权限。隐藏仅停止状态显示轮询、波形及 Live2D 本实例 PIXI/interaction ticker。首次会话创建共用同一个 pending 请求；只有显式“新对话”才重置 ID。保存配置/换会话仍按原规则退休旧连接。手动停止采集、轨道撤销和插件真正卸载各自执行资源清理；真实卸载才销毁 root。浏览器刷新、宿主重启、页面被冻结/丢弃、系统休眠不在在页保活范围内。

点击“开始屏幕陪玩”时同步请求恢复播放，同时保留 `getDisplayMedia` 的原始点击调用栈；不会为解锁扬声器偷偷开启麦克风。播放解锁失败会明确提示。已授权共享期间，后端按采样间隔发送有流 ID 的 WebSocket 采样脉冲，避免只依赖后台页面的 interval；前端与兼容 interval 共用单飞编码、限速、差分及过期检查，不补发积压截图。脉冲不会打开权限。

退出面板本身不等于停止整个语音 supervisor，后台本地服务可继续驻留。插件释放路径会请求停止其拥有的 supervisor；父 stdin EOF 也触发 Python 清理，借用的外部模型进程不主动终止。不能据面板释放或 EOF 清理代码宣称父退出、异常终止后的全部子进程已收敛。

`scripts/check_panel_retention.cjs` 配合 `scripts/serve_screen_request_acceptance.py` 验证编译版 DSH 前端、真实 Live2D canvas、Pipecat WebSocket/AudioContext 的保留及释放，以及切页后的主动回复和普通回答真实 worklet 消费 ACK。运行 fixture 时设置 `SCREEN_FIXTURE_ORIGIN=http://127.0.0.1:18876`、`SCREEN_FIXTURE_OUTPUT_DIR=E:/Dafeiyu/verification/background-interaction/fixture`；后端监听回环 18875，浏览器脚本临时监听回环 18876。宿主 keyed slot、判断/DSH/语音响应是本地夹具，麦克风是静音 MediaStream、屏幕是生成画布；浏览器 visibilitychange 为合成事件，不证明 OS 冻结下运行。不访问真实桌面、麦克风、DSH 登录凭据或付费 API，不冒充真实 DSH 整体宿主的自动化测试。报告在 `E:/Dafeiyu/verification/background-interaction/browser.json`。

持久安装（先退出/重启目标 profile 确保加载）：

```powershell
./scripts/dsh_plugin.ps1 -Action Install -Profile web -DshBin $dshBin
```

退出临时 Start 实例再进行持久安装；后续按原方式启动该 DSH profile，或使用上述会检测 managed block 的 Start，不再手工叠加 Prepare 生成的 `--patch`。Install/Uninstall 修改已有 `$DshHome/profiles/<Profile>/cordis.patch.yml` 中本插件的标记块，不用模板整体覆写 profile；不改 profile 的 `package.json` 或 DSH 安装源码。每次实际变化前将原 patch 备份到项目忽略目录 `.runtime/dsh-profile-patch-*.yml`，再用临时文件替换目标 patch；这仍是对 patch 文件的写操作，不是零写入安装。已有 provider / MCP / 记忆配置应予保留，缺 profile 或标记不完整时停止操作。以下 smoke 通过不包含持久 Install 后重启的验收结果。

原 patch 为独立的空序列 `[]` 时，脚本把原文本放入自己的恢复标记，卸载时恢复该文本。若安装后又手工扩展过该 profile patch，先在本机审阅当前文件与备份，尤其原为空序列的情况，不把卸载当作任意人工编辑的合并工具。不要将含配置的备份内容贴入公开报告。

插件入口直接指向 G 盘项目源文件；模型、运行环境和缓存保持原位置（可在 E 盘），不会因插件安装复制到系统盘。`web/dist-dsh` 与独立版 `web/dist` 分开，DSH 构建设置 `copyPublicDir:false`，不复制 public 模型树。`web/public/models` 可指向 E 盘，静态服务使用真实根目录边界校验。不要将模型、缓存、配置密钥打进发布包。

## 回滚

```powershell
./scripts/dsh_plugin.ps1 -Action Uninstall -Profile web -DshBin $dshBin
```

重启该 profile 使移除生效；Uninstall 只编辑补丁，不通知正在运行的 DSH 热卸载。临时 overlay 则退出该实例，去掉 `--patch` 后按原方式启动即可。卸载不删除数据库、DSH 会话、记忆配置或任何外部模型。

恢复独立版前，先卸载/禁用插件并退出加载它的 DSH 实例，等待所属语音服务释放 8765；不要按端口或 Python 进程名全局终止其他程序。原独立版保持使用 `web/dist` 和原数据目录，在没有手工设置插件运行变量的普通终端执行：

```powershell
Set-Location -LiteralPath G:/dafeiyu
./start.ps1 -NoBrowser
# 独立版需要停止时：
./stop.ps1
```

独立版仍使用其原 LLM 配置与旧数据，不导入 DSH trace。若独立版构建缺失，先在 `web` 执行 `npm.cmd run build`。`stop.ps1` 默认只请求独立版 supervisor 停止；需单独请求插件 supervisor 停止时，使用 `./.venv/Scripts/python.exe scripts/run.py --runtime-name dsh --stop`，这不会卸载仍在 DSH 中启用的插件。插件与独立版不能同时占用 8765，插件遇到其他进程占用时会报错，不终止对方。

## 验收

在合成配置和隔离目录下执行回归（声纹使用其已有独立环境，不混用依赖）：

```powershell
Set-Location -LiteralPath G:/dafeiyu
node --test plugins/dsh/test/*.test.mjs
./scripts/check_dsh_installer.ps1
$env:TEMP = 'E:/Dafeiyu/tmp'; $env:TMP = $env:TEMP
./.venv-voice/Scripts/python.exe -m pytest -q tests
./.venv-voice/Scripts/python.exe -m pytest -q speech --ignore=speech/test_speaker.py
./.venv/Scripts/python.exe -m pytest -q speech/test_speaker.py
Set-Location -LiteralPath G:/dafeiyu/web
npm.cmd test
npm.cmd run build
npm.cmd run build:dsh
```

静态功能核对及完整矩阵见 [DSH_FEATURE_PARITY.md](DSH_FEATURE_PARITY.md)。Mock ctx / HTTP fixture 测试与真实 DSH、真实推理、真人全双工验证分别记录。健康检查不发模型请求；浏览器初始不打开麦克风。没有真实测量不得宣称延迟改善、所有模型可用或 NPU 工作。模型权限审批/工具执行显示由 DSH 原生界面负责，不绕过其 permission harness。

`scripts/check_dsh_plugin.cjs` 是真实 DSH/浏览器 smoke 入口：默认不提交模型提示词；显式设置 **`DSH_TEST_LIVE_TURN=1`** 才发送一次短文字输入，使用当前 DSH 模型和保存的 TTS，可能消耗真实 LLM 配额并运行本地 GPU。两种模式均禁止麦克风采集。脚本检查原生面板、资源前缀、原生会话创建/读取/归档、旧 memory API 410、语音 ready 和失活/恢复生命周期；live 模式额外检查浏览器音频和播放确认后的原生历史。执行需由集成者管理目标实例和私有入口日志；不要在公开报告中附认证入口、会话正文或凭据。

### 本机验收通过（2026-11-14）

以下为集成工作区实际运行结果，详见 `DSH_ACCEPTANCE_2026-11-14.md`；不包含用户对话正文、登录入口或密钥：

- 已安装 **DSH 0.2.2-rc.1**、真实用户 profile，普通 smoke 与显式 `DSH_TEST_LIVE_TURN=1` 均通过。proxy 已转发 WS 升级响应的 `Sec-WebSocket-Extensions`，修复漏转导致的 Chromium 1006。
- 短文字输入走 **`deepseek-flash` → 当前保存的 GPU GPT-SoVITS-v5-turbo → 浏览器**，收到 **55 PCM frames / 107735 wire bytes**；worklet 确认消费/播放，DSH 原生会话出现 **7 字 assistant 已播 prefix**，不记录正文。
- native create/read/archive、inactive 音频资源释放及 reactivation ready 均通过。
- **0 麦克风请求、0 前端旧 memory 请求**，已认证旧 memory 路由 **410**；**0 浏览器 error / 0 资源失败**。
- 真实 profile 持久 Install 后不叠加 overlay 启动，普通浏览器 smoke 通过；实际 Uninstall 后与安装前备份的 SHA-256 完全一致，随后重新 Install。fixture 还覆盖重复安装、空 YAML 序列及环境恢复。
- Windows 自建服务在启动前进入 kill-on-close Job，父 stdin EOF 和 supervisor 强杀回归通过，borrowed 服务不被终止。真实 DSH 宿主意外退出后，原有 3080 / 8765 / 8766 / 8770 监听及其已记录 PID 全部消失；不遗留本轮 GPU/语音服务。
- 插件 25、后端 327、语音适配 107、声纹 3、前端 136 项测试通过，另有 2 项按条件跳过；standalone 和 DSH 前端构建均通过。已有依赖弃用、一个测试协程警告和大包 warning 不隐去。

这是一个特定模型的短文字语音输出链路成功记录，不再把该 LLM/GPU 路径描述成完全未测。wire bytes 不是 PCM 样本数或延迟，worklet 回执不等于物理扬声器听感，也不证明所有 TTS、语音输入或完整迁移矩阵已通过。

### 仍待独立验证

- 真实麦克风/流式 ASR、duplex/pipeline 声学回声消除、owner 声纹、真人打断与主动接话七参数、SystemOne 情绪/表情/动作、物理发声和听感。
- IndexTTS、MOSS CPU voices、其他 TTS 模式/外部付费 TTS API、远端 MOSS Live、其他模型与供应商；切换、取消、停止续说及错误恢复边界。本次结果不能推广为这些项目已实测。
- standalone 实际切回运行仍需独立验收；原入口、配置与数据库保留，已验证其单元回归及构建，不将这些当成实际回滚运行。
- 全量样式交互、鉴权负例、并发会话隔离、取消/输出背压和长期稳定性，按完整矩阵逐项验收。不宣称真人语音全链路成功，也不提供未测的延迟或 NPU 结论。

日志在 `data/logs/dsh-plugin-runner.log` 和原服务日志；`.runtime` 中的配置备份可能含用户设置，必须保持 ignored，不附到公开 issue。
