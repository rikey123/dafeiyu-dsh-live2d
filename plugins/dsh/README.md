# 大肥鱼 · DSH 原生插件

## 自动安装发行版 0.3.1

这是包含预编译原前端与语音后端代码的原生 `dsh.bundle` npm 包，不依赖原开发目录。当前声明 Windows / Node.js ≥22 / DSH 0.2.2-rc.1。

```powershell
dsh plugin --profile web add "E:/Downloads/dafeiyu-dsh-live2d-0.3.1.tgz"
```

重启 DSH，首次打开侧栏「大肥鱼」会出现自动安装向导：选择外部目录（建议 E 盘），自动从远端获取 uv、Python、隔离依赖和 ASR/VAD。可选官方/中国镜像，以及声纹、流式 ASR 和本地 TTS。无需预装 Python 或 uv。目录指针保存在 DSH 原生插件存储，不写回 npm 包。Core/角色分别确认许可；角色远端下载需要合法地址与 SHA256，不擅自托管原角色。完整步骤见包内 `docs/DSH_RELEASE.md`。

**角色直达**：[作者原发布页](https://www.bilibili.com/video/BV1KmxY66EZ3/) · [完整素材仓库](https://github.com/YJackie-Li/DeepSeek-chan) · [固定版本 ZIP](https://github.com/YJackie-Li/DeepSeek-chan/archive/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip)。素材仓库维护者身份未与原作者核实，不标作官方；请先阅读其使用须知。v0.3.1 支持直接导入该 ZIP，原始配布包也继续支持。详见 `docs/DEEPSEEK_SKIN.md`。

命令行：`node <插件目录>/bin/cli.mjs install --home E:/DafeiyuCompanion --source china`。通过命令行安装时，启动 DSH 需配置相同的 `homeDir` 或 `DAFEIYU_HOME`。

不依赖可能被包管理器禁用的 postinstall；下载在首次打开面板并选择目录后进行。若已显式配置 homeDir，首次打开会检查并补齐基础依赖（可用 autoInstall:false 禁止自动补齐）。安装不执行推理，权重、角色、密钥、聊天记录和缓存不进发行包。依赖就绪不代表真实语音或 GPU 验收通过。项目代码许可证尚由所有者指定，暂记 `UNLICENSED`；上游组件保持原许可证。

## 原生集成与源码开发

数字人面板注册在 DSH 的 `main` / `sidebar.panellist`，不是 iframe。原应用以隔离 ShadowRoot 挂载。DSH 提供模型路由、Agent loop、工具、权限及会话持久化；Python 侧只负责语音与数字人交互。

详细安装、生命周期、验收边界及回滚见项目的 `docs/DSH_PLUGIN.md`。源码安装入口 `src/index.mjs`；浏览器半面是 DSH 官方 ModuleLoader closure-factory 格式 `src/client.js`。宿主加载本地插件时会发现本包的 `dsh.client`。

原生聊天迁移见 `docs/DSH_NATIVE_CONVERSATION.md`：保留数字人主题与外壳，复用完整 DSH Conversation Factory；会话、人格、任务及记忆归 DSH。语音停播不取消后台任务，会话级订阅接收后续回复。

用户明确要求：插件不迁移旧 memory，不保留旧记忆 CRUD / 注入，不安装新记忆 MCP。现有独立版数据库不删除。

开发测试：`node --test plugins/dsh/test/*.test.mjs`。这些隔离测试不证明真实麦克风、声学回声消除、GPU 推理或外部付费 API 已验收。
