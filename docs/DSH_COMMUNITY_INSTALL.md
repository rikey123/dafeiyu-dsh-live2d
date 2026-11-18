# DSH 社区插件安装与组合

本说明针对 DSH 0.2.2-rc.1 的现有 `web` profile。独立环境中的版本为 `dsh-soul-md@0.12.3`、`dsh-fish-memory@1.6.1`、`dsh-bili-subagent@1.0.1`、`@tencent-connect/dsh-qqbot@0.5.5`。请以安装器的校验和状态输出核对本机情况。上游包独立安装，许可证以各包随附的许可文件和上游发布信息为准；本项目没有复制上游源代码。

安装器先写入惰性注释记录；配置器随后在原生 profile `package.json` 记录四个 E 盘本地 `link:` 依赖及 `dsh.profile.bundles`，用 NTFS junction 提供模块解析。上游 bundle 各自声明唯一条目，组合块仅按原生 id 覆盖配置（B 站使用 `bili-scroll`），不重复插入。这样插件库存、启停管理和人格配置界面也由 DSH 原生处理。QQ 条目使用原生 `disabled: true`，凭据为空，尚未登录，禁用时不注册绑定界面。Soul 只负责人格：关闭注入、召回和压缩召回，并禁用当前卡片记忆；策略守卫默认拒绝 Soul 的 `memory_read`、`memory_append`、`memory_rewrite`、`memory_search`、`memory_digest`，由独立的 fish-memory 负责记忆。

B 站配置默认为手动模式，关闭自动评论、观看、收件箱、私信、动态和三连等选项。策略守卫默认拒绝发布、互动、登录和配置相关工具调用，提供默认只读工具约束；它不是文件系统或网络安全沙箱，DSH 其他权限及用户设置界面仍适用。修改策略或上游行为后应重新审查。

## 路径与数据

安装环境为 `E:/Dafeiyu/dsh-community-installer/environment`，四个包的实际文件均在其中 `node_modules`；本项目策略入口是工作树中 `plugins/dsh-community-policy/index.mjs` 的绝对路径。策略使用独立后端包身份，避免原生客户端模块发现器将它误认为第二份 Live2D 前端。移动或删除工作树会影响该入口。B 站 Python 环境已安装于 `E:/Dafeiyu/dsh-community/data/bili-duty/.venv`；依赖快照保存在 `E:/Dafeiyu/dsh-community-installer/bili-requirements-lock.txt`。安装时 `qrcode-terminal` 没有 wheel，因此仅该纯 Python 包由源码构建 wheel，依赖校验与 MCP 无网络初始化/列工具已通过。宿主 peer 默认来自 DSH 0.2.2-rc.1 的 runtime `node_modules`，可用 `DSH_RUNTIME_MODULES_ROOT` 覆盖。

安装器为 DSH home 下的 `fish-memory`、`fish-memory-backup`、`bili-duty`、`soul-md` 和 `attachments` 创建指向 `E:/Dafeiyu/dsh-community/data/` 的 junction，并记录在 `E:/Dafeiyu/dsh-community-installer/junctions.json`。已有源目录或目标目录时会停止，不会自动迁移或覆盖。fish-memory 的小型配置和诊断文件仍可能写在原生 DSH home；原生 DSH 会话也仍留在原位置，不能声称全部数据都在 E 盘。

截图等 DSH 附件通过 `attachments` 持久保存，可能包含敏感画面；请自行设置保留期限、定期清理并保护备份。卸载时非空数据目录及对应 junction 会保留，需检查 journal 后自行处理。

## 操作顺序

在工作树根目录的 PowerShell 中运行。默认 profile 是 `%USERPROFILE%/.dsh/profiles/web/cordis.patch.yml`；如使用其他 home，先设置 `$env:DSH_HOME`。操作前退出 DSH，并避免其他进程同时修改 profile。`plan` 是默认动作；下面显式写出以便审阅。

```powershell
node scripts/check_dsh_community_plugins.cjs
node scripts/check_dsh_community_composition.cjs
node scripts/dsh_community_plugins.cjs status
node scripts/dsh_community_plugins.cjs plan
# 检查计划后安装：
node scripts/dsh_community_plugins.cjs apply
node scripts/dsh_community_plugins.cjs status
node scripts/configure_dsh_community.cjs plan
# 检查路径、peer 和计划后写入组合：
node scripts/configure_dsh_community.cjs apply
node scripts/configure_dsh_community.cjs status
```

安装器 `plan` 校验本地归档并检查路径；`apply` 使用 npm 的 `--ignore-scripts` 和 `--legacy-peer-deps` 安装，创建 junction 并写入惰性记录。传递依赖仍可能从网络获取，并非逐个固定哈希或审计；失败后的环境和 journal 留待人工检查。已有安装或记录时不要重复执行安装 `plan/apply`，先用 `status` 检查。配置器的 `plan/status` 也会校验归档、已安装版本、宿主 peer 和数据重定向；其 `status` 说明配置是否存在，并不证明插件已运行。配置器 `apply` 创建 peer/profile junction、保存 `profile-composition.json` 恢复记录并备份修改 manifest/组合块，不启动宿主。请勿绕过该组合直接启用上游默认记忆和自动互动；默认限制是本项目额外施加的策略，而非上游默认值。

停止 DSH 后按相反顺序撤销：

```powershell
node scripts/configure_dsh_community.cjs uninstall
node scripts/dsh_community_plugins.cjs uninstall
```

配置器先核对 manifest 是否被手工改动，再恢复其管理的依赖/选择记录并移除组合块；安装器再移除其惰性记录，只清理 journal 中仍匹配且目标为空的数据 junction。依赖、模块解析 junction、缓存及非空数据保留。两者修改 profile 前会将原文件备份到 `E:/Dafeiyu/dsh-community-installer/backups`，并检查并发修改；备份可能包含私密配置，应妥善保护。配置器按标记替换或删除整个组合块，手工修改块内内容会被覆盖；标记异常时停止。安装器对其注释块进行完整性检查，修改过的块需人工处理。

## 实际验收（2026-11-14）

- DSH 原生 profile 启动成功；浏览器实际加载三个上游客户端模块，并打开“鱼的记忆”“刷 B 站”和人格插件配置，无 JS 错误；QQ 已安装但仍禁用、未登录。
- B 站 Python `pip check`、导入和 MCP `initialize/list_tools` 通过；没有登录、调用 B 站网络工具、评论、三连或私信。可运行 `E:/Dafeiyu/dsh-community/data/bili-duty/.venv/Scripts/python.exe scripts/check_bili_mcp.py` 重测。
- 大肥鱼原界面/Live2D、同源语音 protobuf 握手、原生会话和卸载后资源释放经过真实浏览器验证；未自动打开麦克风或屏幕。
- 屏幕链路以 HTTP 模型/TTS 夹具验证低意愿零回复、高意愿走现有 TTS、播放确认才回写、共享停止取消、过期结果丢弃、跨连接限额；这不是已测量的真实推理延迟或付费视觉能力证明。
- 屏幕功能默认关闭。浏览器显示原生 DSH 图片能力预检结果，文字/未知模型不允许先采集再假装看懂；能力检查不生成文本、不上传截图。运行时仍会在实际图像请求前复核。System One 与回复模型收到截图；DSH 可能按原生附件和临时会话日志持久保存。Pipecat 截图传输日志已脱敏。
- 后续已完成两次生成测试图的真实云端判断，其中允许分支走通原生 DSH 视觉、IndexTTS 和浏览器播放确认。没有采集真实桌面；测试等待阈值及开关已恢复。这与实际游戏语音的性能/概率校准是两回事，详见 [SCREEN_COMPANION.md](SCREEN_COMPANION.md)。

复验：`node scripts/check_dsh_community_runtime.cjs` 和 `node scripts/check_dsh_plugin.cjs`（后者需设置 `DSH_TEST_ORIGIN=http://127.0.0.1:3080`、`DSH_TEST_ENTRY_LOG=G:/dafeiyu/.runtime/dsh-active.log`）。日志中的认证 URL 不应公开；这些验收脚本不登录、不打开采集设备、不调用付费生成。
