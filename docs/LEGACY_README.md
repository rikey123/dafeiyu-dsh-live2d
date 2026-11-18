> 历史源码部署与本机验收资料。不是独立发行版的安装入口，也不表示新安装已准备好模型、密钥或记忆。当前发行说明见 [DSH_RELEASE.md](DSH_RELEASE.md)。

# DeepSeek-chan（大肥鱼） · 数字人语音伙伴

## DSH 插件独立发行

当前提供原生 `dsh.bundle` npm 包的构建与独立安装流程：`npm run release -- --out <发行目录>`，产出包含预编译原前端和语音后端的 `.tgz`、哈希及审计报告。运行代码与外部 `DAFEIYU_HOME` 分离，不依赖本机项目盘符或预先建好的 Python 环境；模型、私有配置及受限角色素材不进发行包。完整说明见 [DSH 独立发行](DSH_RELEASE.md)。下文旧独立版和本机验收记录保留供历史/源码部署参考，不是新安装已配置密钥或模型的承诺。

完整语音补齐进度见 [逐项实施与验收表](VOICE_COMPLETION.md)：保留46个上游的99项能力和59条补充发现，并关联到23项实施任务。[能力明细CSV](VOICE_COMPLETION.csv) 与 [任务验收CSV](VOICE_TASKS.csv) 可导入Excel。表中“待实测”“条件受限”和“进行中”均有尚需完成的具体条件。

基于 Pipecat 语音内核、官方浏览器音频客户端、本地开源推理和 Live2D 的中文数字人应用。默认使用 DeepSeek 兼容 API 对话、本地语音识别和合成，另有本地大模型备用。DeepSeek-chan 是用户提供的角色形象，不代表官方员工。研究文档的候选技术和性能目标不作为已经实现或达到的事实。

语音合成可选择 GPT-SoVITS v5 turbo / IndexTTS-2.5 GPU、MOSS-TTS-Nano 100M ONNX CPU、自动或独立 API 模式。交互方式可选择轮流说话、支持打断的 DeepSeek 流水线，或云端 MOSS-Live 语音模型：前台语音由 MOSS 处理，复杂任务委托给已配置的 DeepSeek。MOSS 与 TTS API 使用各自独立的密钥，自动模式不会调用收费接口。模型、运行时和大文件缓存放在 E 盘，保存模式后启动器同步受管理的 TTS 服务。配置与实测边界见 [TTS 模式说明](TTS_MODES.md)。历史 CosyVoice 实测记录保留供迁移参考，不代表当前 IndexTTS 路由的验证结果。

## 现在使用

本机依赖和语音模型已经准备好。当前主配置为 **DeepSeek API / deepseek-chat + 本地语音**，本机密钥已在应用设置中配置并通过一次真实回复/合成/口型检查；新安装时需自行填写。本地 Qwen3 1.7B INT4 作为离线备用已经准备好。

1. 双击 `start.cmd`，或在项目目录运行 `powershell -ExecutionPolicy Bypass -File .\start.ps1`。
2. 打开 <http://127.0.0.1:8765>，可先输入文字，确认角色真实回答并发声。新安装时在左侧“设置”填写 DeepSeek API 密钥并保存。
3. 点击“开启语音”，允许浏览器使用麦克风。说完稍作停顿，角色会接话；它说话时可插话，也可按“停止”。
4. 左侧“设置”可以修改大模型、角色设定、声线、麦克风、Live2D 地址和手动记忆。左下角进入全屏角色舞台，Esc 退出。
5. 关闭启动控制台时按 Ctrl+C。后台运行时，执行 `.\stop.ps1` 停止项目管理器及其自己启动的服务。

服务刚启动时，模型需要加载和预热；请在设置中确认“对话模型”和“本地语音”已就绪。2026-11-06 本机真实 DeepSeek 文本回复、本地 CPU 合成和实际 Live2D 嘴形已单轮通过，不代表真人语音/外放环境已经验收。应用默认只监听本机回环地址。访问权限来自浏览器，第一次使用麦克风时需要用户允许。

麦克风启动失败时，页面保留浏览器错误代码：`NotFoundError` 表示没有可用输入，先在 Windows“设置 → 系统 → 声音 → 输入”确认已接入并启用麦克风；“立体声混音”不是实体麦克风。`NotAllowedError` 检查网站及 Windows 麦克风权限，`NotReadableError` 检查设备占用，`OverconstrainedError` 重新选择输入设备。设置中的“刷新麦克风列表”无需开启录音，插拔设备也会自动更新；默认设备与手动指定设备分别处理，失败不会擅自换用其他麦克风。接好设备后刷新页面、选择输入并重新点击“开启语音”。

麦克风回归检查：启动项目后运行 `node scripts/check_microphone.cjs`（需已有 `qa/node_modules/playwright` 和本机 Edge）。脚本分别记录真实设备打开结果，并使用合成静音流验证错误分类、设备切换、关闭释放、worklet 失败清理与重试；合成流通过不代表实体麦克风采音或声学回声消除已通过。可通过 `MIC_CHECK_OUTPUT` 指定 JSON 证据文件。

## 已实现

- Live2D DeepSeek-chan 角色，复用 AIRI 的色彩渲染补丁和 MAGIC 待机/说话动作生成器；嘴部跟随 Web Audio 实际播放波形，分句情绪映射到角色表情，设置中可关闭“自然动作”或调节“动作幅度”（默认 0.6）。
- Pipecat Silero VAD、Local Smart Turn v3.2、官方录放音 AudioWorklet；浏览器请求回声消除/降噪/自动增益，初步降音量、最终转写确认插话。
- 中文 SenseVoice INT8、sherpa-onnx VITS 离线合成；OpenVINO Whisper NPU 自检、CPU 后备和 Windows SAPI 后备。
- 框架原生 DeepSeek/OpenAI 兼容服务、增量文字、TTS 聚合、PCM 队列和取消；有限中文附和映射到原生 backchannel frame。
- SQLite历史、每个原生TTS音频段实际消费完成后确认并保留连续前缀、手动记忆、配置和密钥脱敏。中断保留已确认段；尚无逐字已听位置。手动停止后可点“继续刚才的回答”发起新一轮接续，不恢复被取消任务或原音缓存。
- 桌面/窄屏布局、全屏舞台、本地资源离线加载、真实服务诊断、一键启停。

46 个完整源码归档和语音内核复用边界见 [docs/VOICE_OPEN_SOURCE.md](VOICE_OPEN_SOURCE.md)，固定版本清单见 [docs/UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)。完整 WebSocket/HTTP 契约见 [docs/PROTOCOL.md](PROTOCOL.md)，实施选型见 [docs/ARCHITECTURE.md](ARCHITECTURE.md)，实际开源复用范围见 [docs/AVATAR_OPEN_SOURCE.md](AVATAR_OPEN_SOURCE.md)，验收边界和测量结果见 [docs/VALIDATION.md](VALIDATION.md)，逐项目语言系统复审见 [docs/OPEN_SOURCE_LANGUAGE_REVIEW.md](OPEN_SOURCE_LANGUAGE_REVIEW.md)。

全部差距的实施表单见 [docs/VOICE_COMPLETION.md](VOICE_COMPLETION.md)，也提供 [CSV 表格](VOICE_COMPLETION.csv) 和 [结构化状态](VOICE_COMPLETION.json)。逐条保留46个上游的99项能力和59条补充发现，并关联实现、验收证据和剩余条件。原始差距审计保留于 [docs/CURRENT_VOICE_GAPS.md](CURRENT_VOICE_GAPS.md)，其wLipSync问题已在本轮按源码修复并重新校准，E/O/U分类准确性仍需改进。

新增“设置 → 本人声音”：本机 ERes2Net 声纹模型已准备好，主动录制至少两段、每段建议3–10秒，提交后开启“仅回应本人声音”。重新手动开启聊天语音后，先核对声纹再进行识别和对话；不匹配或不确定不会启动回答。短句需要至少2秒有效人声，太短时会提示重新说完整句子。录音结束或关面板释放麦克风，删除后关闭筛选，只保存声音特征。真人准确率、多人重叠和录音重放尚未验证。音频工程来源、使用方法和真实测试边界见 [docs/AUDIO_ENGINEERING.md](AUDIO_ENGINEERING.md)。

口型使用 wLipSync WASM/MFCC 和 AIRI 元音驱动，分析实际播放增益后的 PCM，映射张嘴、嘴形和收唇。默认使用通用模板（尚未按当前声线校准）；旧 VITS 专属模板只保留手动选择，不能当作 GPT-SoVITS/MOSS 的校准模板。播放不等口型初始化，实际消费样本驱动活动门，静音、停止与重连清零，并过滤迟到帧；移除角色层重复平滑，缓存编译后的 WASM。分类不可用时明确显示音量口型回退。它是近似元音动画，不是逐字音素对齐，中文 E/O/U 等混淆和真人声画效果仍需验收。表情仍按 TTS 段首次实际消费触发。详见 [实时口型](REALTIME_LIPSYNC.md)。

MFA 离线强制对齐已从应用设置、启动器和播放链移除，不再为口型等待整句合成与离线对齐。旧配置会自动迁移，E 盘已有历史环境/模型未擅自删除；离线研究仅归档参考，不是实时功能。当前语音模式与模型以 [TTS_MODES.md](TTS_MODES.md) 为准。

## 本机推理选择

设置中的“智能交互判断 · System One”可选火山方舟豆包 `doubao-seed-2-1-lite-260915`（北京，Beta，支持配置 `ep-...` 接入点）或 TokenToSea `clef-omni`，判断插话/附和、情绪、表情和手势；回答仍由 DeepSeek 等原对话模型生成，GPU、CPU 或 API TTS 不变。默认关闭，两家密钥独立；音频判断向选定供应商发送最长 4 秒声音及有限对话，可改为仅文本，不采集图片/视频。超时回退到规则，绝不自动切换收费供应商；播放片段绑定、手动优先，不与 MOSS-Live 同时启用。概率尚未校准，提供显式付费评估脚本。配置步骤与真实验收边界见 [SYSTEMONE.md](SYSTEMONE.md)。

设备为 Core Ultra 5 225H、32GB 内存、Arc 130T iGPU、Intel AI Boost NPU。语音目前使用经过验证的 CPU 路径。Whisper INT8 和 FP16 虽然都能在该 NPU 编译，但中文自检产生异常重复字符，因此自动拒绝该结果并回退；状态接口会显示原因。

本机 `.env` 可选择 `DAFEIYU_LLM_DEVICE=CPU` 或 `GPU`，修改后重启。大模型和语音是独立服务，语音使用 CPU 不代表大模型也必须使用 CPU。NPU 的存在、编译成功、识别正确和达到延迟目标需要分别验证。

```dotenv
DAFEIYU_LLM_DEVICE=GPU
# 强制稳定 CPU 语音，跳过 NPU 探测：
# DAFEIYU_ASR_DEVICE=CPU
# 驱动/模型更新后重新测试 NPU：
# DAFEIYU_VOICE_MODE=manual
# DAFEIYU_ASR_DEVICE=NPU
# DAFEIYU_ASR_RETRY=1
```

语音模型配置与设备探测详见 [speech/README.md](speech/README.md)。默认最终识别使用完整片段SenseVoice，普通识别接口也有独立人声检测，静音/噪声不直接喂给识别模型。设置中可打开实验性的“更快响应插话”：在线Zipformer稳定部分文字用于提前打断，最终文字仍单独提交一次；开启本人筛选时保留严格声纹门，停用早打断。本机模型完整时启动器启用在线服务能力，功能仍默认关闭；新环境先运行 `python -m speech.prepare streaming-asr`。极短语音和中文数字仍需真人实测。

默认VITS按句生成，通过sherpa原生callback提前传PCM，由Pipecat播放；可选ZipVoice已完成本地参考音色与语速接口的CPU生成测试，但短句只在完成时回调一次，权重许可尚未明确，暂不替换默认声线。这些能力不等同于持续文本输入的双向流式TTS。

## 切换云端大模型

在设置里填写兼容服务的 API 地址（通常包含 `/v1`）、模型名称和密钥，保存后即可使用。密钥只保存在忽略的本地数据目录，不回传给界面。留空保持原有密钥。原始语音继续由本地服务处理；转写文字和会话上下文会发送给所选云端 LLM。

当前云端配置为 `https://api.deepseek.com/v1` / `deepseek-chat`。本地模型备用地址为 `http://127.0.0.1:8767/v1`，模型名 `qwen3-1.7b-int4`；也能接 Ollama 的 `http://127.0.0.1:11434/v1` 或其他兼容服务。启动器在主配置选择云端时不自动加载本地大模型。切换离线模型时先使用 `start.ps1 -LocalLlm` 启动备用服务，并在设置中改为本地地址和模型名。

## 从干净环境安装

需要 Windows、Node.js 24 或 Node.js >=22.12、Git、uv。Python 环境由 uv 创建为 3.12。

```powershell
.\setup.ps1 -LocalLlm
.\start.ps1
```

安装分别使用 `requirements-lock.txt` 约束本地推理环境、`requirements-voice-lock.txt` 安装独立 `.venv-voice` 网关；`npm ci --include=dev` 使用前端 lockfile，并自动应用固定版本的 AIRI 渲染及官方录音器补丁。将自行获得的 `DeepSeek免费公皮.zip` 放到项目根目录，安装脚本会安全导入角色并下载 Live2D Cubism Core；角色资源和 SDK 不提交 Git。如果角色已导入，可以不保留压缩包。缺少压缩包和已导入角色时安装会提示具体路径。语音模型与可选 Qwen 模型需单独下载；只接外部大模型时可省略 `-LocalLlm`。模型已下载时可使用 `-SkipModelDownload`。离线运行前必须完成所有模型和前端资源准备。

## 验证和开发

```powershell
.venv\Scripts\python.exe scripts/doctor.py
uv pip install --python .venv-voice/Scripts/python.exe pytest
uv pip install --python .venv/Scripts/python.exe pytest
.venv-voice\Scripts\python.exe -m pytest -q tests speech/test_pipecat_services.py
.venv\Scripts\python.exe -m pytest -q speech/test_speech.py speech/test_speaker.py inference/test_llm.py
$env:DAFEIYU_RUN_LLM_TEST='1'
.venv\Scripts\python.exe -m pytest -q inference/test_llm.py
npm --prefix web test
npm --prefix web run build
```

运行新内核真实浏览器验收：先启动本地 8766 语音服务，然后另开终端运行隔离网关。它使用临时数据库和受控 SSE 模型，不修改主设置、不需要云端密钥。

```powershell
.venv-voice\Scripts\python.exe scripts/serve_voice_acceptance.py
# 另一个终端：
npm --prefix qa install --no-audit
npm --prefix qa run voice
npm --prefix qa run primary
npm --prefix qa run idle
.venv-voice\Scripts\python.exe scripts/stress_pipecat_protocol.py --turns 10
.venv-voice\Scripts\python.exe -m speech.benchmark_vad
node scripts/check_audio_engineering.cjs
# 本人声纹使用另外的隔离服务/模板，运行结束自动清理：
.venv-voice\Scripts\python.exe scripts/check_owner_voice.py
```

浏览器验收使用真实官方客户端、Pipecat、Silero/Smart Turn 和本地 ASR/TTS，麦克风为合成音频虚拟流，不代表物理 AEC 或真人误打断率。结果位于 `artifacts/pipecat-acceptance/`。脚本支持 `PLAYWRIGHT_MODULE` 指向已有 Playwright。旧 JSON/WAV 管线的验收脚本已归档，只能作为历史资料，不能用于新框架宣称性能。纯待机验收仍用真实 Live2D 连续动画。

## 目录与进度管理

`web/` 是前端，`server/` 是对话服务，`speech/` 是本地语音，`inference/` 是可选本地 LLM，`scripts/` 是启停和验收。数据在 `data/`，模型在 `models/`，两者均被 Git 忽略。

开发使用三个独立 worktree：`feat/frontend`、`feat/backend`、`feat/speech`，分别由三个 agent 并行实现后合入 `main`。进度和提交记录见 [docs/PROGRESS.md](PROGRESS.md)。

## 素材与范围

默认角色来自用户自行提供的 DeepSeek-chan 皮肤。模型原画及拆分为神宫凉子，Live2D 建模为霓虹猫_NeonNeko；使用范围和署名要求见 [docs/DEEPSEEK_SKIN.md](DEEPSEEK_SKIN.md) 及导入后的原始使用须知。角色不可擅自重新分发。Cubism Core 和开源应用代码的许可相互独立，见 [web/LIVE2D-LICENSE.md](web/LIVE2D-LICENSE.md)。替换模型时把 `.model3.json` 及配套目录放入 `web/public/models/`，重新 build 后在设置中填写同源地址。

当前版本适合本机单用户数字人对话。真实外放 AEC、自然附和与误打断率、方言和嘈杂环境、30 分钟真人连续交互仍需要实机验收。没有集成摄像头、桌面操作、自动语义记忆、AIRI 完整应用、Live2D MotionSync、开机自启动或安装包。默认 1.7B 模型和 VITS 声线提供本地可用基线；更强的云端模型与更自然的 TTS 可以通过现有服务边界替换。
