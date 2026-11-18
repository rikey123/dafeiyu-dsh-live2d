# 首页展示素材

这些图片用于 GitHub README 的界面说明，不是模型文件、性能测试或可用性证明。

## 截图来源

- 日期：2026-11-18。
- 前端：主应用为 v0.3.0 对应的原始编译前端（v0.3.1 编译结果逐字节不变）；首次安装截图已更新为 v0.3.1，展示素材直达入口。开发提交 `4ce953ff4940a8776ce6f64a9da101fa9bade904`，公开发行快照 `51262a7269db61fac81b90a75cb5f8cf9010c522`。
- 方法：在 loopback 隔离预览页内挂载原 `mountDafeiyu`；安装页使用原 `mountInstallView`。通过 Microsoft Edge / Playwright 拍摄，没有修改原组件或样式。
- 数据：离线 HTTP 与 RTVI fixture，使用示例模式、未配置密钥及未就绪的推理状态。切换 GPU / CPU / API 仅为展示设置，没有保存、加载或运行推理模型。
- 未使用真实麦克风、桌面采集、付费服务、生产聊天记录、生产配置或认证信息。
- PNG 截图转换为压缩 WebP；安装页仅裁去空白边缘。未擦除、覆盖或伪造功能状态。
- 因未注入原生 DSH 聊天桥接，这组截图不展示 DSH 富内容聊天，也不把离线外壳当作完整宿主运行验收。

## 图片清单

| 文件 | 内容 |
| --- | --- |
| `banner.svg` | 手工编写的 SVG 项目封面，鱼标基于本仓库插件图标。 |
| `digital-life.webp` | 数字生命主题主舞台。 |
| `neon-companion.webp` | 霓虹全息主题主舞台。 |
| `avatar-wardrobe.webp` | 表情、眼镜、配件与手势抽屉。 |
| `tts-api.webp` | DeepSeek TTS API 及音色设置。 |
| `local-tts.webp` | MOSS-TTS-Nano ONNX CPU 模式设置。 |
| `gpu-tts.webp` | 本地 GPU 模式与模型选择。 |
| `interests-and-presence.webp` | 共同兴趣与空闲主动聊天参数。 |
| `screen-companion.webp` | Jev 判断后陪伴模式。 |
| `direct-screen.webp` | 屏幕直接交给 DSH 模式。 |
| `first-run-installer.webp` | 首次安装向导。 |

## 角色署名与权利边界

截图使用用户本地合法取得的 **DeepSeek-chan（大肥鱼）** 角色：

- 原画及拆分：**神宫凉子**。
- Live2D 建模：**霓虹猫_NeonNeko**。
- 模型来源：**神宫凉子免费配布模型**。

角色的使用须知允许个人内容创作、社交媒体及作品展示，并要求保留署名。完整模型禁止未经许可再分发；商业推广等用途需要另行联系作者。此处仅提供渲染结果截图，不提供模型、纹理、动作资源或 Core 下载。角色条款优先于本仓库应用代码的许可状态，截图不代表取得其他使用或再分发权限。

详见[角色说明](../DEEPSEEK_SKIN.md)、[第三方声明](../../THIRD_PARTY_NOTICES.md)与素材随附的原始使用须知。直接入口：[作者原发布页](https://www.bilibili.com/video/BV1KmxY66EZ3/) · [完整素材仓库](https://github.com/YJackie-Li/DeepSeek-chan)（社区存放，未核实维护者为作者本人）。
