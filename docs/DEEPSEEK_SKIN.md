# DeepSeek-chan 本地皮肤

此项目可以从用户自行获得的 `DeepSeek免费公皮.zip` 导入角色，模型文件不会提交到 Git。导入命令在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\import_avatar.py ".\DeepSeek免费公皮.zip" --output ".\web\public\models\deepseek"
```

脚本保留原始模型文件、纹理、物理、参数说明、表情和动作的名称及相对路径，并生成额外的 `avatar.model3.json`，用于注册压缩包中已有的表情和动作。原始 `.model3.json` 不会被修改。PSD 不用于运行，也不会被解压。重复导入覆盖本角色目录中对应的文件，不删除其他模型目录。导入时会验证路径、符号链接和文件大小；运行后打印参数 ID 和动作名。

模型名称：DeepSeek-chan（大肥鱼）。原画及拆分：神宫凉子；Live2D 建模：霓虹猫_NeonNeko；模型来源：神宫凉子免费配布模型。原始使用须知保存在导入后的 `使用须知.txt`，应以该文件为准。该须知允许个人使用和个人直播、视频创作及相关平台收益；公开创作需注明来源及制作人员。不得擅自重新分发或出售完整模型；品牌广告、产品推广及作为付费商业产品一部分等用途需要事先联系作者。此导入工具不提供模型素材下载或再分发。

原版 `pixi-live2d-display@0.4.0` 渲染本模型鼻部时出现黑块。现已复用 AIRI 的 drawable multiply/screen color 补丁修正，恢复原始鼻线，移除临时隐藏 `Part46` 的处理；原始模型文件未修改。补丁来源及安装方式见 `web/patches/README.md`。角色的头部和身体通过 AIRI MAGIC 的待机、说话配置驱动，设置中的“自然动作”可关闭这一层，嘴部仍跟随实际播放音频。
