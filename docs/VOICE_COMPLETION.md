# 语音差距逐项补齐表

> **2026-11-14 当前状态：MFA 运行功能已退役。** 本文涉及 MFA 的实现、安装、命令、测试和结果均为历史记录，不是当前可选功能；相关启动/安装/浏览器时间轴验收入口已经移除。当前仅使用实时 PCM 口型，见 [实时口型](REALTIME_LIPSYNC.md)。E 盘历史环境与权重未自动删除。下文旧“当前”描述不再代表现行状态。

来源：46 个固定上游，99 项原始能力；审计基线 `5c5ce43`。更新：2026-11-07。

本表是实施与验收记录。原始审计保留于 [CURRENT_VOICE_GAPS.md](CURRENT_VOICE_GAPS.md)。同一能力的不同开源实现关联到同一工作项；保留每个出处，避免遗漏，也避免重复引入互斥的推理/播放栈。已有能力保留回归项；非同类架构保留候选评估项。

**状态以证据为准：代码接入、合成样本通过、真人/物理设备验收分别记录。待实测与条件受限均不是已完成。CPU 推理不能作为 NPU 验收。**

历史任务状态（不含上述退役调整）：已验收 6；待实测 11；待实现 1；条件受限 4；非同类候选 1。

工程接入与验收状态分列。CPU 耗时不作为推迟代码接入的条件；独立诊断工具不算生产链路接入，未实现路径不能仅写成待测试。

## 实施工作项与验收

| 工作项 | 优先级 / 负责人 | 工程接入 | 验收状态 | 实现与验收条件 | 本轮证据 / 结果 | 尚需完成 |
|---|---|---|---|---|---|---|
| R01 · 框架音频、取消与连接回归 | P0 / backend/frontend | 已接入 | 已验收 | 保留官方PCM播放器/工作队列/取消；附和、打断、下一轮、断开和重连故障注入全部通过。 | [scripts/check_pipecat_voice.cjs](../scripts/check_pipecat_voice.cjs)；[web/qa/reconnect-resources.cjs](../web/qa/reconnect-resources.cjs)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；官方Pipecat/RTVI客户端与PCM worklet、真实CPU ASR/TTS、虚拟麦克风8项回归通过；附和不取消、明确插话打断并进入下一轮、停止/关麦/重连通过。已修8秒连接超时与独立录音AudioContext释放。 实际Edge三次握手/开麦后断线再重连并手动重开通过；峰值2个活动AudioContext（播放+录音），旧资源全关闭，恢复后仅当前资源。 | 本机官方链路故障注入已验收；广域网抖动与真人长会话另见E02/A02。 |
| S01 · 在线中文部分识别、端点和token时间 | P0 / speech/backend | 已接入 | 待实测 | 使用维护的在线识别模型；真实PCM中间结果先于语句结束；最终结果只提交一次；中文短语/数字/噪声、实时因子和首部分结果均实测。 | [speech/streaming_asr.py](../speech/streaming_asr.py)；[speech/pipecat_services.py](../speech/pipecat_services.py)；[docs/VOICE_CORPUS_AFTER_2026-11-06.json](VOICE_CORPUS_AFTER_2026-11-06.json)；真实CPU在线Zipformer已接入Pipecat；稳定partial不入context，SenseVoice final一次；12项节奏输入语料9项出现文字，首partial wall P50 0.718s/P95 1.462s(n=9)，极短嗯无结果。 | 真人中文短命令/数字/噪声质量、端点与RTF分布；默认可选，不把合成语料当真人。 |
| S02 · 更早打断、声纹门禁及附和保护 | P0 / speech/backend | 部分接入 | 待实测 | 稳定部分转写可启动打断；owner_only模式未验证身份不得打断/进入LLM/历史；噪声和短附和保留播放。 | [speech/pipecat_turns.py](../speech/pipecat_turns.py)；[speech/test_pipecat_services.py](../speech/test_pipecat_services.py)；[tests/test_playback.py](../tests/test_playback.py)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；稳定明确停止意图或>=4字符非附和可早打断；owner模式关闭preview，final严格本人门；禁空轮自动LLM；旧话段guard防迟到interim。 最新Edge虚拟麦克风单次1.967秒明确插话至interruption约1.523秒，不是开口即停或物理停止延迟。 | 真人双讲误打断率；本人模式仍需>=2秒验证，尚无验证后partial早打断。 |
| M01 · 修复MFCC十二系数并重新校准 | P0 / frontend/integrator | 已接入 | 已验收 | 固定上游C源码可重现构建；六类配置十二系数全部更新；新算法重采集profile并记录hash。准确率单列在M02与中文校准验收中。 | [web/vendor/wlipsync/README.md](../web/vendor/wlipsync/README.md)；[docs/WLIPSYNC_REPAIR_2026-11-06.json](WLIPSYNC_REPAIR_2026-11-06.json)；[docs/LIPSYNC_PROFILE_PROVENANCE.json](LIPSYNC_PROFILE_PROVENANCE.json)；[docs/LIPSYNC_BINARY_EQUIVALENCE_2026-11-06.json](LIPSYNC_BINARY_EQUIVALENCE_2026-11-06.json)；两次可复现构建hash一致；原版6槽哨兵残留、修复版0槽；新声线模板经新WASM采集，JSON和二进制328帧分类完全一致。 | 依赖系数写入缺陷已修；E/O/U泛化、精确中文音素时间仍未达标，继续见M02与E02。 |
| M02 · 历史强制对齐（已移除） | P1 / speech/frontend | 已退役 | 不适用 | 将音素/viseme时间区间绑定实际播放时钟，打断/重连清理；中文对齐精度和额外首音等待与MFCC方案对照。 | [speech/forced_alignment.py](../speech/forced_alignment.py)；[speech/requirements-alignment.txt](../speech/requirements-alignment.txt)；[docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[speech/mfa_alignment.py](../speech/mfa_alignment.py)；[speech/prepare_mfa.py](../speech/prepare_mfa.py)；[speech/MFA_ALIGNMENT.md](../speech/MFA_ALIGNMENT.md)；[scripts/serve_phoneme_acceptance.py](../scripts/serve_phoneme_acceptance.py)；[web/src/avatar/lipsync/phonemeTimeline.ts](../web/src/avatar/lipsync/phonemeTimeline.ts)；[web/qa/phoneme-browser.cjs](../web/qa/phoneme-browser.cjs)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；[speech/mfa_sidecar.py](../speech/mfa_sidecar.py)；[speech/alignment_audio.py](../speech/alignment_audio.py)；[web/src/avatar/lipsync/mandarin-visemes.json](../web/src/avatar/lipsync/mandarin-visemes.json)；[web/qa/optional-voice-browser.cjs](../web/qa/optional-voice-browser.cjs)；[docs/VOICE_ENGINEERING_2026-11-06.json](VOICE_ENGINEERING_2026-11-06.json)；MFA实际普通话IPA TextGrid已导出并严格校验；可信同WAV hash/epoch的可选时间轴已接协议消费者，worklet实际消费样本推进，真实Edge/DeepSeek的i嘴形、静音、mute、stop通过。错epoch帧确认转发且后续boundary/ACK完成。Qwen仅字词，不冒充phoneme。 根据工程优先要求已接入可选生产MFA路径：每次实际TTS生成→16kWAV→MFA→hash/区间核验→24k播放epoch；真实Edge验证嘴形变化、完整ACK、等待时停止后3085ms释放MFA、无迟到音频、下一轮完整历史一致。普通话IPA配置扩充带调/圆唇/闭唇，复韵母静态近似不捏造子区间。 CosyVoice持续文本+MFA+Edge/Cubism组合亦通过，停止等待对齐本次80ms释放（单次工程取消测量，非声卡/双讲延迟）。 | 中文音素人工准确率、近似viseme视觉质量与音色泛化待测；MFA目前完整合成后离线对齐再播放，CPU耗时如实展示。 |
| M03 · 角色专属嘴映射、预计算profile | P1 / frontend | 已接入 | 已验收 | 多嘴参数映射配置化且校验实际模型ID/范围；预计算profile与原JSON分类一致、保留可复现来源。 | [web/src/avatar/lipsync/mouth-mappings.json](../web/src/avatar/lipsync/mouth-mappings.json)；[web/vendor/wlipsync/json2bin.mjs](../web/vendor/wlipsync/json2bin.mjs)；[web/src/avatar/lipsync/local-vits-profile.bin](../web/src/avatar/lipsync/local-vits-profile.bin)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；413B官方二进制profile与JSON328帧分类完全一致；修复CSP下data加载失败，改同源实体资源。真实Edge默认/切换模板/故障回退及等RMS五元音实际嘴参数、停止清零通过。 | 映射/二进制工程项已验收；精确中文音素与E/O/U泛化继续归M02及E02。 |
| M04 · 表情映射及播放时序队列 | P1 / frontend | 已接入 | 已验收 | 角色表情映射可配置；表情按播放段而非提前LLM文本激活；打断/停止/下一轮不会残留。 | [web/src/emotionQueue.ts](../web/src/emotionQueue.ts)；[web/src/emotionQueue.test.ts](../web/src/emotionQueue.test.ts)；[web/src/emotionKeywords.json](../web/src/emotionKeywords.json)；[server/playback.py](../server/playback.py)；[web/src/avatar/expression-mappings.json](../web/src/avatar/expression-mappings.json)；[web/qa/emotion-browser.cjs](../web/qa/emotion-browser.cjs)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；复用Pipecat原生AggregatedTextFrame按context_id在start附对应文本，前端首次实际consume才激活且单段去重；boundary兼容回退。角色表情/关键词均源码JSON可配置，中断/重连清理。真实Edge两句开心/难过在各epoch首次消费后分别驱动DeepSeek key7/key2>0.1，无页面错误。 | 段级播放同步工程项已验收；关键词表情并非情感模型，精确词/音素时序及真人观感另需评估。 |
| A01 · 同步真实播放参考的原生AEC | P0 / integrator | 独立诊断，未接生产 | 待实现 | 同一设备时钟的render/capture参考，真实ADC/DAC时间记录；原生APM只接独立双工链，未经对照不得叠加生产浏览器AEC。 | [scripts/capture_aec_device.py](../scripts/capture_aec_device.py)；[requirements-device-audio.txt](../requirements-device-audio.txt)；新增独立sounddevice单流render/capture+LiveKit APM工具，保存实际ADC/DAC时间与原始/处理音频；已验证数值指标，不采集麦克风。 | 代码缺口：生产原生双工设备/同钟播放参考路由、浏览器AEC显式切换与回退未实现。物理验收：实际外放与双讲保真未测；当前生产使用浏览器AEC。不是CPU耗时阻挡。 |
| A02 · 外放、噪声及双讲验收 | P0 / integrator | 需现场设备与样本 | 待实测 | 同设备原始/处理后音频；远端单讲回声衰减、近端单讲与双讲保真、误打断、丢帧/削波均记录；真人确认听感。 |  | 需要实际目标扬声器/麦克风和本人双讲录音；合成混音不是物理验收。 |
| P01 · 真实播放进度/完成回执与过期保护 | P0 / backend/frontend | 已接入 | 已验收 | ACK由worklet已消费PCM产生；连接/turn/track epoch校验、单调偏移、完成与丢弃分离，旧ACK不得污染新轮。 | [scripts/check_playback_receipts.cjs](../scripts/check_playback_receipts.cjs)；[server/playback.py](../server/playback.py)；[web/src/playback.ts](../web/src/playback.ts)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；真实Edge短回复2 contexts、长回复6 contexts，逐段consumed严格等于boundary且各1次ACK；未完成旧段拒绝、下一轮可播放。迟ACK、重复、越界、128项有界/退休及失败上下文单测通过。 | 工程协议已验收；完整段确认不是逐字进度或声卡已听，真人/物理测量另见A02/E02。 |
| P02 · 已播放历史与误打断恢复 | P1 / backend/frontend | 部分接入 | 待实测 | 只把有完成证据的音频文本段计入已播放上下文；无字级对齐不声称逐字已听；假插话恢复原播放或明确安全重生成。 | [server/playback.py](../server/playback.py)；[tests/test_playback.py](../tests/test_playback.py)；[tests/test_pipecat_voice.py](../tests/test_pipecat_voice.py)；[web/qa/continue-browser.cjs](../web/qa/continue-browser.cjs)；[web/src/App.tsx](../web/src/App.tsx)；[web/qa/optional-voice-browser.cjs](../web/qa/optional-voice-browser.cjs)；[docs/VOICE_ENGINEERING_2026-11-06.json](VOICE_ENGINEERING_2026-11-06.json)；原生per-context模式并显式flush消除每段默认3秒等待；真实Edge确认前2段后停止，仅保留连续前缀且一条DB记录，下一轮正常。多epoch乱序ACK、同全文不同prefix、220段/220轮有界与上下文截断通过。临时duck保留未取消播放。 新增用户显式“继续刚才的回答”作为普通新轮接续，浏览器已验证不自动发送，点击才发新LLM请求，新问题清入口，不复活旧任务。 停止后生成字幕明确标注未必全部播放；语音准备阶段始终提供停止。浏览器音频resume版本校验阻止停止后发送旧文本；优先RTVI stop/ACK避免慢send-text flush堵塞停止。真实MFA停止与下一轮ACK/history通过。 已修重复相同回复归属错误：下一轮使用Store已确认历史快照，保留原生tools/tool_choice；实际Cosy+MFA重复回复及取消轮的完整下一轮LLM请求顺序通过。 | 硬取消后采用显式新轮重生成；无原音暂停续播与逐字已听位置，接续语义与真人误打断体验待测。 |
| E01 · 队列、溢出/欠载与用户可感知延迟 | P1 / backend/frontend/integrator | 已接入 | 已验收 | 客户端样本时钟/队列水位/欠载/溢出可观测；阶段与播放时间分开，重复样本报告P50/P95及样本量；不混用跨机单调时钟。 | [server/voice_metrics.py](../server/voice_metrics.py)；[tests/test_voice_metrics.py](../tests/test_voice_metrics.py)；[scripts/check_voice_soak.cjs](../scripts/check_voice_soak.cjs)；[docs/VOICE_SOAK_2026-11-06.json](VOICE_SOAK_2026-11-06.json)；客户端水位/underrun/overflow/消费可观测且10秒cap；pending/invalid有界。最新分段版1807.417秒206轮177完成29取消，活动AudioContext恒1、0溢出、无mic申请；短回复消费完成P50/P95与长回复分组记录。服务端阶段分布独立报告，非声卡首音。 | 本机浏览器队列与消费工程项已验收；真实跨设备/网络/声卡延迟仍需独立测量。 |
| E02 · 中文语料、压力与长期验收 | P1 / integrator | 已接入 | 待实测 | 中文短指令/数字/附和/噪声可重复；ASR CER、端点与打断延迟有分母；持续30分钟会话及恢复测试无资源增长。 | [scripts/prepare_voice_corpus.py](../scripts/prepare_voice_corpus.py)；[scripts/benchmark_voice_corpus.py](../scripts/benchmark_voice_corpus.py)；[docs/VOICE_CORPUS_BEFORE_2026-11-06.json](VOICE_CORPUS_BEFORE_2026-11-06.json)；[docs/VOICE_CORPUS_AFTER_2026-11-06.json](VOICE_CORPUS_AFTER_2026-11-06.json)；[docs/VOICE_CORPUS_MATCHED_2026-11-06.json](VOICE_CORPUS_MATCHED_2026-11-06.json)；[docs/VOICE_SOAK_2026-11-06.json](VOICE_SOAK_2026-11-06.json)；12条同文件/hash中文合成/静音/噪声语料各3次，before/after均36次、318参考字符。普通HTTP非人声假转写由6/6降至0/6；有声CER仍14.15%，没有掩盖短句/数字错误。在线另有节奏输入首partial/端点报告，不与离线时延混合。 分段版完整30分钟206轮（177完成/29取消）通过；旧整context基线另完整225轮。 | 真人中文/方言/数字、短命令、声纹与双讲长期会话待测，合成与无麦克风压力不是真人验收。 |
| S03 · 时间戳、多语种和VAD输入质量 | P1 / speech | 已接入 | 待实测 | 可选词/token/VAD时间区间明确层级；重采样/WAV质量校验不回退污染；离线Whisper对齐不冒充TTS音素时间。 | [speech/quality.py](../speech/quality.py)；[speech/server.py](../speech/server.py)；[speech/test_quality.py](../speech/test_quality.py)；[docs/VOICE_CORPUS_AFTER_2026-11-06.json](VOICE_CORPUS_AFTER_2026-11-06.json)；[docs/VOICE_CORPUS_MATCHED_2026-11-06.json](VOICE_CORPUS_MATCHED_2026-11-06.json)；普通HTTP转写复用Silero独立人声门，非owner不要求2秒；结构化WAV/VAD区间、online token时间；离线word/token明确null与原因。 | 当前SenseVoice无词级对齐；中文多语种与极短语音漏检需改进，VAD时间不是phoneme时间。 |
| I01 · 本人模板、短命令和声纹质量 | P1 / speech/backend | 部分接入 | 待实测 | 多样本模板/质量检查、阈值与相似度；短命令不借身份缓存旁路门禁；真人FAR/FRR按数据集标定。 | [server/main.py](../server/main.py)；[speech/speaker.py](../speech/speaker.py)；[docs/AUDIO_ENGINEERING.md](AUDIO_ENGINEERING.md)；[docs/VOICE_ACCEPTANCE_2026-11-06.json](VOICE_ACCEPTANCE_2026-11-06.json)；[scripts/benchmark_owner_corpus.py](../scripts/benchmark_owner_corpus.py)；[speech/short_speaker_evaluation.py](../speech/short_speaker_evaluation.py)；[speech/test_short_speaker_evaluation.py](../speech/test_short_speaker_evaluation.py)；[docs/VOICE_ENGINEERING_2026-11-06.json](VOICE_ENGINEERING_2026-11-06.json)；原有严格本人门保留，启停/改语音服务/删除模板后关闭旧连接，校验失败不关闭；新连接不自动开麦。 新增独立标签语料评测，不改本人模板；FAR排除静音噪声，短本人不确定计入有效FRR，合成两条本人一短句被拒，不能外推真人。 新增0.5/1/1.5/2秒独立实验入口与可复用helper，按同一真实模型/VAD报告分数、拒绝原因和分母，不改生产2秒门。合成小样本每窗2本人/1旁人，0.5秒本人有效拒绝2/2，其余1/2，旁人误接受0/1；不能推断真人准确率或据此降低门槛。 | 代码/质量缺口：生产仍要求>=2秒有效人声，短命令未解决；独立短窗评测入口已实现并以合成小样本跑通，需真人注册及短句FAR/FRR/重放/噪声评测后才能调整门槛。没有身份缓存旁路。 |
| I02 · 在线说话人跟踪与重叠人声提取 | P1 / speech | 独立诊断，未接生产 | 条件受限 | 区分说话人跟踪、注册本人匹配、重叠分离三层；模型真实在线运行并测实时因子与目标人声保真。 | [docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[speech/diarization.py](../speech/diarization.py)；[speech/prepare_diarization.py](../speech/prepare_diarization.py)；[speech/DIARIZATION.md](../speech/DIARIZATION.md)；实际CPU运行pyannote3 ONNX+ERes2Net；10秒双声线耗时0.914秒，但同一VITS被拆成两类且Kokoro混入其中，质量失败，不接生产。 固定官方archive SHA与离线诊断CLI已保留，identity_verified=false，不把匿名speaker标签当用户身份。 | 代码缺口：在线窗口状态、跨窗口说话人关联和重叠目标人声提取未实现。已测离线聚类质量失败；匿名标签不能替代本人验证。不是CPU耗时阻挡。 |
| T01 · 真正持续文本输入与增量语音 | P1 / speech/backend | 已接入 | 待实测 | CosyVoice2/3非vLLM生成器路径或等价引擎可持续接收文本；有界队列、取消持锁、首音/质量对照；按句PCM仍保留可用回退。 | [server/cosyvoice_prepare.py](../server/cosyvoice_prepare.py)；[server/cosyvoice_probe.py](../server/cosyvoice_probe.py)；[server/COSYVOICE_PROBE.md](../server/COSYVOICE_PROBE.md)；[docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[server/cosyvoice_sidecar.py](../server/cosyvoice_sidecar.py)；[speech/cosy_bistream.py](../speech/cosy_bistream.py)；[tests/test_cosy_pipeline.py](../tests/test_cosy_pipeline.py)；[requirements-cosyvoice-cpu-lock.txt](../requirements-cosyvoice-cpu-lock.txt)；[docs/OPTIONAL_VOICE_SERVICES.md](OPTIONAL_VOICE_SERVICES.md)；[docs/VOICE_ENGINEERING_2026-11-06.json](VOICE_ENGINEERING_2026-11-06.json)；[docs/COSYVOICE3.md](COSYVOICE3.md)；[docs/COSYVOICE3_ACCEPTANCE_2026-11-07.json](COSYVOICE3_ACCEPTANCE_2026-11-07.json)；[scripts/check_cosyvoice3.py](../scripts/check_cosyvoice3.py)；[web/qa/cosyvoice3-browser.cjs](../web/qa/cosyvoice3-browser.cjs)；CosyVoice2固定权重已全部校验，固定上游+Matcha在WSL CPU真实generator文本双流产出3块共4.28秒音频；模型加载52.005s、首PCM12.450s、合成26.503s、RTF6.192，4线程单次。CPU速度独立记录；可选生产链路已接入。 可选CosyVoice2原生TOKEN持续输入已经接入生产factory及UI；有界队列、实际消费text_ack反压、context过期防重放、隔离worker取消join及后继请求、正常完成warm复用均实现。真实CPU常驻/取消重建已通过；新消费确认及Cosy+MFA真实Edge整链通过：本次同WAV哈希/音素/实际样本时钟、取消无迟到音频、下一轮ACK与重复回复归属均通过。 2026-11-07：已选择官方Fun-CosyVoice3-0.5B-2512并完成固定revision/12文件校验；第三代CPU FP32真实文本双流、ASR去标点回读一致、warm复用、取消回收和Edge/Cubism消费/完整历史/停止无迟到音频通过。新模型选择已写入应用设置；GPU/NPU未验收。 | 真人中文音质/跨句韵律待验收；GPU/NPU另验，不以CPU耗时推迟接入。 |
| T02 · 参考音色、提示缓存与韵律控制 | P1 / speech | 已接入 | 待实测 | 合法参考音频、clone/prompt缓存/风格及跨句韵律；至少一种开源模型真实中文音质/资源/延迟对照通过。 | [speech/zipvoice.py](../speech/zipvoice.py)；[speech/test_zipvoice.py](../speech/test_zipvoice.py)；[docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[server/cosyvoice_sidecar.py](../server/cosyvoice_sidecar.py)；[docs/VOICE_ENGINEERING_2026-11-06.json](VOICE_ENGINEERING_2026-11-06.json)；[docs/COSYVOICE3_ACCEPTANCE_2026-11-07.json](COSYVOICE3_ACCEPTANCE_2026-11-07.json)；增加维护的sherpa ZipVoice参考音色合成与speed；真实CPU中文WAV/PCM成功并ASR回读正确，单次0.98–1.17s完成回调，RTF约0.54–0.65。 追加复用CosyVoice官方add_zero_shot_spk/zero_shot_spk_id提示缓存，正常完成复用模型与参考特征，取消丢弃重建；参考WAV及精确文本仅服务端本地配置，不接受客户端文件路径。 第三代按官方格式补入endofprompt前缀后缓存参考特征；没有将未知声线或角色名当作已授权参考音色。 | 真人克隆相似度、跨句韵律、自然语言风格控制尚未验收；ZipVoice权重许可状态独立保留。 |
| T03 · 可替换TTS分段/音素接口 | P2 / speech | 已接入 | 待实测 | 统一分段文本、可选音素、样本率和取消契约；中文Kokoro/Piper候选需实际模型评测，音素字符串不称时间戳。 | [speech/kokoro.py](../speech/kokoro.py)；[speech/test_kokoro.py](../speech/test_kokoro.py)；[speech/prepare.py](../speech/prepare.py)；[docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；Kokoro中文int8真实CPU后端已接入、8文件固定hash准备；45号中文声线，首块1.776/3.121秒、RTF0.870/0.803（各单次），长句2回调。ASR回读各有增字。 | 真人音质、中文发音与词典资源许可尚需核查；sherpa接口未暴露音素序列/时间戳，不能当精确口型来源。 |
| D01 · 端到端音频、多模态和模型双工 | P2 / integrator | 模型、许可或设备条件未满足 | 条件受限 | 为Moshi/MiniCPM-o/GLM/Qwen-Omni/vLLM-Omni逐一核对中文、重叠收发、取消、权重、硬件；通过真实对照才替换当前DeepSeek分离链。 |  | 多个独立大模型架构无法由小型接口替代；需要兼容设备/服务和模型，暂未证明本机实时可用。 |
| D02 · 桌面、多用户、分布式与视频头像候选 | P2 / integrator | 按产品需求选择 | 非同类候选 | 明确Electron权限、Redis多会话、GPU服务、视频头像与本机Live2D用途的差异；保留可扩展接口，不把无关功能伪装语音缺口。 |  | 有对应产品需求时独立实现和验收；当前固定单用户Live2D与DeepSeek API。 |
| M05 · 官方MotionSync Core许可与效果对照 | P2 / integrator | 模型、许可或设备条件未满足 | 条件受限 | 取得独立许可Core/SDK，匹配当前模型；中文音频与MFCC逐项比较准确性、首音等待和资源。 | [docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[web/src/avatar/lipsync/mouth-mappings.json](../web/src/avatar/lipsync/mouth-mappings.json)；已核实上游组件不包含Core，官方独立下载脚本本次HTTP403；角色映射机制已移植，未取得/绕过Core。 | 需取得合法Core及SDK再做中文效果和延迟对照；不开源Core不作为必需生产依赖。 |
| N01 · NPU中文语音真正推理验收 | P1 / speech/integrator | 模型、许可或设备条件未满足 | 条件受限 | 模型在实际NPU运行，中文自检与代表语料通过，设备/CPU回退可观测，端到端延迟实测。 | [docs/VOICE_MODEL_DECISIONS_2026-11-06.json](VOICE_MODEL_DECISIONS_2026-11-06.json)；[speech/probe.py](../speech/probe.py)；Whisper INT8/FP16在实际NPU编译后中文自检失败；保留拒绝异常结果和CPU回退。 | 现有Whisper NPU中文自检失败，CPU语音继续可用；未达到NPU验收。 |

## 全部 99 项能力对照

| 编号 | 开源项目 / 能力 | 审计判定 | 补齐工作项 | 当前任务状态 |
|---|---|---|---|---|
| V001 | akkoaya/EvatarFramework · 多样本声纹模板归一化与匹配 | 部分 | I01 | I01: 待实测 |
| V002 | akkoaya/EvatarFramework · 原生客户端重连与退避配置 | 已具备 | R01, E01 | R01: 已验收；E01: 已验收 |
| V003 | aryeo0908/whisper-loop · 独立轮次任务取消与通知 | 已具备 | R01 | R01: 已验收 |
| V004 | aryeo0908/whisper-loop · 流式 LLM 按句入队 TTS | 已具备 | R01 | R01: 已验收 |
| V005 | Code-Amadeus/Amadeus · 基于音量及回声候选的插话判断 | 部分 | S02, P02 | S02: 待实测；P02: 待实测 |
| V006 | Code-Amadeus/Amadeus · 最终音频消费接口 | 已具备 | R01 | R01: 已验收 |
| V007 | datascale-ai/opentalking · Redis 会话状态和任务排队 | 非同类 | D02 | D02: 非同类候选 |
| V008 | datascale-ai/opentalking · 上传音频前明确打断 | 部分 | S02 | S02: 待实测 |
| V009 | FahadiF/Edge-Voice-Assistant · WebRTC APM 双向参考处理 | 缺失 | A01, A02 | A01: 待实现；A02: 待实测 |
| V010 | FahadiF/Edge-Voice-Assistant · ASR 过期结果 epoch 丢弃 | 待验证 | S02, E01 | S02: 待实测；E01: 已验收 |
| V011 | huggingface/speech-to-speech · 带时间戳播放参考的 AEC | 缺失 | A01, A02 | A01: 待实现；A02: 待实测 |
| V012 | huggingface/speech-to-speech · 音频时间轴口型事件 | 部分 | M02 | M02: 待实测 |
| V013 | huggingface/speech-to-speech · 流式说话人分离与跨话段跟踪 | 缺失 | I02 | I02: 条件受限 |
| V014 | liampetti/fulloch · 浏览器 AEC 请求及播放取消 | 已具备 | R01, A02 | R01: 已验收；A02: 待实测 |
| V015 | liampetti/fulloch · 无界面卫星端指数退避重连 | 待验证 | R01, E01 | R01: 已验收；E01: 已验收 |
| V016 | livekit/agents · 自适应打断和误打断恢复 | 缺失 | S02, P02 | S02: 待实测；P02: 待实测 |
| V017 | livekit/agents · 播放完成位置和同步文本 | 缺失 | P01 | P01: 已验收 |
| V018 | pipecat-ai/pipecat · 原生阶段指标和句子聚合 | 已具备 | R01 | R01: 已验收 |
| V019 | pipecat-ai/pipecat · 空用户轮次恢复 | 部分 | S02, P02 | S02: 待实测；P02: 待实测 |
| V020 | pipecat-ai/pipecat-client-web · 打断回调与事件 | 已具备 | R01 | R01: 已验收 |
| V021 | pipecat-ai/pipecat-client-web · 类型化指标消息 | 已具备 | R01 | R01: 已验收 |
| V022 | pipecat-ai/pipecat-client-web-transports · 打断消息处理 | 已具备 | R01 | R01: 已验收 |
| V023 | pipecat-ai/pipecat-client-web-transports · 重连失败事件 | 部分 | R01, E01 | R01: 已验收；E01: 已验收 |
| V024 | pipecat-ai/pipecat-examples · 并行流水线与 VAD | 非同类 | D02 | D02: 非同类候选 |
| V025 | pipecat-ai/pipecat-examples · 框架指标启用示例 | 已具备 | R01 | R01: 已验收 |
| V026 | pipecat-ai/smart-turn · 音频轮次结束预测 | 已具备 | R01 | R01: 已验收 |
| V027 | pipecat-ai/smart-turn · 延迟与吞吐基准 | 部分 | E02 | E02: 待实测 |
| V028 | TacoTakumi/HermesConsole · 物理设备 AEC 验收门槛 | 缺失 | A02 | A02: 待实测 |
| V029 | TacoTakumi/HermesConsole · 可重复打断语音样本 | 部分 | E02, A02 | E02: 待实测；A02: 待实测 |
| V030 | TacoTakumi/VoiceManager · 增量 STT 中间结果与最终结果 | 缺失 | S01, I01, E02 | S01: 待实测；I01: 待实测；E02: 待实测 |
| V031 | TacoTakumi/VoiceManager · 客户端播放边界与麦克风样本时钟 | 缺失 | P01 | P01: 已验收 |
| V032 | TacoTakumi/VoiceManager · 有界队列与溢出丢弃 | 待验证 | E01 | E01: 已验收 |
| V033 | CoreWorxLab/local-livekit-plugins · Piper ChunkedStream 封装分块音频 | 部分 | T03 | T03: 待实测 |
| V034 | CoreWorxLab/local-livekit-plugins · faster-whisper STT 适配器 | 已具备 | R01 | R01: 已验收 |
| V035 | FunAudioLLM/CosyVoice · 零样本参考音频与流式模型输出 | 缺失 | T02 | T02: 待实测 |
| V036 | FunAudioLLM/CosyVoice · 跨语言与自然语言指令控制 | 缺失 | T02 | T02: 待实测 |
| V037 | FunAudioLLM/CosyVoice · 音频生成器按 stream 参数返回 | 部分 | T01 | T01: 待实测 |
| V038 | FunAudioLLM/CosyVoice · CosyVoice2/3 持续流式文本输入 | 缺失 | T01 | T01: 待实测 |
| V039 | FunAudioLLM/SenseVoice · ONNX 语音识别推理封装 | 已具备 | R01 | R01: 已验收 |
| V040 | FunAudioLLM/SenseVoice · 音频数据加载与特征提取 | 部分 | S03 | S03: 待实测 |
| V041 | ggml-org/llama.cpp · 本地模型服务上下文 | 非同类 | D02 | D02: 非同类候选 |
| V042 | hexgrad/kokoro · 返回文本、音素和音频分段 | 部分 | T03 | T03: 待实测 |
| V043 | hexgrad/kokoro · 文本管线按块迭代输出 | 部分 | T03 | T03: 待实测 |
| V044 | k2-fsa/sherpa-onnx · 在线识别端点检测与 token 时间戳 | 缺失 | S01, I01, E02 | S01: 待实测；I01: 待实测；E02: 待实测 |
| V045 | k2-fsa/sherpa-onnx · 离线 TTS 生成回调 | 已具备 | R01 | R01: 已验收 |
| V046 | kyutai-labs/moshi · 有状态语言模型逐步音频 token 生成 | 缺失 | D01 | D01: 条件受限 |
| V047 | kyutai-labs/moshi · 模型 TTS 生成 | 非同类 | D01 | D01: 条件受限 |
| V048 | modelscope/FunASR · Paraformer 缓存分块及最终块标记 | 缺失 | S01 | S01: 待实测 |
| V049 | modelscope/FunASR · 统一模型生成接口 | 部分 | S03 | S03: 待实测 |
| V050 | ollama/ollama · 本地聊天与生成服务 | 非同类 | D02 | D02: 非同类候选 |
| V051 | openai/whisper · 词级时间戳对齐 | 缺失 | M02 | M02: 待实测 |
| V052 | openai/whisper · 窗口式多语言转写 | 部分 | S03 | S03: 待实测 |
| V053 | OpenBMB/VoxCPM · 模型生成步骤输出音频块 | 部分 | T02 | T02: 待实测 |
| V054 | OpenBMB/VoxCPM · 参考提示缓存条件生成 | 缺失 | T02 | T02: 待实测 |
| V055 | QwenLM/Qwen3-ASR · 状态化 PCM 分块识别 | 缺失 | S01, I01, E02 | S01: 待实测；I01: 待实测；E02: 待实测 |
| V056 | QwenLM/Qwen3-ASR · 可选强制对齐 | 缺失 | M02 | M02: 待实测 |
| V057 | QwenLM/Qwen3-Omni · 音频输入多模态推理示例 | 缺失 | D01 | D01: 条件受限 |
| V058 | QwenLM/Qwen3-Omni · 自动设备映射与多模态处理 | 待验证 | D01 | D01: 条件受限 |
| V059 | QwenLM/Qwen3-TTS · 参考音频克隆 | 缺失 | T02 | T02: 待实测 |
| V060 | QwenLM/Qwen3-TTS · 文本描述设计音色 | 缺失 | T02 | T02: 待实测 |
| V061 | QwenLM/Qwen3-TTS · 非流式文本接口的模拟设置 | 非同类 | D02 | D02: 非同类候选 |
| V062 | QwenLM/Qwen3.5 · 模型系列介绍与规模选择 | 非同类 | D02 | D02: 非同类候选 |
| V063 | snakers4/silero-vad · 状态化流式 VAD | 已具备 | R01 | R01: 已验收 |
| V064 | snakers4/silero-vad · 离线语音区间时间戳 | 部分 | S03, E02 | S03: 待实测；E02: 待实测 |
| V065 | SYSTRAN/faster-whisper · 分段 Whisper 转写和词级时间戳 | 部分 | S03, E02 | S03: 待实测；E02: 待实测 |
| V066 | SYSTRAN/faster-whisper · 转写时语音活动过滤 | 部分 | S03 | S03: 待实测 |
| V067 | THUDM/GLM-4-Voice · 语言模型音频 token 流输出 | 缺失 | D01 | D01: 条件受限 |
| V068 | THUDM/GLM-4-Voice · 语音 flow 流推理 | 部分 | D01 | D01: 条件受限 |
| V069 | vllm-project/vllm · 异步模型请求与增量生成 | 非同类 | D02 | D02: 非同类候选 |
| V070 | vllm-project/vllm-omni · 双工客户端发送 PCM 流 | 部分 | D01 | D01: 条件受限 |
| V071 | vllm-project/vllm-omni · 异步多模态生成 | 缺失 | D01 | D01: 条件受限 |
| V072 | wwbin2017/bailing · FunASR 识别后端接口 | 部分 | S01 | S01: 待实测 |
| V073 | wwbin2017/bailing · Kokoro 合成后端 | 缺失 | T03 | T03: 待实测 |
| V074 | electron/electron · 桌面媒体权限策略 | 非同类 | D02 | D02: 非同类候选 |
| V075 | electron/electron · 来源权限检查 | 非同类 | D02 | D02: 非同类候选 |
| V076 | lipku/LiveTalking · 音频视频时钟 | 非同类 | D02 | D02: 非同类候选 |
| V077 | lipku/LiveTalking · 音频特征队列 | 非同类 | D02 | D02: 非同类候选 |
| V078 | moeru-ai/airi · 元音音频分析 | 已具备 | R01, M01 | R01: 已验收；M01: 已验收 |
| V079 | moeru-ai/airi · 流式语音调度 | 部分 | T01 | T01: 待实测 |
| V080 | moeru-ai/airi · 表情队列 | 部分 | M04 | M04: 已验收 |
| V081 | Open-LLM-VTuber/Open-LLM-VTuber · 中断已听文本 | 部分 | P02 | P02: 待实测 |
| V082 | Open-LLM-VTuber/Open-LLM-VTuber · 客户端中断消息 | 部分 | P01, P02 | P01: 已验收；P02: 待实测 |
| V083 | Open-LLM-VTuber/Open-LLM-VTuber-Web · 音频任务队列 | 已具备 | R01 | R01: 已验收 |
| V084 | Open-LLM-VTuber/Open-LLM-VTuber-Web · 音频与口型停止 | 已具备 | R01 | R01: 已验收 |
| V085 | Open-LLM-VTuber/Open-LLM-VTuber-Web · 表情映射 | 部分 | M04 | M04: 已验收 |
| V086 | Open-LLM-VTuber/Open-LLM-VTuber-Web · 播放完成回执及中断文本 | 部分 | P01 | P01: 已验收 |
| V087 | OpenBMB/MiniCPM-o · 流式输入与生成 | 部分 | D01 | D01: 条件受限 |
| V088 | OpenBMB/MiniCPM-o · 说话时钟 | 待验证 | D01 | D01: 条件受限 |
| V089 | OpenBMB/MiniCPM-o · 4.5 全双工声明 | 待验证 | D01 | D01: 条件受限 |
| V090 | suzuran0y/Live2D-LLM-Chat · WAV 输入校验 | 已具备 | R01 | R01: 已验收 |
| V091 | suzuran0y/Live2D-LLM-Chat · ASR worker 分离 | 已具备 | R01 | R01: 已验收 |
| V092 | suzuran0y/Live2D-LLM-Chat · 结构化 worker 帧 | 部分 | R01 | R01: 已验收 |
| V093 | TMElyralab/MuseTalk · 音频特征与帧切片 | 非同类 | D02 | D02: 非同类候选 |
| V094 | TMElyralab/MuseTalk · 视频帧输出 | 非同类 | D02 | D02: 非同类候选 |
| V095 | mrxz/wlipsync · 播放音频的 MFCC 分类与时间平滑 | 已具备 | R01, M01 | R01: 已验收；M01: 已验收 |
| V096 | mrxz/wlipsync · 声音专属校准模板 | 已具备 | R01, M01 | R01: 已验收；M01: 已验收 |
| V097 | mrxz/wlipsync · 预计算二进制 profile | 缺失 | M03 | M03: 已验收 |
| V098 | Live2D/CubismWebMotionSyncComponents · 模型专属音频→形状映射和后处理配置 | 部分 | M03 | M03: 已验收 |
| V099 | Live2D/CubismWebMotionSyncComponents · 官方CRI分析、混合和平滑接口 | 待验证 | M05 | M05: 条件受限 |

## 审计补充发现（逐条保留）

| 项目 | 补充发现 | 对应任务 |
|---|---|---|
| akkoaya/EvatarFramework | 需要时才扩展多用户索引；用户当前需求是只回应本人 | I01, R01, E01 |
| akkoaya/EvatarFramework | 反复网络抖动后的在途音频及播放状态恢复仍待实测 | I01, R01, E01 |
| aryeo0908/whisper-loop | 端到端播放确认尚未具备 | R01 |
| Code-Amadeus/Amadeus | 真实环境自回声误打断效果未测 | S02, P02, R01 |
| datascale-ai/opentalking | 多进程会话队列非当前单机场景必要条件 | D02, S02 |
| FahadiF/Edge-Voice-Assistant | 设备参考同步 AEC | A01, A02, S02, E01 |
| FahadiF/Edge-Voice-Assistant | 旧 ASR 结果跨轮隔离的系统级实测 | A01, A02, S02, E01 |
| huggingface/speech-to-speech | 同步设备参考 AEC | A01, A02, M02, I02 |
| huggingface/speech-to-speech | 多说话人在线分离 | A01, A02, M02, I02 |
| huggingface/speech-to-speech | 经中文验证的音素时间口型事件 | A01, A02, M02, I02 |
| liampetti/fulloch | 断线后会话恢复验收 | R01, A02, E01 |
| liampetti/fulloch | 真实设备 AEC 测量 | R01, A02, E01 |
| livekit/agents | 已播放文本确认 | S02, P02, P01 |
| livekit/agents | 经验证的误打断暂停恢复 | S02, P02, P01 |
| pipecat-ai/pipecat | 播放 ACK 驱动的已听历史 | R01, S02, P02 |
| pipecat-ai/pipecat | 真实误打断恢复验收 | R01, S02, P02 |
| pipecat-ai/pipecat-client-web | 实际播放进度与文本确认 | R01 |
| pipecat-ai/pipecat-client-web-transports | 断网恢复及会话一致性验证 | R01, E01 |
| pipecat-ai/smart-turn | 中文轮次准确率与时延基准 | R01, E02 |
| TacoTakumi/HermesConsole | 目标设备的真实 AEC 及双讲门槛 | A02, E02 |
| TacoTakumi/VoiceManager | 真增量 STT | S01, I01, E02, P01, E01 |
| TacoTakumi/VoiceManager | 播放边界确认 | S01, I01, E02, P01, E01 |
| TacoTakumi/VoiceManager | 队列压力指标与恢复策略 | S01, I01, E02, P01, E01 |
| FunAudioLLM/CosyVoice | 参考音色克隆 | T02, T01 |
| FunAudioLLM/CosyVoice | 风格指令 | T02, T01 |
| FunAudioLLM/CosyVoice | 同一会话增量文本输入，需CosyVoice2/3且非vLLM路径 | T02, T01 |
| ggml-org/llama.cpp | 可选本地对话模型 | D02 |
| hexgrad/kokoro | 可用的音素序列 | T03 |
| k2-fsa/sherpa-onnx | 可靠的在线部分识别和模型端点 | S01, I01, E02, R01 |
| kyutai-labs/moshi | 端到端语音 token 对话 | D01 |
| modelscope/FunASR | 真实流式部分识别 | S01, S03 |
| ollama/ollama | 本地 LLM 备选 | D02 |
| openai/whisper | 可验证的识别时间对齐 | M02, S03 |
| OpenBMB/VoxCPM | 音色克隆与提示缓存 | T02 |
| QwenLM/Qwen3-ASR | 部分转写 | S01, I01, E02, M02 |
| QwenLM/Qwen3-ASR | 转写与音频强制对齐 | S01, I01, E02, M02 |
| QwenLM/Qwen3-Omni | 原生多模态音频理解 | D01 |
| QwenLM/Qwen3-TTS | 语音克隆 | T02, D02 |
| QwenLM/Qwen3-TTS | 文字音色设计 | T02, D02 |
| QwenLM/Qwen3.5 | 可选本地对话模型 | D02 |
| SYSTRAN/faster-whisper | 词级时间戳输出 | S03, E02 |
| THUDM/GLM-4-Voice | 端到端语音 token 生成 | D01 |
| vllm-project/vllm-omni | 统一多模态双工模型 | D01 |
| wwbin2017/bailing | 可选 Kokoro 音色 | S01, T03 |
| moeru-ai/airi | 流式语音调度 | R01, M01, T01, M04 |
| moeru-ai/airi | 表情队列 | R01, M01, T01, M04 |
| Open-LLM-VTuber/Open-LLM-VTuber | 中断已听文本 | P02, P01 |
| Open-LLM-VTuber/Open-LLM-VTuber | 客户端中断消息 | P02, P01 |
| Open-LLM-VTuber/Open-LLM-VTuber-Web | 表情映射 | R01, M04, P01 |
| Open-LLM-VTuber/Open-LLM-VTuber-Web | 播放完成回执及中断文本 | R01, M04, P01 |
| OpenBMB/MiniCPM-o | 流式输入与生成 | D01 |
| OpenBMB/MiniCPM-o | 说话时钟 | D01 |
| OpenBMB/MiniCPM-o | 4.5 全双工声明 | D01 |
| suzuran0y/Live2D-LLM-Chat | 结构化 worker 帧 | R01 |
| mrxz/wlipsync | 上游导出特征写入范围风险 | R01, M01, M03 |
| mrxz/wlipsync | 更可靠的中文声线校准与独立发音评测 | R01, M01, M03 |
| mrxz/wlipsync | 可选预计算profile | R01, M01, M03 |
| Live2D/CubismWebMotionSyncComponents | 角色映射配置化 | M03, M05 |
| Live2D/CubismWebMotionSyncComponents | 官方引擎的中文/延迟A/B仍未完成 | M03, M05 |

## 复现与更新

运行 `.venv\Scripts\python.exe scripts/build_voice_completion.py` 校验 46 仓库、99 项能力和全部补充发现无遗漏，再生成本表及可导入表格的 UTF-8 CSV。JSON 是状态唯一来源；验收更新必须填写证据和未解决条件。
