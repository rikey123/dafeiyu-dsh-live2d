# 本地语音服务

服务在 `127.0.0.1:8766` 提供中文识别和离线语音合成，默认不访问网络。优先加载 `models/whisper-base-openvino` 并尝试 NPU；失败后优先使用本地 sherpa-onnx SenseVoice CPU int8，再回退 faster-whisper CPU int8。TTS 优先使用 sherpa-onnx 中文 VITS，模型未安装时使用 Windows SAPI（设备上需安装中文语音）。状态接口明确显示实际设备、加载错误和后备选择。识别按用户一句话进行，并非流式识别；TTS 按分句生成 WAV，并非流式模型。

```powershell
# 在仓库根目录，使用 Python 3.12 虚拟环境
python -m pip install -r requirements-speech.txt
python -m speech.prepare sensevoice asr tts
python -m uvicorn speech.server:app --host 127.0.0.1 --port 8766
```

现有 Hugging Face 缓存有 `Systran/faster-whisper-base` 时无需重复下载。下载 OpenVINO Whisper 并尝试 NPU：

```powershell
python -m pip install openvino openvino-genai
python -m speech.prepare openvino
$env:DAFEIYU_ASR_DEVICE = 'NPU'
python -m uvicorn speech.server:app --host 127.0.0.1 --port 8766
```

首次加载可能需要编译数分钟。启动时会用本地 TTS 合成中文句子进行识别自检；输出异常会判定设备不可用。模型及当前驱动能否编译、推理，必须查看 `http://127.0.0.1:8766/health` 并以实际识别测试为准，枚举到 NPU 并不意味着模型可用。自动和显式 NPU 失败后默认回退 CPU；如要诊断失败而禁止回退，设置 `$env:DAFEIYU_ASR_FALLBACK = '0'`。自动模式在自检失败后缓存失败信息 24 小时，避免每次重启都重新编译；设置 `$env:DAFEIYU_ASR_RETRY = '1'` 可立即重试。支持 `DAFEIYU_ASR_DEVICE=AUTO|NPU|GPU|CPU`；CPU 首选 SenseVoice。通过 `DAFEIYU_ASR_BACKEND=auto|sensevoice|faster-whisper` 选择 CPU 模型；`DAFEIYU_SENSEVOICE_MODEL`、`DAFEIYU_OV_WHISPER`、`DAFEIYU_WHISPER_MODEL` 和 `DAFEIYU_TTS_MODEL` 可指定本地模型目录。环境变量仅影响服务启动时加载；修改后重启服务。

模型下载是可重复执行的独立步骤，未完成的文件可续传。音色模型的权利与许可需参考对应模型卡：[sherpa-onnx-vits-zh-ll](https://huggingface.co/csukuangfj/sherpa-onnx-vits-zh-ll)、[OpenVINO Whisper](https://huggingface.co/OpenVINO/whisper-base-int8-ov)、[faster-whisper](https://huggingface.co/Systran/faster-whisper-base)。模型未内置于仓库。

## 接口

可选离线中文文本对齐实验使用独立 Python 环境安装 `speech/requirements-alignment.txt`，再运行 `python -m speech.prepare forced-aligner` 下载固定版本模型。命令 `python -m speech.forced_alignment input.wav "录音对应的文字"` 输出中文字符或词的起止秒数。输入须为 16 kHz 单声道 PCM16 WAV、最长 30 秒；参考文字需要与音频一致。该模型是离线 CPU 推理，输出不包含音素时间戳，也不表示对齐准确性已经过人工标注验收。

可选 Kokoro 中英量化模型：`python -m speech.prepare kokoro` 固定模型 revision 并校验模型、音色和词典 SHA-256；设置 `DAFEIYU_TTS_BACKEND=kokoro` 后重启语音服务。默认中文音色 ID 45（`zf_xiaobei`），可用数字 `voice` 选择其他音色。原始 Kokoro v1.0 权重和转换仓库均标注 Apache-2.0；词典等资源的个别许可应随部署核查。该适配器不暴露音素序列或音素时间戳；PCM 响应头明确标记不可用。CPU 性能因设备和文本而异。

可选在线识别模型以固定版本准备：`python -m speech.prepare streaming-asr`。该命令检查四个模型文件的 SHA-256；模型卡标示 Apache-2.0。设置 `DAFEIYU_STREAM_ASR=1` 可启用本地预览接口；`/health` 的 `streaming_asr` 分别报告开关、文件和实际加载状态，模型首次连接时加载到 CPU。最终转写仍使用既有离线识别；在线部分结果及时间戳可能有误。

可选 ZipVoice 使用本地参考声音及对应文本。运行 `python -m speech.prepare zipvoice` 获取官方 sherpa-onnx 中文模型、声码器和词典并校验固定 SHA-256。现有模型目录不完整或校验失败时命令会停止，不覆盖已有文件。模型卡未明确声明权重许可证，使用或再分发前需确认模型、声码器和训练数据许可。设置环境变量后重启服务：

```powershell
$env:DAFEIYU_TTS_BACKEND = 'zipvoice'
$env:DAFEIYU_ZIPVOICE_MODEL = 'D:\project\dafeiyu\models\zipvoice-zh-en'
$env:DAFEIYU_ZIPVOICE_REFERENCE = 'D:\path\to\reference.wav'
$env:DAFEIYU_ZIPVOICE_REFERENCE_TEXT = '参考录音中实际说出的文字'
```

参考音频须为最多 30 秒的单声道 PCM16 WAV。仅使用有权使用的参考声音。`/health` 显示实际加载结果；缺模型或参考音频时不会冒称 ZipVoice 已就绪。`/v1/audio/speech` 和 `/v1/audio/speech/stream` 接受 `speed`（0.5 至 2.0）。本机验证是 CPU 离线生成，短句回调可能直到整句完成才出现；这不是连续流式文本输入，也不保证推理立即取消。

可选说话人相似度模型需显式准备：`python -m speech.prepare speaker`。这是本地模型，模型来源及 Apache-2.0 许可文件保存在 `models/speaker-eres2net/`；在设置中开启本人模式前不会拦截对话。注册至少两段独立 16 kHz 单声道 PCM16 WAV，Silero 检测的有效人声每段至少两秒，短附和可能被拒绝。只保存平均嵌入到 `data/speaker-owner.json`，不保存录音。可以删除模板。默认阈值 0.65 尚未在本人及实际环境中标定，仅作为可调整的实验起点；声纹相似度不是身份认证，也不是降噪或回声消除。命令 `python -m speech.speaker_cli first.wav second.wav` 可离线比较两段录音而不注册。

- `GET /v1/speaker/status`：模型状态与是否已注册。
- `POST /v1/speaker/enroll`：multipart `files`，2–5 段录音；样本不一致或质量不合格时不覆盖已有模板。
- `POST /v1/speaker/verify`：multipart `file`，返回相似度和通过/不确定状态。
- `DELETE /v1/speaker/enrollment`：删除本地模板。
- `POST /v1/audio/transcriptions` 可选 multipart `owner_only=true`，不匹配或有效人声不足时不转写；未配置模型或模板时返回错误。

- `GET /health`：实际加载状态、计算设备、原因和 OpenVINO 可见设备列表。
- `POST /v1/audio/transcriptions`：multipart `file`，16 kHz、单声道、16 位 PCM WAV，最长 30 秒，返回 `{ "text": "..." }`。
- `POST /v1/audio/speech`：JSON `{"input":"你好","voice":"","response_format":"wav"}`，返回 WAV。Windows SAPI 的 `voice` 可填写 `/health` 列出的名称；sherpa 模型使用数字 speaker ID，默认 0。

识别与合成分别串行，适配单用户会话；中断时播放器和上游需丢弃已取消的响应，本服务中已开始的 CPU 推理不能强制中止。所有推理在本地执行；上游对话模型是否发送转写文本到云端由对话服务设置决定。

### ??????

?? `DAFEIYU_HOME` ????????? `models/`?????? NPU ?????? `data/`?MFA ?????? `cache/mfa/`?`DAFEIYU_MODELS_DIR`?`DAFEIYU_DATA_DIR`?`DAFEIYU_CACHE_DIR` ????????????????????? home ???????????? `python -m speech.prepare`?`speech.prepare_diarization` ? `speech.prepare_mfa` ?????????????????????????????????????????????????????????????????
