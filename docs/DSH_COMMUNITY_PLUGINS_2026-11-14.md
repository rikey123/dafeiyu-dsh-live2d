# DSH 养鱼插件：B 站线索、选型与离线下载

核对日期：**2026-11-14**。当前本机 DSH：`0.2.2-rc.1`，使用 `web` profile。

## 交付状态与位置

- **21 个项目**：固定提交的 GitHub ZIP + 已解压源码。
- **14 个发布包**：与源码 `package.json` 同名、同版本的 npm `.tgz`，已核对 registry 的 SHA-512/SHA-256 integrity。
- **8 条 B 站视频**：公开 API 返回 `HTTP 200 / code 0`，已核对标题、UP 主及发布时间，记录在 `references/bilibili-sources.json`。这是检索与元数据核对，**不是逐条观看完整视频或验证演示效果**。
- **没有安装或启用插件**，没有读取账号 Cookie、扫描主人屏幕、登录 QQ、修改 DSH profile、重启 DSH 或启动推理。
- 下载均在 **E 盘**：`E:\Dafeiyu\research\dsh-community-plugins\2026-11-14`，不复制到系统盘。
- 源码 ZIP 约 **81.91 MiB**，源码解压约 **109.32 MiB**，npm 发布包约 **12.56 MiB**。

目录说明：

```text
E:\Dafeiyu\research\dsh-community-plugins\2026-11-14\
  README.md                       本报告副本
  source-index.md                 每个源码目录、固定提交、版本、发布包的精确索引
  manifest.json                   源码 commit、日期、ZIP URL、SHA-256、包声明
  npm-tarballs-manifest.json      npm 包版本、integrity、SHA-256、gitHead 对照
  SHA256SUMS.txt                  所有 ZIP / TGZ 的本地复核清单
  archives\                      21 个固定提交 ZIP
  sources\                       按六类整理的源码（保留各自许可证）
  npm-tarballs\                  14 个已下载的 npm 发布包，不是已安装插件
  references\                    B 站线索、社区目录 README 与来源记录
```

**源码快照 ≠ npm 发布包。** 即使版本号相同，GitHub HEAD 与 npm 的 `gitHead` 也可能不同或无法对照；清单已分别记录，不把源码静态检查当作发布包完整安全审计。完整性校验也不等于安全认证。

## 1. B 站入口

| UP 主 | 视频 | 对应线索 |
|---|---|---|
| 湖上的优尤 | [分享自己给大肥鱼做的一系列插件，以及长期养鱼的心得](https://www.bilibili.com/video/BV1ednc6jE3j/) | 记忆、心情、主动搭话、刷 B 站、QQ、朗读桥的作者入口 |
| AI技术投降派 | [六个插件：给你的大肥鱼DSH装上灵魂](https://www.bilibili.com/video/BV1jhn16GEcv/) | 上述组合的使用介绍 |
| 阳子YoungZi | [零基础deepseek养鱼教程](https://www.bilibili.com/video/BV161nZ6JE6b/) | 同类组合的安装线索 |
| 湖上的优尤 | [我做了个插件，让大肥鱼能陪我打电话、看视频、打游戏！](https://www.bilibili.com/video/BV1eAs96TEM2/) | 鱼搭子 `dsh-fish-buddy` |
| AI技术投降派 | [让你的大肥鱼每2.5秒看一眼屏幕的插件](https://www.bilibili.com/video/BV1Fcnd6kEer/) | 鲸鱼陪看 `dsh-whale-sense`；标题中的间隔不是本机端到端实测延迟 |
| 苍穹晓雷 | [超便宜的准实时视觉DSH插件！](https://www.bilibili.com/video/BV1c3xb6UEWE/) | `dsh-see-now` 连续屏幕感知 |
| 时梦染 | [我花了 13 亿 token，就为了看AI能不能长出人格](https://www.bilibili.com/video/BV1oTnZ6LEtc/) | `@ssamurias/dsh-fish` 自主养成 |
| 莫德雷 | [教你在b站养一条deepseek大肥鱼！](https://www.bilibili.com/video/BV16KnN6KEwo/) | `dsh-bili-whale` 作息、刷视频及互动 |

没有下载或搬运这些视频，只保存检索与来源元数据。

## 2. 已下载项目清单

下表版本来自**固定源码快照**的 `package.json`；“包”仅表示该精确 npm 版本已另行下载，**不表示已安装或通过本机功能验收**。“源码”表示该精确版本在 npm 返回 404，保留 GitHub 源码，不自动改装其他版本或其他同名包。

### 人格、心情与主动性：`sources/01-personality`

| 项目与来源 | 版本 | 下载 | 用途及选择注意 |
|---|---|---|---|
| [dsh-soul-md](https://github.com/Scorp1o117/dsh-soul-md) | 0.12.3 | 源码 + 包 | 可切换人格卡，按工作区/会话选择；同时带文件记忆，**每张人格卡默认启用记忆，可独立关闭**。适合先只用人格功能。包声明明确列出 `0.2.2-rc.1` 兼容，尚未在当前面板验收。 |
| [dsh-fish](https://github.com/ssamurias/dsh-fish) | 1.0.0 | 源码 + 包 | 自主养成、认知/遗忘、作息及 B 站活动的一体方案；不是纯角色卡。作者关于“人格诞生”的说法是产品设计叙述，不是训练出独立人格的证明。当前 DSH 版本在其兼容表中为 `unknown`。 |
| [dsh-feiyu-mood](https://github.com/Yuuyuko-uu/dsh-feiyu-mood) | 0.9.3 | 源码 + 包 | 对话后的心情判断、数值与时间线挂饰。它的心情值不会自动驱动我们现有的 Live2D 表情。 |
| [dsh-speak-up](https://github.com/Yuuyuko-uu/dsh-speak-up) | 0.3.2 | 源码 + 包 | 空闲时按随机节奏让 DSH 开口。它不等于现有 Jev/System One 的“用户正在说话时是否接话”的判断。 |

### 第三方 DSH 记忆（仅备选）：`sources/02-memory-optional`

| 项目与来源 | 版本 | 下载 | 用途及依赖 |
|---|---|---|---|
| [dsh-fish-memory](https://github.com/Yuuyuko-uu/dsh-fish-memory) | 1.6.1 | 源码 + 包 | 带时间和遗忘机制的会话长期记忆；适合对比轻量养鱼记忆。 |
| [dsh-tdai-memory](https://github.com/Scorp1o117/dsh-tdai-memory) | 0.4.8 | 源码 + 包 | 对话采集、结构化提取、分层记忆和检索；需另配提取 LLM 与 embedding 服务，不是附送了可工作的本地向量模型。 |
| [dsh-xingxi](https://github.com/Yuuyuko-uu/dsh-xingxi) | 0.3.2 | 源码 + 包 | 将整理的记忆档案展示为星图；不能代替记忆采集与召回引擎。 |

遵守之前的决定：**不恢复本项目旧记忆模块、不导入旧数据库、不另写 harness**。这些只是下载的 DSH 侧扩展候选；本次没有选择或启用任何记忆插件，也不建议同时堆叠多套自动召回。

### 自己刷 B 站：`sources/03-bilibili`

| 项目与来源 | 版本 | 下载 | 用途与边界 |
|---|---|---|---|
| [dsh-bili-subagent](https://github.com/Yuuyuko-uu/dsh-bili-subagent) | 1.0.1 | 源码 + 包 | 派 DSH 子代理读字幕、简介和评论，内部汇报后让主伙伴决定如何分享。需自己的 B 站登录与独立 Python 依赖；**读字幕不等于看过视频画面**。推荐先手动、只读验证。 |
| [dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) | 0.4.6 | 源码 | 作息、日记、视频阅读、分享、评论/私信；画面路线需 ffmpeg 和宿主图像工具/模型。对外发言与账号风控是额外责任。 |
| [dsh-bili-pod](https://github.com/nullifyi/dsh-bili-pod) | 0.10.0 | 源码 | 上一项目的派生增强：模块化、审核、账本、日记分类等。和上游选一个，不要重复安装；不照搬 README 中放宽全盘工具权限的建议。 |
| [dsh-bili-humanism](https://github.com/InariNGT-Ofiicial/dsh-bili-humanism) | 1.11.5 | 源码 | 更偏内容学习、取稿/抽帧/ASR、手账与人格积累。作者区分正式包和源码，GitHub Release 安装路径不能和 npm 一键安装混为一谈。 |

其中“自主刷视频”与下面的“看主人当前屏幕”是两件事，不能互相替代。B 站 Cookie/扫码凭据不进 Git；自动评论、私信、点赞等写操作应单独授权、先关闭。

### QQ：`sources/04-qq`

| 项目与来源 | 版本 | 下载 | 接入路线与用途 |
|---|---|---|---|
| [dsh-qq-link](https://github.com/Yuuyuko-uu/dsh-qq-link) | 1.5.9 | 源码 + 包 | **普通 QQ 号 / OneBot v11**，依赖另装并登录的 NapCat、SnowLuma 等协议端；偏向把现有 DSH 伙伴双向接到 QQ。六件套的当前仓库叫 `qq-link`，不要按旧称 `qq-bridge` 乱装同名包。 |
| [@tencent-connect/dsh-qqbot](https://github.com/tencent-connect/dsh-qqbot) | 0.5.5 | 源码 + 包 | **QQ Bot 官方 API v2 路线**，扫码绑定或机器人凭据；不是让你的普通 QQ 账号自动化聊天。官方协议路线可先评估。 |
| [dsh-onebot-qq](https://github.com/YUsaltyfish/dsh-onebot-qq) | 0.1.1 | 源码 | OneBot v11，微内核和可插拔子插件，适合群聊、媒体和后续定制。额外带群记忆、人设等，需先明确哪些关掉。 |
| [@zaofan/dsh-qqbot](https://github.com/zaofan-make/dsh-qqbot) | 1.12.34 | 源码 + 包 | 腾讯路线的增强 fork：多实例、人设、表情、定时、关系等。功能多且维护面更大，不与上游一起启用；许可为 AFL-3.0。 |

普通 QQ 自动化路线有协议端与平台风控风险；这次没有安装 QQ 协议端、登录 QQ 或发送任何消息。

### 看主人屏幕、陪看、陪玩：`sources/05-screen-companion`

| 项目与来源 | 版本 | 下载 | 适用性与实际限制 |
|---|---|---|---|
| [dsh-fish-buddy / 鱼搭子](https://github.com/Yuuyuko-uu/dsh-fish-buddy) | 插件 0.9.0 | 源码 + 包 | 仓库含 DSH 插件和 Python/Tk 桌面挂件，提供语音、字幕白板、游戏截图与弹幕。桌面程序与插件版本分开。这里下载的是源码和插件包，**没有下载/运行挂件 EXE，也没有另下 ASR 模型**。 |
| [dsh-see-now / See Now](https://github.com/SAOS-3624/dsh-see-now) | 0.2.3 | 源码 | 屏幕/摄像头/视频变化筛选与多帧拼图，支持声音转写和可选悬浮窗；适合研究连续感知。当前精确版本在 npm 返回 404，不能把 README 的 npm 示例当成本次已经拿到的安装包。 |
| [dsh-whale-sense / 鲸鱼陪看](https://github.com/pairun325/dsh-whale-sense) | 0.1.0 | 源码 | Windows 截屏差分、窗口过滤、冷却和小时限额，默认不自动唤醒。实现轻但有作者环境残留，见下节，**不列为本机开箱即用**。 |

关于看屏幕的共同前提：

1. 需要**明确的屏幕采集授权、区域/窗口选择、可见状态和立即停止入口**；密码、聊天或支付窗口应排除。
2. 会把图片交给模型；当前选用的 DSH 模型/提供商若不支持图像，需明确配视觉模型或图像描述工具，不能声称仅靠文字模型就能看懂屏幕。
3. See Now 的 Windows 采集使用 ffmpeg，悬浮窗另需可用的 Python/Tk；鱼搭子的 ASR 模型与桌面挂件另算依赖。
4. README 的毫秒、采样间隔、token 节省等均是作者描述，**不是本机测得的视觉响应/语音首包延迟**。
5. 持续截图会影响隐私、磁盘、模型用量与上下文长度；要先设触发冷却、每天预算和清理策略。

**明确发现的问题**：下载快照 `dsh-whale-sense/lib/index.js:282` 的唤醒提示引用 `E:/dswork/tools/say-check.mjs`。那是作者路径，不是本项目已提供的工具。它还依赖宿主图像/字幕工具，必须修整并做真实链路测试后才能谈接入。

鱼搭子的宿主会另开 `127.0.0.1:8777` 本机 HTTP 服务，接入前还应单独评审入站鉴权、Origin、消息大小和会话边界，不能把 loopback 当成充分的身份校验或直接转发公网。

### 一体替代方案与语音桥：`sources/06-integrated-alternatives`

| 项目与来源 | 版本 | 下载 | 为什么作为替代而非默认叠加 |
|---|---|---|---|
| [dsh-fish-soul](https://github.com/Britneycode/dsh-fish-soul) | 0.16.3 | 源码 + 包 | 人格、按人记忆、QQ/OneBot、B 站、抖音、语音与生活节奏的一体方案。会拥有较大一块伙伴逻辑，不是只补一条能力的小模块。 |
| [dsh-aurabot-qq](https://github.com/aureth-labs/dsh-aurabot-qq) | 1.2.1 | 源码 | QQ 伙伴一体方案：人格/记忆/主动性、语音/唱歌、模块面板等，需另装 OneBot 协议端。应和鱼魂择一评估。 |
| [dsh-tts-bridge](https://github.com/Yuuyuko-uu/dsh-tts-bridge) | 1.3.3 | 源码 + 包 | 将 DSH 文字交给 DeepSeek 网页端朗读；依赖网页环境/登录，不是我们现有 GPU/CPU/API TTS 的同义替代。当前已有音频输出，不应再双重朗读。 |

## 3. 对当前 Live2D 项目的建议

推荐**小模块路线**，而不是把 21 个插件全部启用：

1. 人格：先评估 `dsh-soul-md`，关掉其人格卡的额外记忆，避免和当前角色提示重复；使用 DSH 原生能力，不恢复旧记忆。
2. 刷视频：先 `dsh-bili-subagent` 的**手动、只读**路线；确实需要画面再评估抽帧方案。
3. QQ：普通 QQ 双向桥选 `dsh-qq-link`；官方 Bot 身份选 `@tencent-connect/dsh-qqbot`，二选一。
4. 屏幕：优先研究 See Now 的“感知输入”，或者鱼搭子的截图/字幕白板；保留我们现有 Live2D 和音频前端，不整套换成另一套桌宠 UI。
5. `feiyu-mood` 可作为 DSH 情绪信息来源，但需要映射到现有行为协议；`speak-up` 的随机唤醒和现有 System One 主动接话要共用节流与取消逻辑。

### 不能直接称为“装完就融入现有数字人”

源码检查显示鱼搭子、鲸鱼陪看等会直接对 DSH agent 调用 `followup()`；我们的语音适配器则拥有 request ID、取消、已播放前缀确认与单并发状态。**外部开启一轮 DSH 对话，不代表已经通过本项目的 TTS/口型/打断链路。**

下一阶段需要单独设计并验收统一的“外部事件投递”入口：共享会话身份、后台判断与对话轮次预算，和现有语音轮次互斥，确认图片真的被模型接受，最终回复走原音频与 Live2D 管线。人格插件的 DSH 选择器、心情挂饰也不会自动出现在我们自定义设置/表情中。本轮仅研究下载，没有暗中做这些迁移。

## 4. 许可与安全边界

- 不统一标成 MIT：多份 Yuuyuko-uu 插件使用自定义许可，作者说明并非 OSI 认证许可；允许范围和再分发署名条件以各项目 `LICENSE` 为准。
- 鱼搭子的角色/气泡/弹幕素材不单独授权二次使用，附带 OCR/字体又有各自许可；下载供审阅不等于可原样移植素材。
- See Now 为 Apache-2.0；腾讯 QQ 上游为 MIT，zaofan 增强 fork 为 AFL-3.0；均保留原文。
- 没有执行这些仓库的安装器、`npm install`、`npm pack`、生命周期脚本、自更新代码、测试脚本或附带 EXE。npm 包直接从 registry 取 `.tgz` 校验后保存。
- 只有静态初查，未做完整恶意代码审计、依赖供应链审计或本机功能验收；不建议一次性导入正式 profile。
- 实装时优先隔离 profile，备份后逐个验证；账号凭据单独保存并忽略，缓存、运行时、截图/日记目录也要明确迁到 E 盘。第三方默认写 `~/.dsh` / `%LOCALAPPDATA%` 的路径**本次尚未改造**，不要误认为下载在 E 盘就代表将来所有运行数据也会自动落 E 盘。

## 5. 可复现与完整性验证

下载工具：`G:\dafeiyu\scripts\download_dsh_plugins.py`（只用标准库）。

```powershell
& 'G:\dafeiyu\.venv-voice\Scripts\python.exe' `
  'G:\dafeiyu\scripts\download_dsh_plugins.py' `
  --destination 'E:\Dafeiyu\research\dsh-community-plugins\2026-11-14' --packages
```

已有源码按原清单提交复用，不悄悄升级到新 HEAD；ZIP/TGZ 有大小、解压路径和特殊文件约束，下载不触发插件。npm 的精确版本不存在时会明确记录，**不会换一个名字相近的包**。

包名与版本、固定提交、原始下载 URL、哈希和实际磁盘路径均在两个 JSON 清单。`SHA256SUMS.txt` 可对 ZIP/TGZ 复核；源码解压目录不是不可变镜像，若后续修改请另开分支并记录。

下载工具与快照自检 **9 项通过**：包括路径穿越、符号链接、解压限额、覆盖保护、包身份校验、integrity 失败拒绝、无安装保存，以及全部 **35 份 ZIP/TGZ** 的哈希复核和 21 份 ZIP 的 CRC 检查。这些不是插件功能测试。自检脚本副本保存在下载目录的 `references/test_dsh_downloads.py`。

补充线索目录：[awesome-dsh-plugin](https://github.com/Yuuyuko-uu/awesome-dsh-plugin)，只保存其 README 和来源，不下载整个包含大体积媒体的目录仓库。另一个搜索候选 `huaizhuanghub/dsh-persona-dafeiyu` 的 GitHub API 核对返回 404，**未计入下载成功的 21 项，也未用同名来源替代**。
