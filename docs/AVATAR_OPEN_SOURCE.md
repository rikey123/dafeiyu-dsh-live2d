# AIRI MAGIC 来源与集成边界

`web/src/avatar/airi/` 复用 [Project AIRI 固定提交 759fff0e646364fe3ad78c64a12f5f9739877e7a](https://github.com/moeru-ai/airi/tree/759fff0e646364fe3ad78c64a12f5f9739877e7a) 的 MIT 代码。原始版权和许可见该目录 `LICENSE`。源码来源：

- `motion/`：`packages/motion-driver-magic/src/`，包含原项目测试。
- `driver/`：`packages/model-driver-magic-live2d/src/`，包含原项目测试。仅将三个 workspace 类型导入改为本地相对路径。
- `profiles/idle-calm.json`：上游 `packages/stage-ui/src/features/motions/live2d/assets/idle-calm.json`。
- `profiles/speaking-excited.json`：上游 `packages/stage-ui/src/features/motions/live2d/assets/speaking-excited.json`。
- `adapter.ts`、`adapter.test.ts`：本项目新增的框架无关适配器与检查。

上游两包和仓库根目录声明 MIT，动作数据未发现单独许可或来源说明；这不等于独立核实了动作录制素材的权利链。保留原始许可，实际发布前仍需结合素材使用场景核查。上游内部包标记为 private，需复制或自行构建，运行依赖 `es-toolkit`。

适配器使用 AIRI 的 VAR 拟合、生成器、滤波及 crossfade，并自行接入模型每帧更新；本项目没有使用 AIRI 的 `createDriver` 调度器。默认幅度为 0.6，设置可调 0.1–1.0，并接入上游 offsetX×20/offsetY×−40 的相对位置偏移。通用模型使用六个标准角度参数；DeepSeek-chan 经真实参数检查后改写物理输入 `AngleX/Y/Z`、`PositionX/Y/Z`，由原物理系统生成标准头身角度。其身体输入范围依据素材自带 VTube 配置为 [-30,30]，PositionZ 跟随 headZ，与作者的 FaceAngleZ 映射一致。动作在模型动作之后、呼吸与物理之前写入，嘴部在物理之后单独控制；此皮肤的 IDLE 不含眨眼曲线，另调用 SDK 眼睛眨动控制。关闭自然动作会平滑收敛为零。初始化按进程缓存拟合结果。它不包含 AIRI Vue 舞台、语音、自动情绪或视觉感知。模型绑定和显示效果需按具体角色单独实测。

渲染器使用与 AIRI 相同的 `pixi-live2d-display` 0.4.x 和 Pixi 6，并复用 [AIRI 同一固定提交的 Cubism4 multiply/screen color 渲染补丁](https://github.com/moeru-ai/airi/blob/759fff0e646364fe3ad78c64a12f5f9739877e7a/patches/pixi-live2d-display.patch) 中适用于当前 ESM 构建的部分。补丁与角色模型、Cubism Core 的许可各自独立。

## Open-LLM-VTuber 参考调查

参考 [Open-LLM-VTuber 提交 992309c0aa19845960228f880013d4685fde93b5](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/tree/992309c0aa19845960228f880013d4685fde93b5) 的源码及说明，项目后端和 Live2D 素材各自有许可，前端为独立仓库，不能把后端 MIT 直接推定为前端或角色素材的许可。

| 参考位置 | 核对结果 | 本项目的处理 |
| --- | --- | --- |
| `src/open_llm_vtuber/conversations/conversation_handler.py` | 中断处理取消任务，并将已听到的回复传回 agent | 当前直接使用 Pipecat 取消；无浏览器播放确认，未复制该实现 |
| `src/open_llm_vtuber/asr/asr_interface.py` | 定义音频数组的同步与异步转写接口 | 本地语音服务提供单独 ASR 接口；未复制该实现 |
| `src/open_llm_vtuber/tts/tts_interface.py` | 定义文本生成音频文件的同步与异步接口 | 本地语音服务提供 WAV 合成接口；未复制该实现 |
| `src/open_llm_vtuber/live2d_model.py` | 加载模型配置与情绪映射，文件本身不负责渲染 | 使用 AIRI 补丁后的 Pixi 渲染与本项目角色适配；未复制该实现 |
| `.gitmodules` 中的 `frontend` | 前端指向独立的 Open-LLM-VTuber-Web 仓库 | 没有复制或集成其定制前端 |

当前语音编排直接使用 Pipecat 1.15.0 及其官方客户端/媒体库；Hugging Face `speech-to-speech` 保持机制参考，没有直接接入。

## 元音口型来源（2026-11-06）

`web/src/avatar/lipsync/vowel-driver.ts` 和 `profile.json` 来源于 [AIRI 提交 11b8989f6dd7f840cf6b15ce59e367656fb11ac6](https://github.com/moeru-ai/airi/tree/11b8989f6dd7f840cf6b15ce59e367656fb11ac6) 的 `packages/model-driver-lipsync/src/shared/wlipsync/`，保留该提交根 MIT LICENSE。profile 是上游样例，不能称为已校准当前中文声音。

直接安装 MIT `wlipsync@1.3.1`，固定发行包由 package-lock 校验。源码归档固定于 [mrxz/wlipsync 177f3ac4095dbad81be0a800a8c6f975abe4ae04](https://github.com/mrxz/wlipsync/tree/177f3ac4095dbad81be0a800a8c6f975abe4ae04)，两者版本边界分别记录。发行包 WASM SHA256 见 [LIPSYNC_PROFILE_PROVENANCE.json](LIPSYNC_PROFILE_PROVENANCE.json)。运行时未改写其 DSP 或分类器。

本项目新增 `adapter.ts` 将元音映射至实际 moc 参数并读取默认值/边界；`local-vits-profile.json` 是本地 sherpa VITS 默认声线的合成录音模板。`scripts/calibrate_lipsync.cjs` 直接调用固定上游 WASM 的 `execute`/`mfccOut` 导出收集 MFCC、按其 profile 格式采样，不自写频谱分析器；这是一项本项目的离线校准适配，并非上游官方创建器。它依赖1.3.1导出符号，升级必须重新验证。48个模板槽位会对不足48的有效帧重复采样，独立帧数量记录在 provenance 中。输入标签 AEIOUS 中 S 仅作为齿音样例，AIRI 将其投到 I，不代表完整辅音识别。

实际模型参数包含 `ParamMouthOpenY`、`ParamMouthForm`、`Mouthpucker`、`MouthFunnel`、`MouthPuckerWiden`；不存在的参数不会通过 SDK 虚拟ID误写。校准与通用样例可在设置切换，切换重连但不打开麦克风。真实等响度浏览器测试已有独立验证，E/O/U 仍有误分类；不宣称中文精确音素对齐。
