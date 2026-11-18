"""Validate and render the current, per-capability review of all source archives.

Default input is the tracked JSON. --import-agents is for the integrator and
requires the three ignored agent reports from the corresponding review.
No inference, network calls, model changes or application settings changes.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / 'docs/CURRENT_VOICE_GAPS.json'
STATES = {'缺失', '部分', '已具备', '非同类', '待验证'}


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def evidence(path, line, finding):
    return dict(path=path, line=line, finding=finding)


def lip_projects():
    return [dict(repo='mrxz/wlipsync', capabilities=[
        dict(mechanism='播放音频的 MFCC 分类与时间平滑', comparison='已具备', benefit='在同等音量下仍可产生不同元音嘴形，且不依赖文本猜测。', adoption_cost='当前已直接依赖1.3.1；其 worklet 发送胜出类别，前端再平滑成权重，不是原始分类置信度或完整音素概率。', evidence=[evidence('src/main.c', 123, '从实际音频提取特征并评分分类'), evidence('www/audio-processor.js', 106, '向主线程发送胜出类别和时间戳'), evidence('www/audio-node.ts', 85, '将胜出类别映射为目标并平滑')]),
        dict(mechanism='声音专属校准模板', comparison='已具备', benefit='模板可随声线更换，而非将某个说话人的样例当作通用中文模型。', adoption_cost='本项目已有本地 VITS 模板和选择；E/O/U仍混淆。上游官方不含创建器，建议 Unity uLipSync 校准，本项目离线工具属于额外适配。', evidence=[evidence('README.md', 54, '校准说明与外部 Unity 创建流程'), evidence('www/types.ts', 5, '每类可存 MFCC 校准数据')]),
        dict(mechanism='预计算二进制 profile', comparison='缺失', benefit='减少原始模板传输体积和初始化预计算。', adoption_cost='当前两个模板作为JSON进入前端包；这是体积/初始化优化，不能提高发音分类准确率，优先级低于修复特征和校准。', evidence=[evidence('www/parse.ts', 10, '解析预计算的二进制校准文件'), evidence('tools/json2bin.js', 17, '使用同一上游WASM转换profile')]),
    ], missing_top=['上游导出特征写入范围风险', '更可靠的中文声线校准与独立发音评测', '可选预计算profile'], corrections=['已具备声学口型，不再是默认音量开合；当前平滑权重不等于完整类别概率。'], risks=[dict(title='六类配置只更新六个MFCC槽位', evidence=[evidence('src/main.c', 180, '写入mfccOut的循环上界为类别数量profile.mfccCount'), evidence('src/score/calc_cosine_similarity_scores.c', 16, '评分遍历MFCC_NUM个系数，常量为12')], finding='固定源码存在类别数量与系数数量混用；独立实例化已安装1.3.1 WASM，以六类配置和12槽哨兵运行execute后，前六槽更新、后六槽保留哨兵。当前本地模板同样为六类，应优先核查。', limit='这证明了写入范围问题，不能证明它是所有E/O/U混淆的唯一原因；本轮未修补依赖、未改生产内存。', reproduction='node scripts/probe_wlipsync_mfcc.cjs；固定诊断快照 docs/WLIPSYNC_MFCC_PROBE.json')]),
        dict(repo='Live2D/CubismWebMotionSyncComponents', capabilities=[
            dict(mechanism='模型专属音频→形状映射和后处理配置', comparison='部分', benefit='以motionsync3配置表达多个音频类别到多个Cubism参数的权重、缩放、阻尼和平滑，便于不同角色独立调校。', adoption_cost='我们已有五个嘴参数映射及范围检查，但映射公式写在adapter.ts；当前皮肤没有motionsync3，需制作并验证映射。', evidence=[evidence('Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json', 17, '配置嘴参数及范围和平滑'), evidence('Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json', 117, '音频类别与模型形状映射'), evidence('Framework/src/cubismmotionsyncdata.ts', 140, '按模型配置建立引擎映射列表')]),
            dict(mechanism='官方CRI分析、混合和平滑接口', comparison='待验证', benefit='提供专门的音频分析与形状后处理接口，可作为替代声学分析器进行对照。', adoption_cost='仓库不含Core；需另取Core/SDK、接受独立许可并适配模型。仅凭接口不能断言中文口型比wLipSync准确或延迟更低。', evidence=[evidence('Framework/src/cubismmotionsyncprocessorcri.ts', 25, 'Analyze接收blendRatio/smoothing/audioLevelEffectRatio'), evidence('README.md', 33, 'Core不在本仓库'), evidence('LICENSE.md', 1, '组件、SDK和Core的独立许可条件')]),
        ], missing_top=['角色映射配置化', '官方引擎的中文/延迟A/B仍未完成'], corrections=['并非完整MIT开源依赖；源码组件与闭源Core/SDK/素材许可分开，不能把接口存在当作准确度优势。']),
    ]


def baseline():
    return [
        dict(area='识别', current='连续PCM输入，但LocalSpeechSTT收完整VAD片段后HTTP请求SenseVoice，仅产生finalized=True；尚无实时部分转写。', evidence=[evidence('speech/pipecat_services.py', 47, '继承SegmentedSTTService'), evidence('speech/pipecat_services.py', 77, '整段PCM封装WAV并识别')]),
        dict(area='轮次与打断', current='已有Silero、默认Local Smart Turn结束判断、播放时先duck；硬打断只由确认最终转写触发，附和为有限中文规则。', evidence=[evidence('server/pipecat_voice.py', 80, '配置VAD和ChineseTurnStartStrategy'), evidence('speech/pipecat_turns.py', 9, '有限附和词表'), evidence('speech/pipecat_turns.py', 36, '收到TranscriptionFrame才启动新轮次')]),
        dict(area='语音输出', current='按句文本提交VITS，通过原生callback提前发送PCM，有界准入/连接复用/取消持锁；不支持同一合成会话持续append LLM token。', evidence=[evidence('speech/pipecat_services.py', 134, '每次run_tts提交完整text'), evidence('speech/server.py', 474, '本地增量PCM端点')]),
        dict(area='播放与历史', current='官方PCM播放器、手动停止、清队与口型重置已具备；服务器保存框架输出历史，没有应用级播放进度/完成ACK。', evidence=[evidence('web/src/voice.ts', 182, '停止官方播放器并发voice.stop'), evidence('server/pipecat_voice.py', 120, '助手轮次停止后保存框架文字'), evidence('docs/PROTOCOL.md', 37, '明确历史不等于已听位置')]),
        dict(area='回声与降噪', current='浏览器请求AEC/NS/AGC，并展示实际报告；生产后端无同步扬声器参考AEC。独立APM实验及合成测试不能证明外放双讲效果。', evidence=[evidence('web/src/voice.ts', 135, '读取浏览器音轨设置'), evidence('server/pipecat_voice.py', 91, '生产处理器链没有原生AEC模块')]),
        dict(area='本人声音', current='CPU ERes2Net/Silero、2—5样本模板、质量门和相似度筛选；整段至少2秒有效人声后核对，不是在线多说话人分离/目标声音提取。', evidence=[evidence('speech/speaker.py', 79, '整段VAD提取并计算embedding'), evidence('speech/speaker.py', 131, '对模板作最终相似度判断')]),
        dict(area='口型与表情', current='wLipSync/MFCC、AIRI平滑、本地声线模板、多嘴参数已具备；没有音素时间区间，E/O/U混淆；表情仍按TTS文本关键词近似。', evidence=[evidence('web/src/voice.ts', 47, '加载声学profile与WASM'), evidence('web/src/avatar/lipsync/adapter.ts', 10, '固定多参数映射公式'), evidence('web/src/voice.ts', 162, '按TTS文本关键词设表情')]),
        dict(area='工程与验收', current='原生阶段metrics、受控回归和一次真实DeepSeek链路已具备；无持续真人P50/P95、真实外放AEC指标、长时噪声/多人语音验收。语音实际CPU。', evidence=[evidence('server/pipecat_voice.py', 97, '原生metrics开启'), evidence('docs/VALIDATION.md', 1, '已有测量和未验收边界')]),
    ]


PRIORITIES = [
    ('P0', '增量识别和更早的可靠打断', 'sherpa-onnx / FunASR / Qwen3-ASR / VoiceManager', '在说话过程中获得部分文字，再结合本人声音门和打断意图区分。Smart Turn已经接入，继续等final ASR不会获得首词打断。', '先对中文短指令、附和、数字和噪声做质量/延迟对照；声纹当前要求2秒，不能直接让陌生人的部分转写启动回答。'),
    ('P0', '核查并修复现有口型依赖与校准质量', 'wLipSync / HF STV / MotionSync', '已发现六类配置MFCC写入范围问题；当前嘴形会变，但不等于发音分类正确。', '先处理依赖问题并重新收集模板、独立验证；再比较中文音素模型或官方引擎，不能盲搬默认英文模型。'),
    ('P0', '真实外放AEC与双讲验收', 'HF speech-to-speech / Edge-Voice-Assistant / HermesConsole', '需要正确播放参考和ADC/DAC时钟，且证明角色说话时用户人声仍被保留。', '浏览器内建AEC与原生设备APM分开评测；不能在没有正确参考时叠加第二层AEC。'),
    ('P1', '播放确认、已听历史和误打断恢复', 'LiveKit / Open-LLM-VTuber Web / VoiceManager', '把实际播放区间回传服务端，才有条件截断上下文并决定续播还是新回答。', '上游完成回执/整段展示文本也不等于逐字已听。Pipecat empty-user-turn重新提示LLM，不是原音续播。'),
    ('P1', '韵律、音色与文本/音频双向流', 'CosyVoice / VoxCPM / Qwen3-TTS / AIRI', '当前VITS能早出PCM，仍没有参考音色克隆、自然语言风格控制、跨句统一韵律或持续文本输入会话。', '中文音质、首音、长句停顿、资源占用和权重许可要分别实测；模型API的stream参数不自动代表双向文本流。'),
    ('P1', '声音身份与复杂声场', 'HF diarization / Evatar / sherpa-onnx', '当前能做整段单人模板验证，尚不能持续跟踪多人、分离同时讲话或只提取用户声音。', 'diarization只标谁在何时说话，不等于认出已注册的你，也不等于消除重叠语音；短命令误拒绝和重放需另评估。'),
    ('P1', '持续观测、压力和真人验收', 'Smart Turn benchmarks / Pipecat metrics / HermesConsole / VoiceManager', '原生阶段指标已有，但欠缺用户可感知的整链时钟、队列水位、欠载/溢出、误打断率及长时统计。', '目前0.124秒首PCM和2.51秒云端首次嘴动分别是小样本组件/单次链路，不能当P50/P95或物理首音。'),
    ('P2', '端到端语音模型与规模化部署', 'Moshi / MiniCPM-o / GLM-4-Voice / Qwen3-Omni / vLLM-Omni / OpenTalking', '可以探索保留语气的直接语音理解、模型层双工、主动发言，或多会话服务。', '这类功能可能需要整体架构和硬件改变；不一定适合当前Intel Windows单人Live2D产品，不能先当确定收益。'),
]


def normalize(project, old, inv):
    project['commit'] = inv[project['repo']]['commit']
    project['license'] = project.get('license', old[project['repo']]['license'])
    for cap in project['capabilities']:
        cap['mechanism'] = cap.pop('name', cap.get('mechanism'))
        if isinstance(cap['evidence'], dict):
            cap['evidence'] = [cap['evidence']]
    for key in ['missing_top', 'corrections']:
        value = project.get(key, [])
        project[key] = value if isinstance(value, list) else [value]
    return project


def import_reports(inv):
    old = {x['repo']: x for x in load('docs/OPEN_SOURCE_LANGUAGE_REVIEW.json')['projects']}
    projects = []
    for name in ['.worktrees/backend/artifacts/current-gap-backend.json', 'artifacts/current-gap-speech.json', '.worktrees/frontend/artifacts/current-gap-frontend.json']:
        report = load(name)
        projects.extend(report if isinstance(report, list) else report['projects'])
    projects.extend(lip_projects())
    projects = [normalize(p, old, inv) for p in projects]
    # The integrator checks claimed advantages against the present implementation.
    by_repo = {p['repo']: p for p in projects}
    by_repo['FunAudioLLM/CosyVoice']['capabilities'].append(dict(
        mechanism='CosyVoice2/3 持续流式文本输入', comparison='缺失',
        benefit='同一合成会话可持续接收文本生成器，交错生成语音token，超出当前“整句text请求→callback PCM”的能力。',
        adoption_cost='源码明确仅CosyVoice2/3且该路径不支持vLLM；需适配生成器、取消、缓存、中文音质和本机资源，不能保证在当前CPU更快。',
        evidence=[evidence('cosyvoice/cli/frontend.py', 79, '输入为Generator时返回增量token生成器'), evidence('cosyvoice/cli/model.py', 104, 'Generator路由到inference_bistream并检查版本与vLLM限制'), evidence('cosyvoice/llm/llm.py', 552, '实现接收Generator的inference_bistream')]))
    by_repo['FunAudioLLM/CosyVoice']['missing_top'].append('同一会话增量文本输入，需CosyVoice2/3且非vLLM路径')
    hf = by_repo['huggingface/speech-to-speech']
    for cap in hf['capabilities']:
        if cap['mechanism'] == '音频时间轴口型事件':
            cap['evidence'].extend([evidence('src/speech_to_speech/STV/w2v_stv_handler.py', 38, 'MIN_AUDIO_LENGTH为0.5秒'), evidence('src/speech_to_speech/STV/w2v_stv_handler.py', 128, 'flush先推断口型再发送缓冲音频'), evidence('src/speech_to_speech/arguments_classes/w2v_stv_arguments.py', 11, '默认音素检查点是英文')])
            cap['adoption_cost'] += ' 此实现缓冲约0.5秒再推断，flush在音频转发前执行，可能引入额外等待；精细口型与首音延迟需权衡。'
    for cap in by_repo['livekit/agents']['capabilities']:
        if cap['mechanism'] == '自适应打断和误打断恢复':
            cap['adoption_cost'] += ' 恢复路径还要求resume_false_interruption配置、timeout及输出audio.can_pause，不能假设所有输出后端可续播。'
    evatar = by_repo['akkoaya/EvatarFramework']
    for cap in evatar['capabilities']:
        if cap['mechanism'] == '原生客户端重连与退避配置':
            cap['comparison'] = '已具备'
            cap['adoption_cost'] = '当前web/src/reconnect.ts已有1—30秒指数退避，同会话重连已有受控验收；上游原生设备配置不能证明在途音频/时钟完整恢复。'
    evatar['missing_top'] = ['需要时才扩展多用户索引；用户当前需求是只回应本人', '反复网络抖动后的在途音频及播放状态恢复仍待实测']
    for repo, mechanism in [('aryeo0908/whisper-loop', '独立轮次任务取消与通知'), ('liampetti/fulloch', '浏览器 AEC 请求及播放取消')]:
        for cap in by_repo[repo]['capabilities']:
            if cap['mechanism'] == mechanism:
                cap['comparison'] = '已具备'
                cap['adoption_cost'] += ' 当前已经有同类机制，不把其存在计作当前缺失；实际鲁棒性仍须测试。'
    return dict(date='2026-11-06', baseline_commit='5c5ce43', scope='18 explicit research GitHub repository URLs plus named projects/direct-support dependencies and two added lip-sync sources: 46 pinned source archives. Relevant implementation/document inspection; not uniform application benchmarking.', states={
        '缺失': '上游有对应接口/实现，当前生产链未接入；适用性与效果仍受模型、后端、硬件和许可证限制。',
        '部分': '当前有同类基础能力，但缺少所列细节，或上游只提供不同层级的机制；不等于完全落后。',
        '已具备': '当前已直接复用或有同等用途机制，不计为新增缺口。',
        '非同类': '用于另一产品/部署层；不能直接称作当前语音体验优势。',
        '待验证': '源码/文档提供候选或配置，但实现完整性、对应后端或本机效果尚不够确定。',
    }, current_baseline=baseline(), priorities=[dict(priority=p, gap=g, sources=s, reason=r, prerequisite=c) for p,g,s,r,c in PRIORITIES], projects=projects)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-agents', action='store_true')
    args = parser.parse_args()
    inventory = {x['repo']: x for x in load('docs/UPSTREAM_SOURCES.json')['repositories']}
    data = import_reports(inventory) if args.import_agents else json.loads(JSON_PATH.read_text(encoding='utf-8'))
    projects = data['projects']
    assert len(projects) == len({p['repo'] for p in projects}) == len(inventory) == 46
    assert {p['repo'] for p in projects} == set(inventory)
    cites = 0

    def validate_file(root, item):
        path = root / item['path']
        assert path.is_file(), str(path)
        assert 0 < item['line'] <= len(path.read_text(encoding='utf-8', errors='replace').splitlines()), str(path)

    for item in data['current_baseline']:
        for ev in item['evidence']:
            validate_file(ROOT, ev)
    for project in projects:
        assert project['commit'] == inventory[project['repo']]['commit']
        source = ROOT / 'artifacts/upstream-archives' / project['repo'].replace('/', '__')
        for cap in project['capabilities']:
            assert cap['comparison'] in STATES
            assert cap['mechanism'] and cap['benefit'] and cap['adoption_cost'] and cap['evidence']
            for ev in cap['evidence']:
                validate_file(source, ev)
                cites += 1
        for risk in project.get('risks', []):
            for ev in risk['evidence']:
                validate_file(source, ev)
                cites += 1
    if args.import_agents:
        JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = Counter(c['comparison'] for p in projects for c in p['capabilities'])
    lines = ['# 当前语音系统与全部46个上游的差距审查', '',
        f'日期：{data["date"]}。当前生产代码基线：`{data["baseline_commit"]}`。逐仓核查语音相关实现和文档，共{len(projects)}个仓库、{sum(counts.values())}项能力、{cites}处上游源码/文档引用。', '',
        '结论：当前已经具备可运行的分离式语音链路、框架取消、增量PCM、声纹筛选和声学元音口型。与相关上游相比，主要差距是增量识别与更早可靠打断、同步播放参考AEC、播放确认及恢复、音色韵律控制、可靠中文音素时间口型，以及真实场景长期验收。部分上游功能已经被我们采用；另一些属于视频头像、桌面壳或服务器部署，不应全部算成我们落后。', '',
        '范围逐一对齐 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)：研究附件中的18个直接GitHub仓库地址，加上按名称补齐的项目及直接支持库，以及官方MotionSync/wLipSync。重新提取比对后46项无缺失、无重复。本次使用本地固定归档，不声称是远端最新HEAD，不下载/运行全部模型。上游实现存在不等于本机中文更准、更快或NPU可用。', '',
        '完整机器可读审查：[CURRENT_VOICE_GAPS.json](CURRENT_VOICE_GAPS.json)。此前移植记录仍见 [OPEN_SOURCE_LANGUAGE_REVIEW.md](OPEN_SOURCE_LANGUAGE_REVIEW.md)，本文件按当前实现重新判定差距。', '',
        '## 当前基线', '', '| 环节 | 当前真实实现 |', '|---|---|']
    for item in data['current_baseline']:
        refs = '；'.join(f'[{e["path"]}:{e["line"]}](../{e["path"]}#L{e["line"]})' for e in item['evidence'])
        lines.append(f'| {item["area"]} | {item["current"]} 证据：{refs} |')
    lines += ['', '最近实测是历史证据：短/长句各3次CPU HTTP首PCM中位约0.124/0.125秒；一次真实DeepSeek文本输入至首次嘴动约2.51秒；约1.91秒合成插话至框架interruption约2.81秒。它们不是本轮新性能测试，不代表P50/P95、真实麦克风/扬声器时延或自然度评分，原始边界见 [VALIDATION.md](VALIDATION.md)。', '', '## 优先差距', '', '| 优先级 | 差距及主要参考 | 为什么仍有差距 / 采用前提 |', '|---|---|']
    for row in data['priorities']:
        lines.append(f'| {row["priority"]} | **{row["gap"]}**；{row["sources"]} | {row["reason"]} {row["prerequisite"]} |')
    lines += ['', '## 判定含义与覆盖统计', '']
    for state, meaning in data['states'].items():
        lines.append(f'- **{state}**（{counts[state]}项）：{meaning}')
    lines += ['', '这些数量是按本次列举的能力项统计，不是统一打分；同一仓库可以同时有已具备、部分和缺失项。未发现额外优势时明确写出，不为凑差距而把已有能力重新列作缺失。', '', '## 46仓库总表', '', '| 项目 | 源码中值得借鉴的机制及当前判定 |', '|---|---|']
    for project in sorted(projects, key=lambda p:p['repo'].lower()):
        text = '；'.join(f'{c["mechanism"]}：**{c["comparison"]}**' for c in project['capabilities'])
        lines.append(f'| {project["repo"]} | {text} |')
    lines += ['', '## 逐项目依据、价值与成本', '']
    for project in sorted(projects, key=lambda p:p['repo'].lower()):
        repo, commit = project['repo'], project['commit']
        lines += [f'### {repo}', '', f'固定源码：[{commit[:12]}](https://github.com/{repo}/tree/{commit})。源码许可记录：{project["license"]}；模型、素材、SDK/Core和服务许可另核。', '']
        if project.get('current_baseline'):
            lines += ['当前对照：' + project['current_baseline'], '']
        for cap in project['capabilities']:
            lines += [f'**{cap["mechanism"]} — {cap["comparison"]}**', '', '上游价值：' + cap['benefit'], '', '当前差距 / 采用成本：' + cap['adoption_cost'], '']
            for ev in cap['evidence']:
                url = f'https://github.com/{repo}/blob/{commit}/{ev["path"]}#L{ev["line"]}'
                lines.append(f'- [{ev["path"]}:{ev["line"]}]({url})：{ev["finding"]}')
            lines.append('')
        if project.get('missing_top'):
            lines += ['重点核对：' + '；'.join(project['missing_top']) + '。', '']
        for risk in project.get('risks', []):
            lines += [f'**依赖风险：{risk["title"]}**', '', risk['finding'], '', risk['limit'], '', '复现：' + risk['reproduction'], '']
            for ev in risk['evidence']:
                lines.append(f'- [{ev["path"]}:{ev["line"]}](https://github.com/{repo}/blob/{commit}/{ev["path"]}#L{ev["line"]})：{ev["finding"]}')
            lines.append('')
        if project.get('corrections'):
            lines += ['校正 / 限制：' + '；'.join(project['corrections']), '']
    lines += ['## 不能从此次审查推出的结论', '',
        '- 无同机统一A/B，不能认定某个完整项目“语音逻辑最好”或一定比我们更快。',
        '- 连续PCM采集、分块音频输出、模型接收流式文本、端到端模型全双工是不同能力，不能混称“真流式”。',
        '- 浏览器报告AEC开启不等于外放效果通过；声纹筛选不等于分离重叠说话或去掉噪声。',
        '- 口型有声学分类不等于中文每字精确；带时间的英文viseme事件也不自动适用于中文。',
        '- NPU设备存在、支持某后端或模型能编译都不等于本项目NPU识别质量/延迟合格。',
        '- 本次只读审查和报告，不将候选方案描述为已移植的新功能。', '']
    (ROOT / 'docs/CURRENT_VOICE_GAPS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(projects=len(projects), capabilities=sum(counts.values()), citations=cites, states=counts), ensure_ascii=False))


if __name__ == '__main__':
    main()
