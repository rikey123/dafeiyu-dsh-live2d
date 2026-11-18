# 大肥鱼 DSH 插件：独立安装与发布

本项目的发行物是官方 `dsh.bundle` 格式的 **npm `.tgz` 插件包**，不是 `.dshb`。
包内包含原前端的预编译文件、Node 插件及完整语音后端代码；不需要原开发目录、Git、前端构建工具或预先创建的 Python 环境。

当前发行版 **0.3.2** 声明 **Windows x64 + Node.js ≥22 + DSH 0.2.2-rc.1**。这不是对其他 DSH 版本或操作系统的兼容承诺。Python 3.12 和依赖通过 uv 安装，无需预装 Python 或 uv。

## 安装发行包

推荐流程：

```powershell
dsh plugin --profile web add "E:/Downloads/dafeiyu-dsh-live2d-0.3.2.tgz"
dsh web
```

使用发行物旁的 `SHA256SUMS` 核对插件包。名称不同的 profile 替换 `web`。重启后首次打开侧栏「大肥鱼」：

1. 选择资源目录，建议 `E:/DafeiyuCompanion`。未选择目录时不向默认系统盘下载。安装向导记录目录到 DSH 的 `dafeiyu_installation` storage domain；只存目录和跳过素材偏好，不存聊天/记忆，也不修改 npm 包目录。
2. 点击「开始安装」，自动拉取固定版本、双重 SHA256 校验的官方 uv 0.13.7 Windows x64 归档与可执行文件，随后准备 managed Python 3.12、两套独立环境、基础 SenseVoice ASR 与 Silero VAD。可选中国镜像（Python 清华源 / Hugging Face 镜像）或官方源；部分可选 TTS 上游准备脚本仍有自己的镜像配置，并非所有权重都会切换到同一来源。
3. 按需勾选声纹、流式 ASR 或本地 TTS，不默认拉取大型 TTS。下载期间不执行推理，不调用付费 API，也不自动开麦或共享屏幕。面板切换不取消后台安装；停止插件会取消其拥有的安装进程树。
4. 阅读并勾选 Core 官方许可，以及「自动下载安装大肥鱼」即可自动获取完整形象，不需要手填 ZIP、URL 或 SHA256。预设从[素材仓库](https://github.com/YJackie-Li/DeepSeek-chan)固定提交直接下载，SHA256 内置校验（由本项目核验下载字节，不冒充作者公布的校验值）；角色不在插件包中重新托管。现有角色不自动覆盖，下载失败可重试并复用已校验缓存。高级选项仍支持原配布 ZIP、GitHub 素材 ZIP 或自定义 HTTPS + SHA256；不能和自动角色同时选择。缺角色/Core 时可暂时进入原设置，缺素材不等于数字人已显示正常。来源、许可和手动步骤见[角色说明](DEEPSEEK_SKIN.md)。
5. 安装完成自动进入原应用；原前端样式、输入框和功能不变。TTS/System One 密钥仍由用户在原设置里配置；DSH 继续负责模型、Agent、会话、工具、人格和记忆。

若已显式设置插件 `homeDir` 或 `DAFEIYU_HOME`，首次打开面板会检查并补齐基础环境；插件配置 `autoInstall:false` 可禁止这种自动补齐，仍可手动点击安装。`homeDir` 优先于环境变量，再优先于向导保存的目录。已就绪的安装不重新下载。改变目录需关闭插件后修改配置并重新安装环境，不移动现有 Windows venv。

安装进度通过经过 DSH owner 鉴权的同源 `/dafeiyu/install` 获取，不能匿名安装。失败可原地重试，完整下载缓存保留；诊断在 `<home>/data/logs/installation.log`，不向浏览器回显下载链接/子进程输出。`<home>/.runtime/bootstrap.json` 记录阶段，不保存 API 密钥。单目录锁避免并发安装；强制终止导致遗留锁时先确认所有安装子进程已结束，再移除 `.runtime/bootstrap.lock` / `setup.lock`，不要绕过活跃锁。

命令行一键方式：

```powershell
$plugin = Join-Path $HOME '.dsh/profiles/web/node_modules/@dafeiyu/dsh-live2d'
$cli = Join-Path $plugin 'bin/cli.mjs'
node $cli install --home "E:/DafeiyuCompanion" --source china --accept-live2d-license --avatar-preset deepseek-chan --accept-avatar-license
# 不安装形象时去掉两个许可参数和 --avatar-preset；手动导入改用 --archive E:/Assets/角色.zip
# 可选语音模型：--models speaker,streaming-asr,moss
# 远端角色：--avatar-url https://your-host/character.zip --avatar-sha256 <64位SHA256> --accept-avatar-license
```

CLI 不修改 DSH 的目录指针，启动 DSH 时用相同 `DAFEIYU_HOME` 或 `homeDir`。`install --plan` 不下载、不写目录。`install --offline` 仅在 uv、Python/依赖、基础 ASR/VAD 和所需 Core 已完整缓存时可用；不允许离线准备未缓存模型或联网补齐。uv 官方归档、角色仓库或模型源不可达时会明确失败，不绕过校验或静默换用未知镜像。需要联网代理时请确保所用 Node/下载进程的网络可访问远端；浏览器能打开不代表后台一定能下载。

uv/角色下载器在 Node 22.21+ / 24.5+ 可使用 `HTTPS_PROXY` / `HTTP_PROXY` 和 `NO_PROXY` 环境变量（旧 Node 直接连接），不读取或自动开启 Windows 系统代理，也不改变内部回环网关的网络路径。下载超时按响应头等待和传输停滞判断，不把持续有进度的慢速下载强制截成 30 秒。

### 兼容的分步 CLI 安装

以下低层命令继续保留，适合已有 uv 或需要细分步骤的部署。不需要单独安装 Python、CUDA 或本地 TTS 模型来使用 API TTS 模式。uv 不在 PATH 时用 `--uv <uv.exe 的实际路径>`。

1. 下载发行包并对照 `SHA256SUMS` 校验哈希。安装到你要使用的 DSH profile：

   ```powershell
   dsh plugin --profile web add "E:/Downloads/dafeiyu-dsh-live2d-0.3.2.tgz"
   ```

   名称不同的 profile 替换 `web`。安装由 DSH 自己记录 bundle，不用修改 DSH 安装源码或手工插入绝对路径 patch。不要同时保留旧源码版插件的 managed block，否则会注册两份插件；旧版可用原 `scripts/dsh_plugin.ps1 -Action Uninstall` 移除，只移除它自己管理的块。

2. 在 DSH profile 中定位已安装插件的 CLI，明确指定**外部可写目录**：

   ```powershell
   # 示例为默认 DSH_HOME；自定义 DSH_HOME 时替换这一段。
   $plugin = Join-Path $HOME '.dsh/profiles/web/node_modules/@dafeiyu/dsh-live2d'
   $cli = Join-Path $plugin 'bin/cli.mjs'
   node $cli setup --home "E:/DafeiyuCompanion"
   node $cli models --home "E:/DafeiyuCompanion" --kind sensevoice
   ```

   `setup` 只安装隔离环境与依赖，不启动推理、不下载 TTS 权重、不占 GPU。ASR 模型下载是第二个显式命令。任何安装命令都可先加 `--plan` 检查操作；`setup --offline` 只使用已有 uv 缓存，缺文件时失败而不联网。安装中断后可原命令重试；未完成时不会标记 ready。不要在正在运行的语音安装目录中更新环境。

   `sensevoice`、`speaker`、`streaming-asr` 的准备命令也会下载并校验固定版本的 Silero VAD，放在 `<home>/public/vad`；普通 ASR 人声过滤与声纹都需要它，不依赖旧开发机的 `web/public`。

3. 原角色和 Cubism Core 的许可独立，不放进发行包。[角色来源、固定版本 ZIP 和导入教程](DEEPSEEK_SKIN.md)均有直接入口；导入合法取得的本地文件：

   ```powershell
   node $cli avatar --home "E:/DafeiyuCompanion" --archive "E:/Assets/DeepSeek免费公皮.zip"
   node $cli core --home "E:/DafeiyuCompanion" --file "E:/Assets/live2dcubismcore.min.js"
   ```

   没有本地 Core 时，阅读 Live2D 条款后，可显式运行 `core --download --accept-live2d-license`。这不是模型再分发许可。角色原始须知、纹理、动作和表情在本地导入时保留。细节见 [角色说明](DEEPSEEK_SKIN.md) 与包内 `app/notices/LIVE2D-LICENSE.md`。

4. DSH 启动进程使用相同目录，重启目标 profile：

   ```powershell
   $env:DAFEIYU_HOME = 'E:/DafeiyuCompanion'
   dsh web
   ```

   也可在 DSH 插件配置中设置 `homeDir`，其优先级高于环境变量；这适合通过桌面启动器运行的场景。只在当前终端设置环境变量不会影响已经运行的桌面启动器。进入 DSH 侧栏「大肥鱼」，在原设置面板填写 TTS、System One 等服务配置。对话模型、任务、工具权限、人格、记忆仍由 DSH 配置。不会自动打开麦克风或共享屏幕。

5. 诊断命令：

   ```powershell
   node $cli verify --home "E:/DafeiyuCompanion"
   node $cli doctor --home "E:/DafeiyuCompanion"
   ```

   `verify` 校验包内代码及资源清单。`doctor` 检查环境和资源文件，不调用付费接口；依赖 ready 不代表真实麦克风、GPU 推理或云端密钥已经验收。

默认本地语音端口仍为 8765/8766，可通过插件配置 `gatewayPort` / `speechPort` 指定其他互不相同的端口。GPU TTS 默认 8770、CPU TTS 默认 8772。不要同时运行两个使用相同端口的服务；不会杀掉或接管其他进程。插件只停止自己拥有的服务。隔离验收使用单独的数据目录及语音端口，不影响已有实例。

## 可选能力的依赖

所有原有功能、界面和交互代码均保留，安装路径变化不改变触发阈值或模型路由。不同能力仍需要各自的真实依赖：

| 能力 | 显式准备 |
|---|---|
| DeepSeek / 兼容 TTS API | 原设置中填写服务密钥及音色；不必装本地 TTS |
| MOSS-TTS-Nano ONNX CPU | `models --home <目录> --kind moss` |
| IndexTTS GPU | `models --home <目录> --kind index`；另需可用 NVIDIA 驱动/CUDA 对应硬件 |
| GPT-SoVITS v5 turbo GPU | `models --home <目录> --kind gpt-sovits`；保留原可选模式 |
| 主人声纹 | `models --kind speaker`，随后由用户在原设置录制注册 |
| 流式 ASR 预览 | `models --kind streaming-asr`，再在原设置启用 |
| System One 情绪/动作/插话、屏幕陪伴 | 原设置填写服务配置；屏幕由用户授权 |
| MOSS-Live 全双工 | 原设置填写独立服务配置，不伪装为本地推理 |

前三种本地 TTS 的 `models` 命令会下载较大的模型和隔离运行时，**不会执行推理验收**。GPU 模型需要按原配置提供参考语音/文本；不随机生成或打包用户声线。不把 CPU 回退、健康检查或缺失模型描述成 GPU 已可用。

可选蓝色大肥鱼人格连同原许可证保存在 `app/personas/blue-whale`，供通过 DSH 人格插件导入；安装不会覆盖现有 DSH 人格，也不迁移旧记忆。语音环境提示继续只在语音会话中追加。

## 数据与代码分离

```text
DSH profile/node_modules/@dafeiyu/dsh-live2d/   # 可替换的插件代码
  src/  bin/  cordis.patch.yml
  app/
    server/ speech/ scripts/ requirements*.txt
    web/dist-dsh/                            # 原前端，不改样式
    personas/ notices/ release-manifest.json

<DAFEIYU_HOME>/                              # 用户选定，例如 E 盘
  .venv/ .venv-voice/ runtimes/               # 由 uv 准备
  tools/uv/                                 # 固定版本、校验过的下载管理器
  models/ source/                            # 独立下载模型及上游代码
  cache/ .runtime/                           # 缓存、锁、进程所有权
  data/                                     # 私有语音设置、日志、声纹
  public/models/ public/cubism/ public/vad/  # 用户素材与单独准备的 VAD
  .env                                      # 本地设置，不进发行包
```

`DAFEIYU_DATA_DIR`、`DAFEIYU_MODELS_DIR` 等底层覆盖仍供源码/外部服务部署使用；标准插件运行时统一从 `homeDir` 派生子目录，避免安装器与运行时读到两套数据。无 `DAFEIYU_HOME` 的源码模式保留原目录布局；不要把源码模式当作打包后的默认路径。

安装包无 postinstall 下载/启动脚本，首次打开面板的向导承担自动安装，不依赖包管理器是否放行 install script。更新替换的是插件代码，用户目录不随 npm 更新或卸载删除。升级后首次打开检查新版依赖，也可执行 install/setup；更换目录需迁移用户文件并重新准备虚拟环境，不能直接移动 Windows venv。卸载使用 `dsh plugin --profile web remove @dafeiyu/dsh-live2d`；用户目录保留供用户决定。

旧源码部署若把可选 TTS 环境和权重放在代码目录之外，迁移前必须显式配置模型/运行时路径；新版不再猜测开发机曾用的盘符。不要直接把旧安装的 `DAFEIYU_HOME` 改成模型目录，否则可能同时切换配置与数据位置。现有实例不由打包流程迁移或停止。

## 从源码构建发行物

```powershell
npm --prefix web ci --no-audit
npm run test:release
npm run release -- --out "E:/DafeiyuReleases/0.3.2"
```

构建脚本重新编译 DSH 前端，只从白名单收集运行代码、依赖清单、人格和第三方声明，再实际执行 `npm pack`，生成 `.tgz`、`SHA256SUMS` 和 `release-report.json`。没有构建输入时直接失败，不把空壳包称为发行版。`--skip-build` 仅适合已经构建且确认版本一致的开发流程。

严禁把开发机的 `web/public` 整体复制到发行物：里面可能是禁止再分发的角色、Core、用户参考声线。打包审计拒绝数据库、密钥文件、权重、虚拟环境和机器专用运行路径。第三方许可证从实际前端依赖收集，不能借应用许可证覆盖其条款。自动角色预设及 SHA256 位于 `plugins/dsh/src/avatar-presets.mjs`；只有用户明确确认后才下载，成功导入后在外部 home 的 `.runtime/avatar-installation.json` 记录版本、来源与校验值，不写 npm 包。

GitHub Actions 的 tag/workflow_dispatch 构建上传包和哈希作为 artifact，**不自动发布 npm 或创建公开 release**。正式公开上架前需由项目所有者确认包名权限、项目代码许可证、版本兼容范围和第三方授权。目前代码许可证记为 `UNLICENSED`，没有擅自选择开源协议或发布到任何账号。

## 验收边界

发行验收必须在原项目目录之外解包：检查包清单、哈希、CLI、真实 DSH bundle 发现、外部 home 写入及无源码路径依赖。合成语音/屏幕夹具仅证明传输、调度与播放 ACK，不证明模型社交质量、真实 GPU 延迟或声学回声消除。保留前端测试和原语音回归测试，不为“能打包”删除已有功能。

### 0.2.0 本轮验证（2026-11-16）

- 原前端 207 项、插件/发行工具 99 项通过；后端与路径回归 546 项通过、1 项跳过，另跑 speech 组 146 项通过、2 项跳过。分组存在重合，不把这些数字相加成独立用例总数。既有测试仍有第三方弃用与 coroutine 资源告警，没有将告警描述为已修复。
- 重建的 6 个前端文件与现用版本逐字节相同；完整蓝色大肥鱼人格原文哈希未变。
- 新目录解包后，uv 创建独立 managed Python 3.12 与两套环境；安装、离线重复校验、安装清单哈希检查通过。依赖下载采用显式指定的镜像，未复制原项目虚拟环境。
- 使用包内代码和新环境真实启动隔离 gateway/speech：授权健康请求 200、未授权 401，退出后两个端口释放，包目录内容哈希完全不变。未安装 ASR/TTS 权重时，模型明确报告未就绪，不视为语音推理成功。
- 官方 DSH 0.2.2-rc.1 CLI 在隔离 profile 安装并发现 bundle；host 激活、面板入口与客户端组合资源通过，确认复用 host 的同一 Cordis 实例。该项关闭了本地语音自动启动，未做完整浏览器真人交互验收。
- 不读取生产密钥或聊天数据库，不采集真实屏幕/麦克风，不执行 GPU 推理或付费模型/TTS 调用；没有切换或停止既有生产实例，也没有对外公开发布。

### 0.3.0 自动安装验证（2026-11-17）

- 原前端 207 项、插件/安装器/发行工具 129 项通过；另跑路径与进程/可移植性回归 13 项通过。6 个原前端编译文件与 0.2.0 逐字节相同，蓝色大肥鱼人格哈希未变。
- 在 E 盘新目录真实拉取 managed Python 3.12.16、两套依赖、SenseVoice 和校验过的 VAD。该次全量安装显式指定 uv；另验证了从已下载的官方归档、固定双重 SHA256 校验后自动提取 uv，以及不传 uv 路径的离线重复安装。
- GitHub 官方 uv 下载在本机约几十 KB/s；网络下载观察到持续传输后主动取消，未把这一部分报告成完整冷启动下载成功。响应头超时、正文停滞、取消、并发缓存校验由离线夹具覆盖；持续有数据的慢速下载不受 30 秒总时长限制。
- 官方 DSH CLI 在隔离 profile 安装包；真实 host 的首装状态返回 `needs_directory`，原前端入口、安装门和官方组合客户端资源返回 200，未授权返回 401。这是宿主 HTTP / 安装 UI 测试，不是完整浏览器真人操作验收。
- 新环境运行包内网关/语音服务，授权健康检查 200、未授权 401，ASR 健康检查为 CPU 就绪；关闭后端口释放，包目录没有被写入。未配置 TTS 时仍如实报告其未就绪，不视为端到端对话/GPU/TTS 推理验收。
- 不读取生产密钥或聊天数据库，不采集真实屏幕/麦克风，不启动 GPU 或付费调用，也未替换现有生产实例。角色/Core/大型可选 TTS 不在本次真实下载验收中；角色未重新托管，包未公开发布。

正常失败会释放安装锁，可原命令重试。若强制杀死安装器导致 `<home>/.runtime/setup.lock` 遗留，必须先确认该目录的安装进程已结束，再手工移除这个锁文件后重试；不要删除用户环境或绕过正在进行的安装。


### 0.3.1 素材直达与 ZIP 兼容验证（2026-11-18）

- 新增作者原发布页、完整素材仓库、固定版本 ZIP 和使用须知直接入口；仓库维护者未核实为原作者，不标作官方，不重新托管完整模型。
- 原前端 207 项、插件及发行工具 130 项、角色导入专项 13 项通过。主应用 6 个编译文件与原版本逐字节相同，人格原文哈希未变；仅首次安装门添加来源链接。
- 真实下载固定提交 `824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f` 的 GitHub ZIP（49,738,232 字节），导入 23 个表情、8 个动作组；另验证原始配布 ZIP，原 model3 与完整使用须知均保留。
- 隔离浏览器加载实际导入的 GitHub 素材，moc3、5 张纹理、物理和待机动作均为 200，角色画面正常，安装门 4 个素材入口可见，390px 小屏无水平溢出，无页面脚本异常。
- 本轮没有重跑真实 DSH 宿主、麦克风、GPU 推理或付费 API 验收；离线界面和资源加载不作为这些能力的新可用性证明。未修改、停止或启动生产语音实例。


### 0.3.2 角色自动安装验证（2026-11-18）

- 首次安装向导支持显式勾选角色使用须知，自动从社区素材仓库下载固定版本，校验 SHA256 后导入；无须手填 ZIP、URL 或 hash。不捆绑或重新托管角色及 Cubism Core，不默认勾选授权。
- 原前端 207 项、插件/安装器/发行工具 141 项（0 跳过）、角色导入专项 13 项通过。主应用 6 个编译文件与原版本逐字节相同，完整蓝色大肥鱼人格原文哈希未变。
- 在隔离 loopback 页面使用实际解包发行物的安装 UI 与真实安装控制器，从浏览器勾选并启动；E 盘目录原已有基础 Python/依赖和 ASR/VAD，但无角色与 Core。本次真实更新依赖、从官方获取 Core、从社区仓库下载约 50 MB 角色，校验后成功导入。不是全新机器全冷启动依赖验收。
- 浏览器进入原前端后真实渲染新下载的角色，moc3、5 张纹理、物理与待机动作请求均返回 200；390px 小屏无水平溢出，页面无脚本异常。非安装相关 API/语音状态使用离线夹具，不等同完整 DSH 宿主语音验收。
- 再次执行真实离线安装，现有角色、完整使用须知与来源记录的哈希不变；已有形象不重复下载或覆盖。测试同时覆盖授权缺失、无效预设、自动/手动冲突、校验失败、取消与重试、导入后缺失资源不标成功。
- 未修改或重启生产实例，不读取生产密钥或聊天数据库，不采集真实屏幕/麦克风，不加载 GPU 模型，不进行 TTS 推理或付费 API 调用。
