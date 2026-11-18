# DeepSeek-chan（大肥鱼）素材获取与导入

## 直接获取，无需自行搜索

- **[作者原发布页（神宫凉子）](https://www.bilibili.com/video/BV1KmxY66EZ3/)**：原视频介绍了工房与群公告下载方式；[作者主页](https://space.bilibili.com/13737731)。
- **[完整素材仓库：YJackie-Li/DeepSeek-chan](https://github.com/YJackie-Li/DeepSeek-chan)**：模型、五张贴图、物理、参数说明、表情、动作均在仓库中。
- **[固定版本 ZIP 直接下载](https://github.com/YJackie-Li/DeepSeek-chan/archive/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip)**：无需 Git，不用逐个下载文件。
- **[该版本的使用须知](https://github.com/YJackie-Li/DeepSeek-chan/blob/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f/README.md)**。

核对日期：2026-11-18。本次下载 ZIP 的 SHA-256：`79f4afc36d07c5a75c6181804e2a788ea5330606054046ebaa77bfee930d8008`（49,738,232 字节；记录本次实际下载，不替代来源与授权核对）。参考版本：`824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f`。GitHub 仓库是社区公开存放，尚未核实维护者与原作者的身份关系，不称为作者官方仓库。下载前请自行确认来源及使用条件；我们不把其公开可下载误说成已获任意再分发授权。作者原发布页是来源确认的首选。

## 发行插件：下载后直接选 ZIP

1. 将下载的 ZIP 保存在例如 `E:/Assets/`，**不要解压或改内部文件名**。
2. 打开 DSH 的「大肥鱼」首次安装向导，将完整文件路径填入「本地角色 ZIP 路径」。旁边也提供了上面的直接入口。
3. 确认独立的 Cubism Core 许可，点击安装。v0.3.1 支持原始 `DeepSeek免费公皮.zip`，也支持上述 GitHub 仓库 ZIP；旧 v0.3.0 仅支持原始配布目录，需要升级后才能导入 GitHub ZIP。

已经完成初装时，用随包 CLI 补充角色，不需要重装 Python、ASR 或 TTS：

```powershell
$plugin = Join-Path $HOME '.dsh/profiles/web/node_modules/@dafeiyu/dsh-live2d'
node (Join-Path $plugin 'bin/cli.mjs') avatar --home "E:/DafeiyuCompanion" --archive "E:/Assets/DeepSeek-chan-824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip"
```

使用相同的 `homeDir` / `DAFEIYU_HOME`，刷新数字人面板。自定义 DSH_HOME / profile 时相应替换插件目录。导入目标为 `<home>/public/models/deepseek`。

## 源码开发导入

在仓库根目录执行；按实际环境替换 Python 路径：

```powershell
.\.venv\Scripts\python.exe scripts\import_avatar.py "E:/Assets/DeepSeek-chan-824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip" --output ".\web\public\models\deepseek"
```

导入器保留原始模型、纹理、物理、参数说明、表情、动作的名称及相对路径，额外生成 `avatar.model3.json` 注册已有表情与动作，**不修改原始 `.model3.json`**。原始使用须知或仓库 README 的完整内容原样保存为 `使用须知.txt`；PSD 不用于运行，也不会被解压。导入前校验路径、符号链接、文件数量与大小、模型依赖和使用须知；缺须知或有多个同名模型时明确失败。重复导入覆盖本角色目录中对应文件，不删除其他模型目录。这不是任意 Live2D 模型的通用转换工具。

## 署名与许可

模型名称：**DeepSeek-chan（大肥鱼）**。

- 原画及拆分：**神宫凉子**。
- Live2D 建模：**霓虹猫_NeonNeko**。
- 模型来源：**神宫凉子免费配布模型**。

使用须知允许个人直播、视频创作、社交媒体与二创展示，并要求署名；**仍禁止擅自重新上传完整模型文件**，商业广告等用途需另行联系作者。本项目提供可点击来源与兼容导入，不重新托管完整模型，也不把代码许可覆盖到角色上。应以获取的素材随附条款和权利人的授权为准。Cubism Core 是另一项独立许可，不包含在素材仓库的角色授权中。

## 渲染兼容

原版 `pixi-live2d-display@0.4.0` 渲染本模型鼻部时出现黑块。现已复用 AIRI 的 drawable multiply/screen color 补丁修正，恢复原始鼻线，移除临时隐藏 `Part46` 的处理；原始模型文件未修改。补丁来源见 `web/patches/README.md`。头部和身体通过 AIRI MAGIC 待机、说话配置驱动，设置中的“自然动作”可关闭这一层，嘴部仍跟随实际播放音频。
