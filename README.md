# 大肥鱼 · DSH 数字人语音插件

中文实时 Live2D 语音伙伴，以标准 `dsh.bundle` npm 插件包独立安装。

**DSH 负责模型调用、Agent harness、工具、子智能体、会话、人格和记忆；本项目只负责数字人、语音和屏幕交互。** 不自建另一套 Agent 或记忆系统，不修改 DSH 安装源码。

## 保留的能力

- 原有 Live2D 舞台、主题、输入框与设置界面；ShadowRoot 嵌入，不使用 iframe。切换面板继续保留应用和语音状态。
- 本地 ASR、VAD、声纹筛选、流式识别预览、播放确认、打断与实时近似元音口型。
- IndexTTS-2.5 / GPT-SoVITS GPU、MOSS-TTS-Nano ONNX CPU、DeepSeek / 兼容 TTS API；MOSS-Live 可选全双工模式。
- System One 情绪/动作/接话判断、屏幕陪玩、DSH 看屏幕工具、兴趣配置、长时间无交互主动接话，以及屏幕直接交给对话模型的模式。
- DSH 原生完整会话与消息内容，保留本项目的视觉外壳；可选完整蓝色大肥鱼人格，不覆盖用户已有的人格设置。

上述是保留的实现能力，不表示全新安装无需模型、授权或服务配置即可全部使用。GPU、云端 API 和真实麦克风仍需各自验收。

## 安装发行包

当前目标：**Windows x64 / Node.js ≥22 / DSH 0.2.2-rc.1**。无需预装 Python 或 uv。

```powershell
dsh plugin --profile web add "E:/Downloads/dafeiyu-dsh-live2d-0.3.0.tgz"
```

重启目标 DSH profile，打开侧栏「大肥鱼」，在首次安装向导选择 **E 盘资源目录**。安装器从远端自动准备经过 SHA256 校验的 uv、Python 3.12、两套隔离依赖和基础 ASR/VAD 模型，显示进度，失败可原地重试。官方源/中国镜像可选；可选 TTS 和声纹模型按需勾选。

Core 需确认官方许可；角色可导入合法取得的本地 ZIP，或填入有权使用的远端 HTTPS 地址、SHA256 并确认授权。未托管或捆绑无再分发授权的角色。暂不导入可进入原设置界面，但数字人显示仍需素材。

也支持无需寻找 uv 的一条命令：

```powershell
node <插件目录>/bin/cli.mjs install --home "E:/DafeiyuCompanion" --source china
```

向导选择的目录由 DSH 自己的插件存储记录，下次打开无需再设环境变量；命令行用户仍通过 `DAFEIYU_HOME` 或插件配置 `homeDir` 指定同一目录。依赖、模型、缓存、配置和日志都与包代码分离，不依赖原开发目录。下载不触发推理、付费调用、开麦或截图，原主界面样式不变。

**完整步骤：**[安装、资源导入、升级与卸载](docs/DSH_RELEASE.md)。角色、Cubism Core、权重、用户声线、密钥和聊天数据不随包发布；需显式下载或导入自己有权使用的资源。

## 开发与构建

```powershell
npm --prefix web ci --no-audit
npm --prefix web test
npm run test:release
npm run test:plugin
npm run release -- --out "E:/DafeiyuReleases/0.3.0"
```

构建原前端、收集白名单代码及第三方许可证，输出 `.tgz`、`SHA256SUMS` 与审计报告。CI 仅生成 artifact，不自动发布 npm 或公开 release。

- [原生 DSH 集成](docs/DSH_PLUGIN.md) · [完整聊天能力](docs/DSH_NATIVE_CONVERSATION.md)
- [协议](docs/PROTOCOL.md) · [语音模式](docs/TTS_MODES.md) · [System One](docs/SYSTEMONE.md)
- [屏幕与主动陪伴](docs/COMPANION_PRESENCE.md) · [实时口型](docs/REALTIME_LIPSYNC.md)
- [第三方声明](THIRD_PARTY_NOTICES.md) · [历史部署与验收资料](docs/LEGACY_README.md)

项目代码许可证尚待所有者确定，目前标记 `UNLICENSED`；第三方代码与人格保留各自原许可证。公开发布前还需确认包名权限及第三方授权。
