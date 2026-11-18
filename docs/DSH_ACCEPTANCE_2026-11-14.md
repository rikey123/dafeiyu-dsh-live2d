# DSH 插件本机集成验收 · 2026-11-14

环境：Windows，已安装的 DSH **0.2.2-rc.1**，用户已有 `web` profile，项目 `G:/dafeiyu`。未修改 DSH 安装源码、provider 凭据或用户其他插件；项目/模型未复制到系统盘。配置仅在既有 DSH profile 追加受标记管理的插件条目。

## 真实运行证据

- DSH 原生侧栏「大肥鱼」加载原 App，ShadowRoot 隔离而非 iframe；Live2D、WASM 和同源资源正常，无浏览器脚本错误或资源失败。
- 原生会话 create/read/archive 成功；插件不列出其他组件的会话。archive 不是永久删除。
- `/dafeiyu` 无认证返回 401，非法 Origin 返回 403；Python API/WS 另有私有令牌边界。
- 首次进入与重新激活均完成 RTVI bot-ready；切到其他面板后，本插件 voice WebSocket 和 AudioContext 关闭，DSH 自身连接不被关闭；恢复不自动开麦。
- 普通 smoke 和 live smoke 均没有调用麦克风；前端没有旧 memory API 请求，手工检查已认证的旧 memory 接口返回 410。旧 SQLite 聊天/记忆不导入或注入；语音、人格等设置仍读原配置库。

### 一次真实短文字回复

显式设置 `DSH_TEST_LIVE_TURN=1`，从嵌入前端发送短验收提示词，调用 DSH 当前的 **deepseek-flash**。当前保存的 GPU 路由实际使用 **GPT-SoVITS-v5-turbo**，不能将此结果称为 IndexTTS 测试。

浏览器收到 **55 个音频帧 / 107735 wire bytes**，worklet 确认消费后，DSH 原生会话读取到 **7 字 assistant 已播放 prefix**。不是 mock、画布显示、健康检查或仅有生成字幕。测试不记录正文。

此处 wire bytes 包含协议开销，不是原始 PCM 样本数；worklet 消费不等于物理扬声器听感，也不是麦克风/ASR 验收。未据此宣称延迟改善或实时性分位数。

## 安装与资源清理

- 已在真实 `web` profile 持久 Install，再由 `scripts/dsh_plugin.ps1 -Action Start -Profile web -Port 3080` 启动，不叠加临时 overlay；完整普通浏览器 smoke 通过。
- 停止本轮实例后实际执行 Uninstall，文件 SHA-256 与首次 Install 前的 ignored 备份一致；随后重新 Install。未输出 profile 内容。fixture 验证重复 Install 幂等、空序列精确恢复、Start 去重、环境恢复。
- Windows base 服务沿用现有 pywin32 suspended-create + Job containment；只管理自己创建的进程，不按端口或镜像名杀其他服务。服务 stdin 为 NUL，不继承宿主存活 pipe。
- 真实 DSH 宿主异常退出前，记录了 3080、8765、8766、8770 的监听 PID。退出后这些 PID 和监听均消失，GPU worker 没有遗留。该次退出检查约 713 ms，仅是一次生命周期观测，不是推理延迟承诺。
- Windows fixture 另验证 stdin EOF、启动期 EOF、launcher 退出、清理异常和 supervisor 实际解释器被强杀；borrowed 服务及其子进程保持运行。Linux 分支仅有单元验证。

## 回归

| 范围 | 结果 |
| --- | --- |
| Node 插件 / bridge / harness / proxy / lifecycle | 25 passed |
| Python 后端（包括 11 项 supervisor 生命周期测试） | 327 passed, 1 skipped |
| 语音适配，不含独立声纹环境 | 107 passed, 1 skipped |
| 声纹独立环境 | 3 passed |
| 前端 | 136 passed |
| standalone build 与 DSH build | passed |
| 安装脚本 fixture | passed |

测试分别使用已有 `.venv-voice` 和 `.venv`，TEMP/TMP 指向 E 盘；没有将缺依赖的混合环境测试当成源码回归。仍有依赖弃用警告、一个既有测试的未等待协程警告，以及 standalone 大 bundle warning。

## 不能从本次结果推断的内容

尚未逐项真人实测：麦克风/流式 ASR、AEC、声纹、长时会话、打断/主动接话、SystemOne 情绪/动作、所有模型切换与错误恢复、MOSS CPU 音色、IndexTTS、远端 MOSS Live、其他付费 TTS API，以及 standalone 实际切回运行。相关实现、设置和单元/协议回归保留，不把 fixture 当成这些供应商或模型的可用性证明。

本机原始验收报告在 ignored 的 `.runtime/dsh-acceptance/`：`live-report.json`、`report.json`、`lifecycle.json`。原日志/配置备份可能含认证信息，不应公开上传。使用与安装说明见 `DSH_PLUGIN.md`，完整功能矩阵见 `DSH_FEATURE_PARITY.md`。
