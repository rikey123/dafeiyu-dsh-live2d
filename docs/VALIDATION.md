# 验收记录（2026-11-06）

## 当前逐项补齐验收

全部能力及剩余条件以 [VOICE_COMPLETION.md](VOICE_COMPLETION.md) 为准。固定审计保留99项能力和59项补充发现，不能由一个总通过标记代替每项验收。新证据集中在 [VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)。下面的早期数字保留为历史样本，不与最新样本合并成分布。

- 当前已跑的单元回归：前端44项；`.venv-voice -m pytest -q tests speech/test_pipecat_services.py` 共66项；独立`.venv`运行speech并排除该Pipecat文件共33项。两组Python文件不重叠，新增MFA和Cosy准备校验均已包含，不再次相加。干净npm安装、补丁、TypeScript与生产构建通过，保留大bundle和框架弃用提示。
- 实际Edge播放器的原生多context协议下，短回复2段40320/25920样本，长回复6段74880/50880/57600/60480/69120/46080样本，每段consume严格等于服务端边界且各一次ACK。完成至最终ACK含历史读取分别3908/15714ms，不是首音延迟。另验证确认前2段后停止，仅持久化一次连续前缀，下一轮恢复。显式结束HTTP对应context消除了每段默认3秒idle等待。
- 最新真实CPU语音、官方Edge工作线程和虚拟麦克风8项回归通过：权限失败重试、PCM实际嘴形、附和保留、明确插话、停止、释放麦克风及安全重连。约1.967秒的合成插话从虚拟输入起点至interruption约1.523秒；单样本、非物理声音停止时间。修正测试将下一句合法打断误归入附和窗口的问题，按下一句转写边界分隔。
- 默认生产口型的CSP回退问题已修复：同源WASM、worklet和413B二进制profile；默认初始化、两种模板切换、故障可见回退均通过。等RMS五元音经实际播放驱动不同模型嘴参数，停止归零；这是声学嘴形依赖证据，不是中文音素准确率。
- 独立CPU身份/录入回归通过，同合成声线新文本相似度0.9161、另一SAPI声线0.1203；被拒声音不触发LLM或硬打断，后续通过声线可继续。真人阈值仍未标定。
- `scripts/benchmark_owner_corpus.py` 不修改生产模板，严格隔离录入/测试文件，分别报告旁人语音FAR、本人有效FRR、可打分FRR和非人声误接收。合成回归中两条本人有一条短命令不确定，不能只报可打分样本的零拒绝率。
- 修复CSP后的整context基线已完整运行1802.07秒，225轮（193完成/32取消）。最新分段版另完整运行1807.417秒、206轮（177完成/29取消），含每9轮一条六段长回复及定期重载；无溢出、活动AudioContext始终1、未申请麦克风、无页面错误。短回复点击至ACK并读取历史P50/P95为3536/3998ms，n=158；长回复16040/16823ms，n=19。它是消费完整回复的时长，不是首音延迟。固定快照见 [VOICE_SOAK_2026-11-06.json](VOICE_SOAK_2026-11-06.json)。更早两次因CSP或context延迟终止的运行单独保留，不算通过。
- Qwen3中文强制对齐实际获得字/词区间，不能称phoneme；MFA 3.3.9真实取得IPA音素区间，但1.654秒WAV三次缓存运行仍需32.286/32.231/32.084秒，只能离线预对齐。中文人工精度与实际模型时间轴仍单列验收。
- CosyVoice2固定模型和源码的真实generator输入已输出3块4.28秒音频；CPU加载52.005秒、首块12.450秒、总RTF6.192。它不适合当前低延迟CPU默认链，生成器中途取消的线程回收尚无安全证据，未接常驻桥。
- 同文件哈希、同12语料各3次的修复前后对照均为36请求、318有声参考字符；静音/噪声假转写6/6降为0/6，有声CER均14.15%。详见 [VOICE_CORPUS_MATCHED_2026-11-06.json](VOICE_CORPUS_MATCHED_2026-11-06.json)；不把质量门修复当ASR模型准确率提升。
- 表情真实Edge复测：原生start.text分别含开心/难过，首个worklet消费后约230/226ms，实际DeepSeek脸红key7/流泪key2超过0.1，无页面错误。角色映射与关键词使用源码JSON，段尾重复文本不重复触发；这是段级播放同步，非真人观感或词/音素情绪准确率。用`.venv-voice python scripts/serve_voice_acceptance.py --expressions --port 8915 --provider-port 8914`及`VOICE_TEST_URL=http://127.0.0.1:8915 node web/qa/emotion-browser.cjs`复现。早期夹具错误返回无情绪的默认六句，已修复并防止误判为产品故障。

物理AEC、真人双讲、本人FAR/FRR、细粒度音素准确率和NPU中文质量仍有独立验收条件。下列是此前各阶段的原始记录。

## 早期音频工程与本人声音筛选

本轮实现、固定来源与复现步骤见 [AUDIO_ENGINEERING.md](AUDIO_ENGINEERING.md)，46个项目的逐项机制对照见 [OPEN_SOURCE_LANGUAGE_REVIEW.md](OPEN_SOURCE_LANGUAGE_REVIEW.md)。三个 feature worktree 的新提交经审查后逐项 cherry-pick 到 main，集成补齐开关与服务能力状态混用、Pipecat 未转交过滤参数、官方录音器 WAV 长度/MIME/双声道格式等实际缺口。声纹模型为本地 CPU ERes2Net，不作为 NPU 成果。

`scripts/check_owner_voice.py` 启动临时模板、临时数据库与独立8884/8885/8886服务，调用真实 ERes2Net/Silero/SenseVoice/VITS，再用另一条 Windows SAPI 声线做对照。两段 VITS 录入、同声线不同文本核对得0.9273并完成ASR；另一声线0.1178被拒绝。静音、固定种子低幅白噪声、0.99秒有效语音均返回不确定且空转写；没有模板返回503。混合两种声线录入失败且旧模板保持不变。仅本次合成样本成立，不是对用户真人的准确率标定。

同一官方protobuf连接中，机器人实际输出PCM时输入另一声线，没有新的LLM调用、没有bot-interrupted或用户转写；VAD降音量恢复，之后本人模板声线的有效发言触发正常下一轮。用户历史恰为两条（初始键入与通过门禁的语音），没有被拒绝的声音。删除后模板文件消失、设置关闭，筛选请求因缺模板拒绝，普通不筛选ASR恢复。浏览器另通过实际官方录音器录制两段，经单声道WAV转换和本地模型成功注册；开关重连不自动开麦，结束录音和关面板均释放全部音轨，删除后关闭开关，无pageerror。原始结果在 `artifacts/audio-engineering/owner.json`、`owner-ui.json`。

`scripts/check_audio_engineering.cjs` 使用实际PCM播放器、增益节点、wLipSync AudioWorklet 和 Cubism嘴部参数，确认实际加载 `wlipsync-single`，静音后嘴部归零、恢复音量重新开口、停止闭嘴。独立诊断 analyser 的窗口1024/24000≈42.67ms；wLipSync 自身使用profile定义的16k/1024分析窗口。最终本地声线复测视觉收敛约267ms/恢复首次开口126ms/停播收敛310ms，包含动作分派、音量包络及渲染，不是扬声器声学延迟或逐字音素准确度。输出 `artifacts/audio-engineering/mouth.json`。

最终回归：前端32项测试、TypeScript/Vite生产构建通过（另含21.46kB wLipSync WASM chunk）；`.venv-voice -m pytest -q tests speech/test_pipecat_services.py` 为29 passed；`.venv -m pytest -q speech/test_speech.py speech/test_speaker.py speech/test_stream.py` 为10 passed。这两组未包含可选真实LLM测试，不混记跳过数。本机真实Silero的静音/噪声拒绝用例已运行。保留上游弃用和bundle体积提示。

新构建完整浏览器复测通过普通自动播放握手、权限拒绝后恢复、短“好的”原生附和（本轮关闭声纹筛选）、实际语音硬打断和下一轮、手动停止、停麦释放、断线安全重连。最终输入1.914秒，到interruption事件估计2.811秒，非物理声学指标；未达到“刚开口即语义停播”。桌面与窄屏已有此前布局验收。主入口8765运行新版：声纹ready=true/enrolled=false/筛选关闭，等待用户主动录入；ASR/TTS为CPU ready。

本轮后段检测到主入口已配置DeepSeek密钥。`scripts/check_deepseek_live.cjs` 使用单独QA会话向真实 `deepseek-chat` 发起一次简短问候请求，收到“嗨，大肥鱼来啦，今天过得咋样？”，本地CPU合成、官方播放器、实际Cubism口型和持久化均通过，无pageerror、无麦克风申请；测试后删除该QA会话。点击至首次嘴形活动约2.514秒，包含网络、云模型、本地TTS和渲染，不是物理扬声器首音，也不是P50/P95。截图/结果在 `artifacts/deepseek-live/`。此处更新早期“未配置密钥”的历史记录，早期受控模型测量仍不作为云端性能数据。

## 本轮口型、增量PCM与46项目复审

完整审查有46项、107处经本地文件存在和行号范围核查的固定提交引用。可运行 `python scripts/build_language_review.py` 重新验证并生成报告，源码归档需已取得。Markdown和JSON都受Git管理。

`scripts/serve_lipsync_acceptance.py` 向实际本地VITS生成阿/衣/乌/鹅/哦各六重复字的独立验证录音，裁切并等RMS约2800后经隔离Pipecat、官方24k播放器、实际wLipSync和DeepSeek模型。`scripts/check_vowel_shapes.cjs` 按官方播放offset取样，验证等响度时真实嘴形不同、I比A更展唇、U确实收唇、打断全参数归中。最终 form范围约0.441、pucker范围约0.195。A帧50/50为A，I为47I/2E，U为23U/10O/10A/6E；E以A为主，O以U为主，明确存在混淆。固定结果快照见 [LIPSYNC_ACCEPTANCE_2026-11-06.json](LIPSYNC_ACCEPTANCE_2026-11-06.json)，原始音频和逐帧数据在 `artifacts/vowel-acceptance/`，不能用这些帧计数外推通用中文音素准确率。

训练是另一次十二重复字的AEIOUS合成录音，直接复用上游原版WASM的MFCC导出生成模板，未重写DSP；声线、训练音频摘要、WASM摘要与限制见 `LIPSYNC_PROFILE_PROVENANCE.json`。通用样例和本地模板切换会重连，均不自动开麦。WASM失败时界面明确显示音量回退，不将其描述为元音分类。

可用 `.venv-voice/Scripts/python scripts/prepare_lipsync_calibration.py` 生成新的合成校准WAV和manifest，再执行 `node scripts/calibrate_lipsync.cjs artifacts/lip-calibration/manifest.json artifacts/lip-calibration/profile.json`。新模板需在独立音频上验证后再替换 `web/src/avatar/lipsync/local-vits-profile.json`；生成器不会采集真人声音。当前模板的来源和独立有效帧数已固定记录。

`scripts/evaluate_lipsync_profiles.cjs` 还比较了上游自带的三种距离/相似度与标准化开关，直接使用同一原版WASM。单个合成序列离线帧匹配比例约0.55–0.62，均未解决E/O混淆，因此没有依据这个小样本改成“更准确”的默认算法。该序列已用于配置比较，后续质量评估必须另取独立样本；结果在 `artifacts/lip-calibration/scoring-options.json`。离线窗口与浏览器重采样链不同，不能直接等同浏览器帧准确率。

`scripts/benchmark_speech_tts.py` 复现短长句各3次串行HTTP对照，原始快照见 `TTS_BENCHMARK_2026-11-06.json`：首PCM中位数0.124/0.125秒，完整WAV 0.305/1.322秒。顺序为stream后WAV，无排除预热，模型输出随机且样本小；非物理扬声器首音。`scripts/check_voice_metrics.py` 在隔离8875服务复现原生RTVI metrics：此次本地TTS TTFB约0.124s、TTFA约0.139s、processing约0.646s，模型SSE为受控桩，不是DeepSeek延迟。

复现浏览器检查前设置 `PLAYWRIGHT_MODULE` 为已有 Playwright 模块路径；先运行 `.venv-voice/Scripts/python scripts/serve_voice_acceptance.py`，再运行 `node scripts/check_pipecat_voice.cjs`、`node scripts/check_audio_engineering.cjs`。等响度检查另运行 `.venv-voice/Scripts/python scripts/serve_lipsync_acceptance.py` 后执行 `node scripts/check_vowel_shapes.cjs`。`node scripts/check_lipsync_profiles.cjs` 检查主入口普通自动播放握手、两种模板切换、WASM加载失败后的可见回退，既不改服务设置也不申请麦克风。

HF Windows WASAPI/原生AEC3与EdgeVoiceAssistant双工LiveKit APM已源码核对，独立离线实验可运行，但双讲近端投影增益仅0.614，未作为成品AEC接入或通过证据。真实麦克风/扬声器、多人叠说、真人声纹误接收/误拒绝率和30分钟真人交互仍需实际环境验收。

---

# Pipecat 开源语音内核验收（2026-11-05）

生产入口已迁移到 Pipecat 1.15.0、官方 client-js 1.16.0 与 websocket-transport 1.8.2。以下新内核结果与后文旧 JSON/WAV 管线的历史测量分开，不把旧回执或 epoch 测试当作当前覆盖。

## 实际框架与浏览器链路

`scripts/serve_voice_acceptance.py` 使用临时数据库、受控 OpenAI SSE 模型和现有本地 8766 语音；`scripts/check_pipecat_voice.cjs` 运行真实 Edge、官方录放音 worklet/protobuf、真实 Pipecat/Silero/Smart Turn、本地 SenseVoice/VITS 和实际用户角色。麦克风是归一化到固定电平的浏览器原生文件虚拟设备，没有采集物理房间，没有调用 DeepSeek 云端。

已验证：官方握手且打开页面不获取麦克风；模拟权限拒绝后安全重试；实际 PCM 驱动 Cubism 嘴部；约 0.47 秒“好的”被识别并走原生附和而不打断、不触发新 LLM；“等一下，我想换一个问题”触发打断并生成下一条回复；手动停止后口型归零；停麦释放音轨；同会话断线自动重连且不自动开麦；键入消息只持久化一次；桌面与 390px 窄屏没有水平溢出。输出在 `artifacts/pipecat-acceptance/browser.json` 和桌面/窄屏截图。浏览器没有 pageerror。主入口另经普通自动播放策略验证握手和缺密钥提示，服务错误后退出忙碌状态；首次初始化不依赖用户提前解锁声音。最终复测还检查起始静音持续上行、附和只显示一次；20 秒纯待机复查取得 205 帧、四个时间窗均有实际动画，无渲染错误。

三次受控样本的插话输入约 1.82–2.03 秒，按虚拟文件名义起点估计到框架 interruption 事件约 2.68–3.27 秒。最终普通自动播放策略复测的输入约 1.871 秒，到 interruption 约 2.851 秒。这包含用户说话、采集/传输、VAD 收尾及最终 ASR，并非物理扬声器停声时刻，也不是 P50/P95。当前硬打断等最终转写，低延迟连续语义插话仍有改进空间。

## 连续性和回归

- `scripts/stress_pipecat_protocol.py --turns 10`：一个官方协议连接，第一轮实际 PCM→ASR，后九轮 RTVI 文字，十轮均真实本地 TTS/PCM 输出、等待完整 bot-stopped。10 条 user / 10 条 assistant 持久化，未断线。它是十轮输出稳定性测试，不能称为十轮真人语音。输出 `artifacts/pipecat-acceptance/stress.json`。
- `.venv-voice` 中网关、官方握手、同会话清理、语音 frame/WAV 适配、共享 TTS context、附和和 observer 测试：12 passed。
- `.venv` 中本地语音推理/持锁与可选本地模型测试：7 passed / 1 skipped；跳过实际加载可选 LLM。
- 前端：26 tests passed，干净 `npm ci` 两个固定版补丁成功，TypeScript/Vite 生产构建成功。真实浏览器还断言“好的”只显示一次。保留上游弃用提示和既有 bundle 大小提示，不将它们当功能测试失败。
- `speech/benchmark_vad.py`：静音、固定种子低幅白噪声、两条本地合成中文，比较 Silero 门限。仅支持这组组件选择，不证明真实噪声/外放鲁棒性。
- 46 个完整上游源码归档均下载成功，提交号和 SHA256 记录于 `docs/UPSTREAM_SOURCES.json`。这是源码取得证据，不是所有完整应用已安装运行或统一 A/B 跑分。

## 交付边界

默认 CPU SenseVoice/VITS；NPU Whisper 未通过中文质量门槛。ASR 按片段，TTS 按句生成 WAV 后转 PCM。框架取消不强行抢占原生计算；历史按框架输出顺序保存，没有浏览器精确播放 ACK。中文附和是窄规则，不是通用语义模型。真实外放 AEC、真人/方言/噪声误打断率、30 分钟真人连续交互以及 DeepSeek 真实云端性能尚未验收。主入口 8765 已运行新网关，`/api/voice/config` 返回 Pipecat 1.15.0 / protobuf-websocket；本地 ASR/TTS 均 ready。API 密钥需用户在应用设置填写，不通过聊天传递。

旧管线脚本移至 `scripts/legacy/`，不再作为当前验收入口。下面保留历史结果，便于追溯，均不得直接套用到 Pipecat 新内核。

---

# 验收记录 · 2026-11-05

## 当前交付状态

本地应用已实现并启动。用户选择的主配置是 DeepSeek 官方兼容 API / `deepseek-chat`，原始语音在本机识别与合成。官方端点已连通，未提供密钥时返回预期 HTTP 401；用户尚需在应用设置填写密钥。未将本地模型的性能测量描述为 DeepSeek 云端性能，也未宣称已用真实密钥完成云端对话。

角色已切换到用户提供的 DeepSeek-chan（大肥鱼）模型，素材包与导出文件保存在本机，不提交 Git；原画及拆分为神宫凉子，Live2D 建模为霓虹猫_NeonNeko。模型来源、署名及使用限制见 [DEEPSEEK_SKIN.md](DEEPSEEK_SKIN.md) 和模型自带使用须知。下方原有浏览器对话检查对应此前的角色版本；新角色检查单列如下。

## DeepSeek-chan 角色验收

主服务生产构建已通过，前端及复用的 AIRI 算法、适配器共 26 项测试通过。已固定复用 AIRI 提交 `759fff0e646364fe3ad78c64a12f5f9739877e7a` 的色彩补丁与 MAGIC 生成器、滤波和动作配置，来源见 [AVATAR_OPEN_SOURCE.md](AVATAR_OPEN_SOURCE.md)。主目录干净执行 `npm ci --include=dev --no-audit` 后自动应用补丁；归一化为 LF 后的渲染器哈希与上游补丁结果一致。

Edge headless 实际加载 moc3 和五张纹理，检查了旧模型地址迁移、爱心眼像素变化、自然动作开关及实际头部变化、受控 WAV 开口、停止与旧音频丢弃、1440px 桌面、1080×1920 全屏和 390px 窄屏。按钮与 Escape 均可退出全屏。眼部爱心表情差异为 7.38%，待机对照 2.39%；仅说明此次场景的可见变化。

鼻部 `Part46` 保持可见。色彩补丁已消除黑块，恢复鼻线，不再隐藏鼻部，模型原始文件未修改。上一轮仅检查 1.8 秒头部参数变化，未充分证明持续待机观感；本轮针对用户反馈增加以下连续验收。

### 连续待机修复与验证

根因包括：额外将动作强度压至 0.15、漏接 AIRI 的整体位置通道、动作更新发生在物理之后，以及本模型将标准 `ParamAngle` / `ParamBodyAngle` 作为物理输出。把更新提前仍会被模型物理覆盖，因此需要写作者设计的 `AngleX/Y/Z` 与 `PositionX/Y/Z` 输入。修复保持原始物理系统、AIRI 的生成与滤波，默认幅度 0.6，增加用户幅度调节和关闭时平滑归中。SDK 自带眨眼在该皮肤的配饰待机动作运行时仍会更新。

`scripts/check_idle.cjs` 在真实主服务以 1440×1000 录制 20 秒无声音待机；每 5 秒统计最终绘制参数和 Part81 身体、Part82 领子、Part85 胸衣、Part89 腰衣的实际顶点变化。四个窗口的身体 X 角度范围分别为 8.092°、7.628°、10.508°、7.616°；胸衣最大局部顶点变化分别为 0.024531、0.016453、0.025744、0.014874（模型局部坐标单位，不是像素）。各窗口均有持续头身运动，20 秒内检测到闭眼与呼吸，静音嘴部为零。网格变化断言可捕捉此前只有位置漂移或呼吸微动、头身参数被覆盖的故障。

录像和截图在 `artifacts/idle-motion/`；`idle.webm` 是完整连续观察，`idle-preview.gif` 是前 10 秒压缩预览。已独立查看间隔帧和预览，能看到头身姿态、眨眼和重心变化。关闭自然动作后的两秒状态另有记录。该测试无真人输入，不作为对话延迟、声学效果或达到真人自然度的证明。

受控 WAV 的实际嘴部参数峰值 0.804，打断后 0.000。测试等待实际开口信号后再截图，不把解码队列处于 busy 当作已发声。三秒 headless `requestAnimationFrame` 调度间隔中位 16.7ms、P95 25.0ms（165 样本），不是物理显示帧率或 GPU 完成帧率。

截图和完整结果在 `artifacts/deepseek-avatar/`。此次注入本地 WAV，没有使用真人麦克风、测量扬声器延迟或完成 DeepSeek 云端对话。MAGIC 接入不代表已经达到真人或 Neuro-sama 的自然度；高级情绪行为、精细音素口型与完整 AIRI 舞台均未包含。

另有可运行的离线备用：SenseVoice CPU + Qwen3 1.7B INT4 CPU/GPU + sherpa 中文 VITS CPU。它完成了真实模型、真实 WAV、浏览器播放及虚拟麦克风的完整验收。

## 功能检查

| 检查 | 结果 | 方法 |
| --- | --- | --- |
| 后端流式解析、取消、持久化、上下文预算 | 通过 | pytest，含 `[DONE]` 后拒绝迟到内容 |
| 本地语音输入校验、NPU 质量门禁、SenseVoice 接入 | 通过 | pytest + 实际合成/识别 |
| 本地模型 Unicode 流式输出与取消锁 | 通过 | pytest，实际 Qwen3 模型测试单独开启并通过 |
| 前端播放清空、迟到解码丢弃、PCM 编码、epoch 过滤 | 通过 | Vitest 4 项 |
| 生产构建 | 通过 | TypeScript + Vite |
| 默认 Live2D 实际渲染 | 通过 | Edge 浏览器，实际加载 moc3 和纹理 |
| 设置保存、真实声音播放与播放完成后的历史记录 | 通过 | 真实本地服务 + 浏览器 Web Audio |
| Silero VAD / AudioWorklet / ASR | 通过 | 浏览器受控虚拟麦克风，准确转写测试中文 |
| 桌面 1440px 与窄屏 390px | 通过 | 截图、无水平溢出检查 |
| 运行时远程静态资源 | 无 | 浏览器记录的外部资源请求为 0 |
| 打断后旧音频 | 测试中 0 帧 | 收到 audio.clear 后监测、下一轮继续对话 |

最新快速回归为 12 passed / 1 skipped（默认跳过需要真实本地大模型的可选用例）；真实模型用例在先前完整运行中已开启通过。框架有一条 TestClient 弃用提示，未影响执行。最新脱敏设置状态为 `api_key_set=false`，不代表已经完成 DeepSeek 云端对话测试。

## 本机语音设备结论

硬件：Core Ultra 5 225H / 32GB RAM / Arc 130T / Intel AI Boost。OpenVINO 2026.4.1 能枚举 CPU、GPU、NPU。

Whisper base INT8 和 FP16 在 NPU 均能编译，但同一中文音频产生重复标点等异常结果，故拒绝投入使用；不是仅凭编译成功就报告 NPU 推理可用。CPU/GPU Whisper 可识别中文，但 base 在部分测试句出现语义错误。

同一组三段合成中文音频的对照：

| 方案 | 热机识别耗时 | 文本质量 |
| --- | --- | --- |
| SenseVoice INT8 CPU | 48–74ms | 三段均正确，含测试电话号码 |
| Whisper small INT8 CPU | 约 1.3–1.8s | 大部分短句正确，数字仍有错误 |
| OpenVINO Whisper base INT8 GPU | 约 74–130ms | 某些中文短句明显误听 |

因此当前默认优先 SenseVoice CPU。TTS 使用 sherpa-onnx 中文 VITS CPU，单次短句 HTTP 合成约 0.28s。上述是小样本热机测试，不替代真人、方言和噪声测试。原始对照为 `artifacts/asr-benchmark.json`。

## 连续 20 轮对话性能

相同的十条中文提示序列各执行两遍，使用本地 TTS 生成输入，再经过真实 ASR、LLM、TTS。指标定义为：**提交完整用户音频后，到客户端收到第一段 WAV**。不包括等待用户说完的 VAD 静音、浏览器解码、缓冲、扬声器或声卡延迟。测试即时模拟播放确认，未等待声音物理播放。

| LLM 设备（语音均为 CPU） | 轮数 | 首 WAV P50 | P95 | 最大值 |
| --- | --- | --- | --- | --- |
| CPU | 20 | 1.646s | 3.343s | 3.860s |
| Intel GPU | 20 | 1.108s | 1.439s | 2.157s |

每次模型采样回复内容可能不同，所以这不是严格固定输出的硬件基准。完整输出与每轮文本在 `artifacts/conversation-benchmark-cpu.json`、`artifacts/conversation-benchmark-gpu.json`。另有固定提示、贪心输出的单模型对照：预热后首字中位 CPU 0.243s / GPU 0.100s；完成中位 CPU 1.148s / GPU 0.679s，见 `artifacts/llm-benchmark.json`。

本地取消测试的 clear 网络往返约 1–2ms，不包含 VAD 检测、用户开口时间和实际声学播放停止延迟。不能将其称为“用户插话到声音停止只需 1ms”。

## 可复现产物

- `scripts/smoke_live.py`：真实音频往返、取消、无旧音频、上下文保存检查。
- `scripts/test_ui.cjs`：真实浏览器、实际声音播放确认、虚拟麦克风 VAD、移动布局。
- `scripts/check_idle.cjs`：20 秒纯待机录像、每五秒真实头身和衣物网格断言、眨眼与呼吸。
- `scripts/check_avatar.cjs`：实际 DeepSeek 角色纹理、眼部表情、受控 WAV 和竖屏截图；不调用云端模型。
- `scripts/benchmark_conversation.py`：20 轮语音提交至首 WAV。
- `inference/benchmark.py`、`speech/benchmark_asr.py`：组件对照。
- `artifacts/ui/desktop.png`、`mobile.png`、`results.json`：浏览器截图与事件记录。
- `requirements-lock.txt`、`web/package-lock.json`：依赖锁文件。

`artifacts/` 为本机验收输出，不提交 Git；跟随源码提交的报告记录其方法与边界。

## 尚未验收或实现

真实麦克风/扬声器回声、误打断率、自然附和、30 分钟真人连续交互和长期散热负载没有完成物理测试。浏览器设置了 AEC/降噪约束，未证明达到 AEC3 的声学效果。没有实现语义 VAD、细粒度音素口型、声音克隆、摄像头、自动记忆提取、开机自启动或安装包。

当前本地 VITS 声线和粗粒度关键词表情是可用基线。接近真人的韵律、角色细腻表现和外放环境下的自然轮替仍需在目标硬件及角色素材上继续验收。

## 2026-11-05 语音与打断专项复查

详细机制、固定开源对照和剩余缺口见 [VOICE_AUDIT.md](VOICE_AUDIT.md)。本次没有把基础打断测试当作自然轮替已达标。

- 最终 Python 回归：20 passed / 1 skipped；跳过可选真实本地 LLM，保留一条 TestClient 弃用提示。隔离数据库验证播放背压、失败中止、异常前后回执历史和同会话连接保护；语音测试验证排队取消与运行中持锁。
- 最终前端：32 tests passed；TypeScript/Vite 生产构建成功。存在既有大 bundle 警告。VAD 与 Pixi 补丁在主工作区均成功应用，前端 worktree 另完成干净安装验证。
- `scripts/check_voice_turns.cjs`：实际 Silero/AudioWorklet/WebAudio、虚拟麦克风、受控 WS，权限拒绝后恢复、插话停播、旧代 WAV 拒收、后续发言、断线释放轨道和人工重开均通过。最终单次降音量159ms、调用停播420ms；“对，好的。”约793ms仍触发打断，记为未满足项。
- `scripts/audit_voice_pipeline.py`：临时数据库、生产 Conversation、受控模型 SSE、真实本地 CPU ASR/TTS。转写正确，提交至首 WAV 约1.028s；取消完成38ms；下一条短文本仍需约3.549s获得 WAV，反映单片段原生计算不能立刻抢占。没有旧代音频，已听历史正确。
- `scripts/test_ui.cjs` 修正了等待旧 Haru 模型和写入实时设置的问题；本轮没有将它列为 DeepSeek 云端全链路通过。

产物为 `artifacts/voice-audit/browser-turns.json`、`pipeline.json` 与固定上游资料 `references/`。浏览器时序不是物理声学指标；受控模型结果不是 DeepSeek 数据，模拟回执不是实际播放。真人20轮/30分钟、语义附和、外放AEC、设备拔插和云端性能门槛保持未通过。
