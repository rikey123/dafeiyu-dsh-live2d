# 可选语音工程链路

> **2026-11-14 当前状态：MFA 运行功能已退役。** 本文涉及 MFA 的实现、安装、命令、测试和结果均为历史记录，不是当前可选功能；相关启动/安装/浏览器时间轴验收入口已经移除。当前仅使用实时 PCM 口型，见 [实时口型](REALTIME_LIPSYNC.md)。E 盘历史环境与权重未自动删除。下文旧“当前”描述不再代表现行状态。

> 本文仅保留历史 CosyVoice/VITS/WSL/MFA 链路说明。当前 TTS 路由以 [TTS_MODES.md](TTS_MODES.md) 为准；MFA 已从应用移除。下面的服务表、配置和命令均不代表当前可用入口。

CPU 推理耗时单独记录，不再作为推迟接入工程机制的条件。默认语音配置保持可用；应用设置提供可选的 Fun-CosyVoice3 连续文本合成和 MFA 普通话音素对齐。两者的模型状态、实际设备和等待时间必须分别报告，安装完成或服务端口存活不表示模型已经推理成功。

## 服务与模型

| 服务 | 地址 | 复用上游 | 机制 |
|---|---|---|---|
| 本地普通语音 | `127.0.0.1:8766` | sherpa-onnx / SenseVoice / VITS | 默认中文识别和合成，Pipecat 负责轮次和打断 |
| 连续文本合成 | `127.0.0.1:8770` | 固定版本 Fun-CosyVoice3-0.5B、Matcha | 一个原生文本生成器持续接收 LLM 文本；隔离推理进程；有界队列；取消后有界清理并复用，超时回收 |
| 普通话音素对齐 | `127.0.0.1:8771` | Montreal Forced Aligner 3.3.9 / Mandarin MFA | 本次真实 TTS WAV → IPA 音素区间 → 文件哈希校验 → 同一播放 epoch 的样本时钟口型 |

CosyVoice 的模型、代码和参考 WAV 路径只能由本机配置提供。WebSocket 客户端不能传任意文件路径。MFA 接受有大小和时长限制的 WAV 上传，不接受调用者提供文件路径。所有服务绑定回环地址。

## 启动

第三代模型、精度与 GPU 部署见 [COSYVOICE3.md](COSYVOICE3.md)。MFA 准备流程见 [MFA_ALIGNMENT.md](../speech/MFA_ALIGNMENT.md)，CosyVoice 模型及依赖见 [COSYVOICE_PROBE.md](../server/COSYVOICE_PROBE.md)。Windows 项目的 `.env` 使用 [.env.example](../.env.example) 中的可选字段填写本地运行环境和参考音频。API 密钥继续只留在现有本地配置中。

安装后的持久 Linux 环境位于 WSL 用户的主目录，避免 `/tmp` 被清理后环境消失：

- CosyVoice：`~/.local/share/dafeiyu-runtimes/cosy`
- MFA：`~/.local/share/dafeiyu/mfa`

在项目目录运行：

```powershell
.venv\Scripts\python.exe scripts/run.py --cosyvoice --mfa
```

如果应用已经运行，先运行 `scripts/run.py --stop`，等本项目进程正常退出，再执行上述命令。正常启动默认 `DAFEIYU_VOICE_MODE=auto`：保留轻量 CosyVoice 探测服务，有可用 CUDA 和足够显存时使用第三代，否则使用原来的 CPU VITS；详见 [AUTO_VOICE_MODE.md](AUTO_VOICE_MODE.md)。设为 `manual` 才沿用应用的合成引擎选择。MFA 仍由应用设置显式启用。`--no-optional-voice` 可使用自行管理的回环服务。

设置变更会关闭旧语音连接，新连接不会自动打开麦克风。MFA 模式必须等待本次 WAV 的对齐结果后才开始播放；对齐失败会显示错误，本次音频不播放。默认 MFCC 模式继续从实际 PCM 分析口型。音素时间轴不是从另一段示例音频套用，也不是按音量猜测音素。

## 取消和退出

CosyVoice 打断采用协作清理：立即停止当前播放，结束文本输入并丢弃本轮剩余音频，等待上游线程和缓存清理后复用已加载的模型。清理期间仍占用推理名额，超过 8 秒则回收进程。正常取消会保留模型显存；停止项目才会释放模型。退出流程会回收热模型进程。

[run.py](../scripts/run.py) 创建本次启动专属的生命周期文件；[wsl_voice_service.py](../scripts/wsl_voice_service.py) 持有自己启动的 Linux 进程组。正常退出先通知 WSL wrapper，结束并回收模型及其子进程，再关闭 Windows 启动器。仅结束 `wsl.exe` 可能留下模型进程，因此不以关闭启动窗口代替模型清理。

可以运行不访问声卡的清理检查：

```powershell
wsl -d Ubuntu --exec python3 /mnt/d/project/dafeiyu/scripts/check_wsl_voice_lifecycle.py
```

它启动测试子进程和孙进程，发送停止信号，并确认两者都不再运行。不会使用真实麦克风，也不会改变语音模型配置。

## 验收边界

当前工程接入和逐项证据维护在 [VOICE_COMPLETION.md](VOICE_COMPLETION.md)，JSON 为唯一状态来源。中文音质、实际外放回声、双讲、本人声纹误拒/误接受率仍需相应的真实录音和设备测试。GPU 和 NPU 的设备结果另行验收；CPU 的模型成功不能替代它们。
