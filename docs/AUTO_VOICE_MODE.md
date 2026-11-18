# CPU / GPU 自动语音模式

界面现已提供 `auto/cpu/gpu/api` 可选模式，明确保存的选择优先于启动环境。本文说明本地自动选择的准入与回退；旧部署使用 `legacy` 保留原行为，完整配置见 [TTS_MODES.md](TTS_MODES.md)。

| 模式 | 语音识别 | 语音合成 |
| --- | --- | --- |
| `auto`（默认） | SenseVoice INT8 CPU | 运行环境支持 CUDA 且满足显存准入时使用 Fun-CosyVoice3-0.5B；否则使用原来的本地 VITS |
| `cpu` | SenseVoice INT8 CPU | 原来的本地 VITS，不启动 CosyVoice sidecar |
| `gpu` | SenseVoice INT8 CPU | 要求 Fun-CosyVoice3 CUDA，不静默改用 CPU |
| `manual` | 沿用本地配置 | 沿用应用已有的 `tts_engine=local/cosyvoice` 设置 |

## 检查依据

GPU 探测在独立 CosyVoice Python runtime 中执行，使用 PyTorch `cuda.is_available()` 和 `cuda.mem_get_info()`；Intel 核显、设备名称或系统能枚举显卡均不算 CUDA 推理可用。探测不会加载第三代模型。正常自动启动会保留一个轻量 sidecar，无 GPU 时不加载缓慢的 CosyVoice CPU 模型。

默认总显存至少 **7.5 GiB**、可用显存至少 **6 GiB**，可以通过 `DAFEIYU_COSY_MIN_TOTAL_GIB`、`DAFEIYU_COSY_MIN_FREE_GIB` 修改。这是保守的可配置准入策略，并非目标显卡上测得的最低模型需求，也不保证模型一定装得下。预热模型自身 PyTorch allocator 已保留的显存会加回计算；其他进程占用不会加回。

每个新回答前检查路由，回答中途固定引擎。GPU 侧请求初始化还会强制重新探测，避免检查后显存被其他应用占用。正常完成后复用上游热模型；取消仍由已有 Pipecat 与隔离 worker 回收机制管理。

路由直接复用 Pipecat 官方 `ServiceSwitcher`，两种引擎保留自己的原生 TOKEN／SENTENCE 聚合、音频上下文、采样率转换、打断和对齐机制。GPU 被选中后若发生 OOM 或合成错误，该轮明确报错，下一个回答优先使用 CPU 一次，随后恢复探测。不在当前回答里重放缓存文字，避免已播放部分重复、文本确认和音频上下文不一致；即使错误发生在首音前，也采用相同的停止策略。

`GET /api/status` 的 `optional.cosyvoice` 保留实际加载设备、模型、精度，并新增 `gpu_eligible`、`hardware`；`hardware.reason` 区分 `eligible`、`cuda_unavailable`、`insufficient_memory`、`probe_failed`。探测合格不代表权重已加载；`loaded/ready` 仍独立报告。

`voice_policy={requested,saved_mode,predicted,reason,prediction_only:true}` 报告部署策略和按健康状态预测的新回答路由，不把预测显示为实际 GPU 推理。各个连接在 GPU 故障后的 CPU 优先状态属于连接内部，因此预测不等同于其最近一次选择。

## 部署与启动

本地忽略的 `.env` 设置：

```dotenv
DAFEIYU_VOICE_MODE=auto
DAFEIYU_COSY_MIN_FREE_GIB=6
DAFEIYU_COSY_MIN_TOTAL_GIB=7.5
```

```powershell
.venv\Scripts\python.exe scripts/run.py --stop
.venv\Scripts\python.exe scripts/run.py --no-local-llm
```

已有 CUDA runtime、权重和参考声音配置保留。自动模式会给受管理的 sidecar 设置第三代、自动设备和自动精度；进入 CUDA 路径时启用上游 FP16。`--no-optional-voice` 代表 sidecar 由外部管理，不启动新实例；外部服务必须使用相同策略配置。独立启动 `server.main` 未设模式时使用 `manual`，避免改变其他测试和旧部署。

升级到 NVIDIA GPU 的机器后，须先在 **CosyVoice 独立 runtime** 安装与驱动兼容的 CUDA PyTorch。现有 CPU-only torch 不会因插入显卡自动变成 CUDA 版本；此时自动模式继续诚实使用 VITS。当前 Intel Arc 核显机器用于验证真实 CPU 回退，GPU 路由使用模拟硬件单元测试；8GB GPU 的实际峰值显存、首音和持续运行仍需目标机实测。

本模式不自动启用 MFA；显式启用 MFA 仍会等待真实音频对齐再播放。ASR、VAD、声纹继续运行于 CPU，避免争抢合成显存。本地健康状态独立报告实际加载的 CPU 模型、后备机制或错误，不会假称 VITS 或 GPU 已就绪。

## 本机验收

自动模式在旧设置 `tts_engine=cosyvoice` 下，仍因实际 `cuda_unavailable` 选择 CPU VITS。使用隔离数据库和固定 SSE 中文回复，不调用云端、不采集麦克风；两轮真实 Pipecat protobuf PCM 合成通过，未发送伪造播放回执，未确认音频不会写入正式 assistant 历史。另一次测试收到首块 PCM 即发送 Stop，下一轮仍成功产出完整片段，Cosy 模型保持未加载。

两轮完整片段测试的首块服务端 PCM 约 0.25／0.22 秒；打断测试约 0.41／0.41 秒。测量从发送测试文字起计，包含固定 SSE 服务与本地 VITS，但不包含真实 DeepSeek 网络耗时、浏览器消费、声卡或人的听感。

证据：[完整片段测试](AUTO_VOICE_ACCEPTANCE_2026-11-07.json)、[中途停止与下一轮恢复](AUTO_VOICE_INTERRUPT_ACCEPTANCE_2026-11-07.json)。运行方式：先以 `DAFEIYU_VOICE_MODE=auto` 启动 `scripts/serve_voice_acceptance.py --tts-engine cosyvoice --reply "你好，这是自动语音模式测试。"`，再使用语音环境运行 `scripts/check_auto_voice.py --interrupt-first`。真实 GPU 尚未验收；原生 Pipecat 模拟切换及 GPU 错误不重播另由 `speech/test_auto_tts.py` 验证。

最终后端回归 **118 passed**（134.11 秒）：`tests/`、`speech/test_pipecat_services.py`、`speech/test_cosy_bistream.py`、`speech/test_alignment_tts.py`、`speech/test_mfa_sidecar_health.py`、`speech/test_auto_tts.py`。覆盖无 CUDA、总显存不足、空闲不足、阈值通过、5 秒缓存与强制刷新、已退出热模型、原生 CPU→GPU→CPU、GPU 首音前后错误不重播、探测取消、设置兼容及既有播放历史/取消/对齐。三个警告均为已有 Pipecat／Python 弃用提示。
