# Fun-CosyVoice3 本地语音

本项目选用官方 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 基础权重，固定 revision 为 `29e01c4e8d000f4bcd70751be16fa94bf3d85a18`。采用已有 CosyVoice 上游加载器、原生持续文本输入与流式音频输出，不自行实现推理引擎。第二代仅作为显式可选兼容项。

## 模型准备

```powershell
.venv\Scripts\python.exe -m server.cosyvoice_prepare models/cosyvoice3 --version 3
.venv\Scripts\python.exe -m server.cosyvoice_prepare models/cosyvoice3 --version 3 --verify-only
```

准备器固定每个权重的大小和 SHA256，配置与 tokenizer 文本固定 Git blob 摘要。缺失、损坏或第二代 YAML 不能作为第三代加载。共享的 BlankEN 权重与 campplus 可以在校验后复用。

## 配置和启动

在忽略的本地 `.env` 中设置以下模型字段，其他已有字段和密钥保持原值：

```dotenv
DAFEIYU_COSY_MODEL=D:/project/dafeiyu/models/cosyvoice3
DAFEIYU_COSY_VERSION=3
DAFEIYU_VOICE_MODE=auto
DAFEIYU_COSY_DEVICE=auto
DAFEIYU_COSY_PRECISION=auto
```

`DAFEIYU_COSY_SOURCE`、`DAFEIYU_COSY_MATCHA` 和独立 Python runtime 沿用已经安装的上游环境。参考 WAV 必须配合其实际文字；第三代所需的 `You are a helpful assistant.<|endofprompt|>` 前缀由适配器补入，不应写入真实参考音频的转写结果。

```powershell
.venv\Scripts\python.exe scripts/run.py --cosyvoice
```

已运行时先用 `scripts/run.py --stop` 正常退出。正常启动器默认自动选择第三代 GPU 或原来的 VITS CPU，见 [AUTO_VOICE_MODE.md](AUTO_VOICE_MODE.md)。`DAFEIYU_VOICE_MODE=manual` 才沿用应用中的 **Fun-CosyVoice3** 选择；配置协议键继续使用 `tts_engine=cosyvoice`。口型可继续使用实时 MFCC；MFA 模式需要本次音频完成对齐后才播放，会增加等待。保存设置后重新建立语音连接，麦克风不会自动开启。

## Windows 原生 CUDA 服务

Windows 可以在忽略的 `.env` 中指定独立 Python，无需 WSL。以下是安装位置示例；解释器内必须先安装适合本机显卡的 CUDA PyTorch、对应 torchaudio 及上游 CosyVoice 依赖：

```dotenv
DAFEIYU_COSY_PYTHON=E:/Dafeiyu/runtimes/cosyvoice-gpu/Scripts/python.exe
DAFEIYU_COSY_MODEL=E:/Dafeiyu/models/cosyvoice3
DAFEIYU_COSY_SOURCE=E:/Dafeiyu/source/CosyVoice
DAFEIYU_COSY_MATCHA=E:/Dafeiyu/source/Matcha-TTS
DAFEIYU_COSY_PROMPT_WAV=E:/Dafeiyu/source/CosyVoice/asset/zero_shot_prompt.wav
```

启动器优先使用该解释器，在 `127.0.0.1:8770` 启动服务。停止项目时会先通知服务回收推理进程。未配置该字段时保留原来的 WSL 启动方式。原生入口固定 PyTorch DLL 的枚举顺序，避免本次 exFAT 安装中观察到的 DLL 加载挂起；建议将运行环境及权重放在 NTFS 数据盘。

初次模型加载最多等待 300 秒，文本消费和后续音频仍使用独立的 120 秒超时；超时时界面会显示 `TimeoutError`，避免只有空白失败原因。

## 8GB NVIDIA GPU 部署

必须为独立语音 runtime 安装与驱动兼容的 CUDA PyTorch。现有 `requirements-cosyvoice-cpu-lock.txt` 是 CPU 环境快照，不能作为 GPU 安装完成的依据。

```dotenv
DAFEIYU_VOICE_MODE=auto
DAFEIYU_COSY_DEVICE=auto
DAFEIYU_COSY_PRECISION=auto
```

`auto` 在 CPU 上使用 FP32，在 CUDA 上启用上游 FP16 路径；这不是所有模块均为 FP16 的承诺。CPU 上明确请求 FP16、CUDA 不可用或版本不匹配均报错，不静默加载第二代或将 CPU 标为 GPU。健康状态在模型实际加载后才报告实际设备和精度。

初次部署让 SenseVoice、在线识别、VAD 和声纹继续运行于 CPU，避免它们与 TTS 争抢 8GB 显存。暂不启用 TensorRT/vLLM；需要先确认其与原生文本生成器和取消机制兼容。8GB 是否足够、首音延迟、峰值显存和持续聊天稳定性必须在目标显卡上测量。

## 无麦克风验收

```powershell
.venv-voice\Scripts\python.exe scripts/check_cosyvoice3.py
```

验收使用实际权重，验证两个文本片段的消费确认、PCM 输出、中文 ASR 回读、正常结束后的模型复用、出声前后取消后的清理及模型复用，并保存 WAV 和测量记录。首轮记录为 first，initially_loaded 标识启动验收前是否已有热模型；不会把热模型结果标成冷启动。它不采集麦克风，也不代表真人听感、GPU 或声卡延迟验收。

播放、打断、样本回执、口型和正式历史继续复用当前 Pipecat 链路。参考声音仍是本地配置的样例，选择第三代模型不会自动获得某个人或角色的授权声音。

## 2026-11-07 本机结果

此前手动选择第三代时，启动器管理的8770服务完成过实际模型预热。该次实际设备为 CPU／FP32，浏览器测试使用固定本地 LLM 回复以隔离语音链路，未采集真实麦克风。12个必要文件校验、双片段消费确认、真实中文合成、ASR去标点回读一致、模型热复用、取消回收、真实Edge/Cubism嘴形变化、准确播放回执和正式历史均通过。之后的自动模式在本机无 CUDA 时选择 VITS，不继续加载 CosyVoice CPU。

单次独立测试：冷加载约51.59秒，首音距请求约63.36秒；热模型首音约14.13秒。正常服务另一次冷加载约54.83秒，合成完成后保留热模型。以上是CPU短句工程测量，不是GPU性能或真人听感结论。测试期间有一次重新加载超过300秒，原因未确定；重试及后续浏览器、正式服务冷启动成功，不能由此宣称所有环境的启动稳定性已验收。

证据见 [COSYVOICE3_ACCEPTANCE_2026-11-07.json](COSYVOICE3_ACCEPTANCE_2026-11-07.json)。真人音质、新音色的MFCC模板校准、真实外放双讲以及8GB GPU峰值显存/延迟仍单独验收。

## 2026-11-08 RTX 5080 实测

Windows 原生环境、Python 3.12.16、PyTorch/torchaudio 2.7.1+cu128，运行环境和模型位于 E 盘 NTFS。Fun-CosyVoice3-0.5B-2512 实际加载设备为 CUDA，使用上游 FP16 路径，已输出真实 24kHz 单声道 PCM。SenseVoice、VAD 及当前 ONNX 语音 tokenizer 仍使用 CPU；LLM 使用已配置的云端 DeepSeek。

同一短句“你好，我是大肥鱼。我们可以慢慢聊。”：首次迁移后准备模型约 50.88 秒，首音距请求约 69.20 秒；随后的新进程加载约 17.69 秒、首音约 36.09 秒。保留模型后的同句首音约 1.44 秒、总处理约 1.89 秒、输出约 3.84 秒音频。热模型保留了初始化缓存，不能将它作为冷启动性能。

双文本片段消费确认、实际 PCM、ASR 去标点回读一致、热模型复用、取消后约 0.33 秒回收均通过。以上为单次工程测量，不代表物理声卡延迟、真实麦克风对话或长时间稳定性。记录见 [GPU 验收 JSON](COSYVOICE3_RTX5080_ACCEPTANCE_2026-11-08.json)。

依赖快照为 `requirements-cosyvoice-windows-cuda-lock.txt`。使用 uv 安装时需要 `--index-strategy unsafe-best-match` 从 PyPI 和 CUDA 索引解析固定版本；旧版 openai-whisper 的构建需将构建环境 setuptools 固定为 `80.10.2`（可通过 uv 的 `--build-constraint`），以保留其依赖的 `pkg_resources`。不应直接把 CPU lock 安装到该 CUDA 环境。

真实 Edge 页面测试也已通过：显式 GPU 模式下，DeepSeek 云端回复经 CosyVoice CUDA 合成后实际进入浏览器播放器，Cubism 口型发生变化，全部播放回执与正式历史一致，页面无错误。该次测试从新进程首次合成开始，点击到首次口型约 41.13 秒，包含加载、网络、LLM、TTS 和渲染；未测量真实麦克风或物理扬声器。验收完成后服务保留热模型。


## 2026-11-08 打断处理修复

用户实测中，打断回复会把正常的 WebSocket 1000 关闭误报为“本地 CosyVoice 失败”，并触发“未生成音频”的二次错误。旧取消策略还会销毁模型，导致随后几轮语音首包等待达到 44.5、32.2、28.9 秒。这些是修复前的日志记录。

现改为先停止接收任务，再关闭连接；加载模型、等待文本确认或等待上一轮清理时被打断，也不会重新打开已取消的上下文。非预期的连接断开仍报告错误。服务端结束文本输入，丢弃本轮剩余输出，让上游生成器完整退出并清理线程及缓存，然后复用模型。清理期间保持占用名额；超过 8 秒或工作进程异常则回收进程。每轮恢复初始流式分块大小，避免热复用时首包分块不断增大。

回归测试不加载实际模型，覆盖出声前后打断、接着回复、忙碌重试、加载中取消、剩余输入和音频隔离、模型只构造一次及超时回收。按用户要求，修改时项目和 GPU 模型进程均已停止；本次未重新执行真实 GPU 推理，修复后的设备延迟仍待实机验证。上方原有 GPU 测量属于修复前版本，不作为本次修复的验收结果。

实际模型验收脚本新增出声前后取消及随后继续合成的检查，以 ready/health 的 worker_pid 确认同一模型进程得到复用。正常取消后模型继续驻留；需要释放显存时应停止项目。
