# 音频工程移植与本人声音筛选

最新逐项进度见 [VOICE_COMPLETION.md](VOICE_COMPLETION.md)；这里保留工程来源与复现入口。当前口型使用修复过十二系数写入范围的上游WASM，生产改为同源资源加载，早期单文件入口的描述属于历史实现。

## 新增的可重复验收

`scripts/benchmark_voice_corpus.py` 用有标签的本地WAV分别测最终CER、普通HTTP识别耗时、节奏输入的在线首部分结果和端点。`scripts/benchmark_owner_corpus.py` 用独立的录入与测试WAV计算身份错误率，不修改本人模板；过短本人计入有效拒绝，噪声/静音不混进旁人语音FAR的分母。当前合成样本仅作回归，真人数据仍需用户录入。

`scripts/capture_aec_device.py` 是独立于浏览器生产链的LiveKit APM物理诊断入口，复用sounddevice单双工流的render/capture时钟机制。帮助及`--list-devices`不采集声音；显式`--capture --reference ...`才运行36秒只听/只说/双讲流程，原始/处理后/播放参考WAV与ADC/DAC时间保留在忽略的artifacts目录。单讲总能量衰减不命名为ERLE，双讲保真和误打断需要真人判断。当前没有执行物理录音，也没有把未经验证的原生APM叠加到浏览器AEC。

```powershell
.venv-audio-experiments\Scripts\python.exe scripts/capture_aec_device.py --list-devices
.venv\Scripts\python.exe scripts/benchmark_owner_corpus.py artifacts/owner-corpus/manifest.json
```

可选ZipVoice/Kokoro真实CPU合成及说话人分段失败实验见 [VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)。短句完成回调、离线说话人标签、字级对齐与连续文本输入分别评估，不互相替代。

2026-11-06。本轮在已经取得的 46 个完整上游源码归档上继续逐模块核查，重点解决实际播放口型、麦克风处理状态和本人声音筛选。源码固定提交见 UPSTREAM_SOURCES.json；下面区分直接调用库、借鉴机制与独立实验。

## 已进入生产的优化

| 功能 | 上游依据 | 本项目实现 |
| --- | --- | --- |
| 播放、采集、PCM、取消 | Pipecat 1.15.0、官方 JS client 1.16.0 / websocket transport 1.8.2 | 继续直接依赖框架和官方 worklet，不增加第二套音频队列 |
| 口型响应 | AIRI `11b8989f6dd7f840cf6b15ce59e367656fb11ac6` 的 `packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts` 和 `src/live2d/index.ts` | 已直接接入固定 `wlipsync@1.3.1` WASM/AudioWorklet：从实际播放器增益后的音频计算 AEIOU 权重、静音门、winner/runner 和时间平滑，再映射到本模型实际存在的 `ParamMouthOpenY`、`ParamMouthForm`、`Mouthpucker`、`MouthFunnel`、`MouthPuckerWiden`。独立 analyser 仍读取 1024 个样本（24kHz 约42.67ms）作诊断/回退；不再把音量作为默认口型算法。静音、降音量和停播均影响实际嘴部 |
| 浏览器音频处理状态 | 官方 WavRecorder、浏览器 MediaTrackSettings | 请求 AEC/NS/AGC，设置中展示浏览器实际报告和“不支持/未报告”，不把请求成功当成声学效果 |
| 声纹推理 | sherpa-onnx 2.0.1 的 SpeakerEmbeddingExtractor；官方 speaker-identification 示例 | 直接调用 CPU ONNX 声纹提取器和 Silero VAD，不自写识别网络 |
| 模板可靠性 | EvatarFramework `63b414c9633d55234949b3754686dcc7acebea60` 的 `providers/speaker/store.py` | 参考归一化、多样本平均、有限值/维度校验和原子写入；自研少量单用户模板适配与 HTTP 门禁，未复制其完整角色应用 |
| 录入体验 | 现有官方录音器 | 显式录音，最长10秒，结束或关面板释放音轨；修复上游固定 RIFF 长度及 MIME，实际 Edge 录音双声道转单声道。录入前停止聊天采集和回答播放，避免角色声音混入模板 |

当前默认是 wLipSync 的声学 AEIOU 元音分类与平滑，不是文本猜测或单一 RMS 开合。它仍不是 ASR 字级音素对齐：wLipSync 返回的是实时音频特征，不能声称每个汉字的精确发音。AIRI 本轮参考提交与已 vendored 的 MAGIC/色彩补丁提交 `759fff0e...` 是两项不同来源，不混记版本。Open-LLM-VTuber WebSDK 的 RMS 口型也已对照；其定制许可前端没有复制进入项目。wLipSync 初始化失败时才回退到短窗口音量口型，并通过 `lipStatus()`保留失败原因。

默认模板已改为当前本地中文 VITS 声线的独立录音校准；设置可切换 AIRI 通用样例，切换会重连但不打开麦克风。离线工具 `scripts/calibrate_lipsync.cjs` 直接使用固定上游 WASM 的 MFCC 导出收集模板，未实现第二套DSP。五段等RMS约2800的真实播放器测试显示 A/I/U 嘴形可区分，U收唇出现，但E/O/U仍有混淆；不能把“频谱能改变嘴形”当作“全部发音准确”。训练/声线/WASM摘要见 [LIPSYNC_PROFILE_PROVENANCE.json](LIPSYNC_PROFILE_PROVENANCE.json)，复现方法见 [VALIDATION.md](VALIDATION.md)。

## 只回应本人的声音

打开设置中的“本人声音”，主动录制至少两段，建议每段3–10秒、说不同的完整句子。也能上传16kHz单声道PCM16 WAV。提交成功后，开启“仅回应本人声音”。录入、启停和删除不会自动打开聊天麦克风；开启后需手动点“开启语音”。删除模板会同时关闭筛选并重连当前会话。文字输入仍可使用。

每段至少需要2秒被 Silero 判为人声的音频，且人声占比至少25%。两至五段注册录音必须两两相似度达标才写入平均模板；注册失败保留旧模板。只保存模型标识、样本数和嵌入向量到忽略的 `data/speaker-owner.json`，不将注册 WAV 写入持久化目录。

```text
麦克风 → 浏览器 AEC/NS/AGC → Pipecat Silero 分段
  → 本地 Silero 质量检查 → ERes2Net 本人相似度
      通过 → SenseVoice ASR → 中文轮次策略 → LLM → TTS
      不匹配/不确定 → voice.speaker 提示，跳过 ASR/LLM/用户历史
      模型/模板/服务不可用 → 拒绝继续识别，提示错误
```

适配层只有在 `speaker.accepted` 严格为布尔 `true` 时才放行；字段缺失、`null`、数字1或服务错误均不放行。被拒绝的声音不发空转写，不启动新轮次或硬打断回答。VAD 检测期间仍可能暂时压低回答音量，结束后恢复。这避免声纹推理完成前就误取消机器人。

短“嗯/好的/你好”可能不到2秒有效人声，开启筛选时会提示无法判断；不会按“刚才是本人”就绕过门禁。多人同时说话、混响、电视中相似声线及录音重放尚未验证，当前不是多人分离或防伪认证系统。阈值0.65是开发默认值，尚未基于用户真人录音标定；声纹降低旁人语音触发的概率，背景杂声仍由降噪、人声检测及质量门槛处理。

短命令可用独立实验入口评测：`.venv\Scripts\python.exe -m speech.short_speaker_evaluation artifacts/owner-corpus/manifest.json --output artifacts/owner-corpus/short-window-results.json`。它复用同一 ERes2Net、Silero 和标注清单，对每条独立测试录音的0.5/1/1.5/2秒前缀分别报告实际时长、有效人声、分数、拒绝原因及 FAR/有效 FRR 的分母；不同窗口来自同一录音，不能当成独立样本。实验入口允许较短有效人声以观测模型表现，生产 HTTP 验证仍固定两秒，不调用该入口、不修改本人模板或自动调整阈值。本机小规模合成样本的0.5秒本人有效拒绝2/2，其余窗口1/2，旁人误接受均0/1；这组样本不足以证明真人准确率或支持放宽门槛。

## 模型与准备

本机模型已放在 `models/speaker-eres2net/`。新环境的准备命令：

```powershell
.venv\Scripts\python.exe -m speech.prepare speaker
# 重启本地语音服务后，到设置录入自己的声音。
```

下载固定于 `onemira/eres2net-base-3dspeaker-onnx` 提交 `94b441c56126883d212425ab108fa46f35775adf`。原始模型为 3D-Speaker 的 ERes2Net-Base 中文声纹模型，ONNX 来自 sherpa-onnx 的转换/发行。文件 `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` 为39,593,761字节，SHA256 `1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b`。镜像保留原始 Apache-2.0 许可、sherpa 许可、NOTICE 和 source-metadata.json；未修改权重。

`DAFEIYU_SPEAKER_MODEL`、`DAFEIYU_SPEAKER_VAD`、`DAFEIYU_SPEAKER_PROFILE` 可覆盖路径，默认均在本项目。服务启动不下载模型；打开状态或使用功能时按需加载。声纹明确使用 CPU；不是 NPU 推理。模型缺失会给出准备命令，不伪装就绪。

## 回声处理：已检查，尚未接入原生 AEC

HF speech-to-speech `5108a3eacea81298a9dc62d5179abcacfb8119f1` 的 Realtime 音频客户端已经有 Windows WASAPI/auto_convert 路径；不能笼统称为不支持 Windows。其 `echo_canceller.py` 使用 pywebrtc_audio AEC3、10ms帧、相同采样率和真实 ADC/DAC 时间对齐。EdgeVoiceAssistant `6ba8a2d7f715e967ecc2f75539f553fb37198ee6` 通过单个 sounddevice 双工流共享时钟，并调用 LiveKit AudioProcessingModule 的 reverse/forward stream。Fulloch 的双通道 native satellite 也假设已经取得正确的播放参考。

这些机制依赖声卡实际播放参考和时钟。当前服务端只知道 WebSocket 排出了什么，不能由此知道扬声器何时播放；把服务端 TTS WAV 硬塞入 AEC 会引入错位。生产继续使用浏览器的设备侧 AEC/NS/AGC，未串联第二个未经验证的消回声器。

`server/aec_experiment.py` 是单独的 LiveKit WebRTC APM 可行性实验，不被生产导入。Windows wheel 可以运行，实验用 Whisper JFK 与 faster-whisper physicsworks 的公开语音、固定40ms多径模拟回声，比较单讲残余能量以及双讲近端投影。单次12秒输入处理约0.089秒，双讲近端投影增益0.614、相关0.669，仍有明显衰减；单讲约56dB的能量比不能证明双讲保真或真实房间效果。因此没有将它接入成品或宣称外放免误打断。

本地 VITS 还新增了 `/v1/audio/speech/stream`：它消费 sherpa-onnx 的原生 callback 分块，在完整 WAV 生成前发送有界 PCM16 块；Pipecat 适配器只在服务返回404/501时回退旧 WAV。取消会停止入队，但原生线程仍持有锁直到实际退出；3槽位准入和HTTP连接复用避免无界排队。HTTP400/429/500/503、首PCM后取消/断连均有测试，避免重复播完整WAV。

短/长句各3次串行CPU HTTP对照：首PCM中位数0.124/0.125秒，完整WAV为0.305/1.322秒。流式后测WAV、模型输出含随机变化，不能当作统一性能排名、连续声学流式、扬声器延迟或NPU成果。原始快照见 [TTS_BENCHMARK_2026-11-06.json](TTS_BENCHMARK_2026-11-06.json)，复现脚本 `scripts/benchmark_speech_tts.py`。原生Pipecat metrics 已开启，可通过 `scripts/check_voice_metrics.py` 观察；原生TTFA也不包含浏览器/扬声器时钟。

复现实验使用隔离环境，生产无需安装：

```powershell
uv venv --python 3.12 .venv-audio-experiments
uv pip install --python .venv-audio-experiments/Scripts/python.exe -r requirements-audio-experiments.txt
.venv-audio-experiments\Scripts\python.exe server/aec_experiment.py far-16k-mono.wav near-16k-mono.wav
```

它不采集设备、不接生产播放；两条输入由运行者提供。真实设备 AEC 需要按听感、残余回声、本人语音保留和双讲误打断共同验收。

## 验证入口

```powershell
# 真实模型/ASR/框架 + 浏览器录入；使用独立临时模板和设置，结束清理子服务。
.venv-voice\Scripts\python.exe scripts/check_owner_voice.py
# 需先运行 scripts/serve_voice_acceptance.py：
node scripts/check_audio_engineering.cjs
```

声纹验收比较本地 VITS 同声线跨文本与 Windows SAPI 另一声线，覆盖注册、混合样本不覆盖旧模板、静音/噪声/过短拒绝、缺模板拒绝、旁人声音不硬打断、不启动 LLM、不写用户历史、后续本人发言恢复、开关与删除。浏览器用文件虚拟麦克风实际录制两段并提交模型，检查录音结束/关闭面板释放音轨、开关重连不自动开麦。结果在 `artifacts/audio-engineering/`。合成声线和虚拟设备用于链路回归，不能外推真人识别准确率、真实背景噪声鲁棒性或防重放能力。
