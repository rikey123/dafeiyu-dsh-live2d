# 实时口型：当前实现与验收

更新：2026-11-14。

## 只保留实时路径

MFA 已从应用设置、API 模型、健康探测、启动器、TTS 适配器、播放协议和浏览器消费者移除。当前本地 GPU、CPU、API 及 MOSS-Live 输出统一进入已有浏览器 PCM 播放链，不为口型等待整句 WAV、外部对齐服务或音素时间轴。

数据库打开时幂等删除旧 `tts_alignment` / `mfa_url`，保留模型选择、音色、密钥与聊天记录。旧客户端继续提交这两个字段会收到 422，需刷新页面。`--mfa` 及对应 sidecar 不再是有效启动入口；8771 不再参与就绪判断。历史离线研究文件仍可保留，但不由应用加载；E 盘既有 MFA 环境、模型和缓存未自动删除。

## 实现边界

复用当前锁定的 wLipSync WASM/MFCC AudioWorklet、AIRI 元音驱动和官方 Pipecat 播放 worklet，不引入第二套推理或渲染引擎：

```text
所选 TTS 的 PCM → Pipecat 播放 worklet → 用户音量/duck 增益 → 扬声器
                                                ├→ RMS 分析（显式回退）
                                                └→ wLipSync 元音分类 → 播放时钟门 → Live2D 嘴参数
```

- 实际 worklet 消费 PCM 后才激活口型，不以服务器开始合成或收到网络数据代替播放证据。已停止、已结束的 epoch 不能由迟到的消费回调重新激活。
- 分类时间戳在进入上游平滑器**之前**验证，丢弃打断前、重复、乱序、非法或明显未来的消息，避免旧帧改写新嘴形或产生负时间步。
- 静音、停止、断连、暂停音频上下文时清零。120ms 内无实际消费也闭嘴；仍在播放但分类过期时使用 RMS，而不是冻结旧元音。该阈值是故障保护，不是主动加入 120ms 音频缓冲。
- 分类回调步长从 512 改为 256 样本，上游平滑参数从 0.05 改为 0.025 秒。去掉角色层的第三重平滑；RMS 回退仍保留原张嘴平滑，不更改音频调度和播放 ACK。
- 编译后的不可变 WASM 和模块跨重连缓存，每个 AudioContext 各建节点。失败缓存可重试，关闭中的上下文不挂载迟到节点。初始化异步进行，不能阻止 PCM 播放。
- 默认通用元音模板；旧 VITS 专用模板保留手动选择，并明确只对应旧声线。**通用模板尚未针对当前 GPT-SoVITS/MOSS 声线校准**，不宣称分类准确率提高。
- WASM 初始化失败时设置显示“音量口型回退”，声音与消费确认继续工作。音量驱动不是音素识别；暂时分类过期也不代表识别成功。

关键代码：`web/src/avatar/lipsync/{runtime,realtime,vowel-driver}.ts`、`web/src/voice.ts`、`web/src/Avatar.tsx`、`web/src/playback.ts`。服务端 `PlaybackStart` 不再延迟起播或发送 `voice.playback.phonemes`。

## 可复现验收

先构建前端，使用 `scripts/serve_voice_acceptance.py --tts-mode gpu --gpu-tts-model gpt_sovits --manage-model-services --reply "你好，很高兴和你聊天。"` 启动隔离网关，再运行 `node scripts/check_realtime_lipsync.cjs`。依赖真实本地 ASR 服务就绪、GPU/CPU TTS 环境和 Edge；网关使用独立数据库，不改变生产模式。临时目录、模型和产物须配置到 E 盘。

此工具使用正式构建的 UI、Edge、Live2D、实际本地 TTS 和 AudioWorklet，禁止访问麦克风；LLM 是明确标注的本地固定回复服务，不调用 DeepSeek 或收费 API。验证消费样本、实际模型嘴参数、ACK 和历史落库，不把端口可达当作成功。

覆盖：

1. GPU GPT-SoVITS 播放：实际 PCM、元音分类、不同嘴形、完整 ACK 与历史。
2. CPU MOSS-TTS-Nano 同路径验证。
3. CPU 播放中静音闭嘴、取消静音恢复、停止闭嘴、迟到帧不重开，下一轮继续工作。
4. 切换模板重连后播放正常，WASM 只下载一次，各上下文独立节点。
5. 主动阻断 WASM 下载，界面明确回退，RMS 嘴动、播放、ACK、历史仍正常。

完整报告：`E:/Dafeiyu/verification/realtime-lipsync/browser-realtime.json`。运行日志、自动化测试结果同目录。真实扬声器声画偏差、真人中文音素准确率、跨声线视觉质量和麦克风双讲未由此验收。

本轮两次真实浏览器验收均为 5/5，通过且无页面异常。最终构建的单次观测：

| 观测 | 结果 | 解释 |
| --- | --- | --- |
| GPU / CPU 实际消费 | 51,840 / 61,440 样本 | 24kHz 输出，完整消费确认与历史落库通过 |
| 活跃分类消息到首次嘴动 | GPU 6.6ms / CPU 26.4ms | 浏览器消息/渲染观测，不是物理声画偏差 |
| 静音 / 停止到观测闭嘴 | 102ms / 151ms | 包含 Playwright 操作及轮询开销，仅单次功能观测 |
| 重连 WASM 请求 | 1 次 | 5 个上下文节点累计，非同时保留 5 个活动连接 |
| 强制 WASM 加载失败 | 播放及 ACK 通过 | 分类消息 0，明确使用 RMS，不冒充元音分类 |

自动回归：后端 `tests/` 169 通过、1 跳过；前端 97 通过，生产构建成功。语音网关环境 109 通过、1 跳过、1 项真实 Silero 测试移交原生语音环境；原生环境相应语音测试组 16 通过。网关环境不安装 `sherpa_onnx`，直接在那里运行真实声纹测试会因缺少该依赖失败，不能当作模型故障。跳过项仍未由本轮验收。Python 源码和三个更新的 JS 验收入口语法检查通过。Vite 仍提示现有大 bundle 警告，未在本轮额外调整打包策略。

`firstMouthAfterConsumptionMs` 包含音频前导静音；`firstMouthAfterActiveClassifierMessageMs` 是主线程分类消息到渲染观测，不是声卡输出到嘴形的物理延迟，也可能因初始化期间 RMS 先张嘴而为负。`submitToAckMs` 含模型加载、合成、整句播放，不是首音或口型算法耗时。不要把这些单条样本读成端到端延迟保证。

## 未解决的独立问题

删除 MFA 消除了其 7–14 秒级离线对齐等待，不代表 TTS/DeepSeek 的首音等待消失。GPU 合成中取消后立即续说的 worker 重建窗口问题仍单独待修；本轮 CPU 停止恢复通过，不证明 GPU 生命周期缺陷已修。既有相关证据见 `FEATURE_AUDIT_2026-11-14.md`。
