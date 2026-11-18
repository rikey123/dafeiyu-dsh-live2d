"""Render and validate the tracked source review against downloaded archives.

Without --from-agent-reports, verifies docs/OPEN_SOURCE_LANGUAGE_REVIEW.json
and renders Markdown. Agent report import is an integration-only operation.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def build():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-agent-reports', action='store_true')
    args = parser.parse_args()
    inventory = {item['repo']: item for item in load('docs/UPSTREAM_SOURCES.json')['repositories']}
    if args.from_agent_reports:
        projects = []
        for path in ['artifacts/review-speech.json', '.worktrees/backend/artifacts/review-backend-zh.json', '.worktrees/frontend/artifacts/review-frontend.json']:
            report = load(path)
            projects.extend(report if isinstance(report, list) else report['projects'])
        projects.extend([
            dict(repo='Live2D/CubismWebMotionSyncComponents', evidence=[dict(path='README.md', line=33, finding='MotionSync Core 不包含在源码仓库，需另取发行包'), dict(path='Framework/src/cubismmotionsyncprocessorcri.ts', line=25, finding='CRI Analyze 接收采样、平滑和混合参数'), dict(path='Samples/Resources/Kei_vowels/Kei_vowels.motionsync3.json', line=1, finding='元音映射至多个模型参数的配置样例')], advantage=['官方 CRI 声学分析、混合与平滑', '模型专属多参数口型映射'], gap=['当前皮肤无 motionsync3 配置，不能直接套用样例', 'Core 与 SDK 独立许可、发行方式，仓库不是完整可运行依赖'], decision='作为高阶候选，当前采用 MIT wLipSync；不打包未取得的 Core。', dependencies='Cubism SDK、MotionSync Core、模型专属映射', license='Live2D Open Software；Core/SDK 另受 Proprietary/SDK 条款'),
            dict(repo='mrxz/wlipsync', evidence=[dict(path='src/main.c', line=130, finding='实际音频频谱/MFCC 提取及模板分类，非单一响度'), dict(path='www/audio-node.ts', line=70, finding='按真实音频时间更新分类权重和平滑'), dict(path='README.md', line=55, finding='官方未提供校准创建器，指向 Unity uLipSync 流程')], advantage=['浏览器 WASM/AudioWorklet 可直接分析实际播放 PCM', '兼容 uLipSync 声学校准模板和多个元音类别', 'MIT，单文件内嵌 WASM 无额外运行服务'], gap=['AIRI 通用模板对当前 VITS 有元音混淆', '本地声线模板改善 U 收唇，但 E/O 仍会混淆；不提供辅音或字级时间对齐'], decision='直接固定依赖1.3.1；使用原版 WASM MFCC 导出生成本地声线模板，保留 AIRI 样例供其他声音选择。', dependencies='WebAudio AudioWorklet、WASM、声音专属 profile、localhost/HTTPS', license='MIT'),
        ])
        adopted = {
            'moeru-ai/airi': '直接移植元音 driver、样例 profile；此前已移植 MAGIC 和渲染补丁，来源提交分别记录。',
            'mrxz/wlipsync': '直接依赖 WASM 频谱分类；新增声线模板校准工具与选择界面。',
            'pipecat-ai/pipecat': '直接作为生产编排内核，Silero、Smart Turn、backchannel、取消、RTVI；本轮启用原生 metrics。',
            'pipecat-ai/pipecat-client-web': '直接依赖官方 RTVI 客户端。',
            'pipecat-ai/pipecat-client-web-transports': '直接依赖官方 PCM 录放 worklet 与 protobuf 传输。',
            'pipecat-ai/smart-turn': '通过 Pipecat 使用 Local Smart Turn v3.2 收尾判断。',
            'k2-fsa/sherpa-onnx': '直接运行 SenseVoice/VITS/ERes2Net；本轮采用原生 TTS callback 增量 PCM。',
            'FunAudioLLM/SenseVoice': '通过 sherpa-onnx 使用模型；不是复制其 Python 模型实现。',
            'snakers4/silero-vad': '通过 Pipecat 与声纹质量门使用。',
            'SYSTRAN/faster-whisper': '保留可选识别后备，当前主识别为 SenseVoice。',
            'akkoaya/EvatarFramework': '已借鉴模板可靠性机制；未引入完整会话框架。',
        }
        for project in projects:
            project['implemented'] = adopted.get(project['repo'], '未将该项目新增为生产依赖；具体可移植点和限制见决定。')
            project['commit'] = inventory[project['repo']]['commit']
        data = dict(date='2026-11-06', scope='44 research/support repositories plus official MotionSync and wLipSync source; fixed source inspection, not a uniform runtime benchmark.', projects=projects)
        (ROOT / 'docs/OPEN_SOURCE_LANGUAGE_REVIEW.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    else:
        data = load('docs/OPEN_SOURCE_LANGUAGE_REVIEW.json')
    projects = data['projects']
    assert len(projects) == len(inventory) == len({p['repo'] for p in projects})
    assert set(inventory) == {p['repo'] for p in projects}
    lines = [f'# {len(projects)} 个上游项目的语音系统复审', '',
        '日期：2026-11-06。覆盖研究与直接依赖的44个仓库，并补充官方 MotionSync 与 wLipSync，共46个完整源码归档。固定提交和归档 SHA256 见 [UPSTREAM_SOURCES.json](UPSTREAM_SOURCES.json)。下载不包含 Git 历史、LFS 权重或递归子模块；没有批量运行上游安装器。', '',
        '当前实现的进一步逐能力差距审查与依赖风险见 [CURRENT_VOICE_GAPS.md](CURRENT_VOICE_GAPS.md)，其中重新区分已具备、部分、缺失、待验证和非同类能力。', '',
        '以下是源码机制对照，不是全部项目在同机运行后的排名。“优势”表示该项目有值得借鉴的机制，可能已被当前系统采用；不表示整套项目一定更快。许可证指源码，模型、声音、角色素材、SDK Core 必须分别核查。原文仅 README 的项目明确标识，不能当作实现证据。完整结构化数据见 [OPEN_SOURCE_LANGUAGE_REVIEW.json](OPEN_SOURCE_LANGUAGE_REVIEW.json)。', '',
        '## 已落实的改动', '',
        '- 口型：wLipSync 1.3.1 原版 WASM 对实际 post-gain 播放 PCM 提取 MFCC 并分类；AIRI 元音 driver 提供胜出/次位、静音门和时间平滑；适配 DeepSeek 实际存在参数与边界。增加当前 CPU VITS 声线模板、通用样例选择、重连和停播清零。能做声学元音形状，尚不能做每字精确音素对齐。',
        '- 本地合成：sherpa 原生 callback 提前输出 PCM，有界队列/准入、连接复用与原生锁生命周期；HTTP400/429/500/503和出音后中断不会误回放完整WAV，仅404/501回退。',
        '- 编排：直接使用 Pipecat 和官方客户端/媒体传输，启用原生 TTFB/TTFA/processing metrics，保留 Smart Turn 与中文窄附和策略。',
        '- 声纹：此前已采用 ERes2Net/Silero 与模板可靠性机制；当前本人声音过滤需用户先录入，不会凭空识别用户身份。', '',
        '## 验证与仍有差距', '',
        '真实浏览器官方 PCM 播放器→wLipSync→Cubism 的等响度五元音测试通过：RMS 均约2800，而嘴形范围明显不同；本地模板使 U 收唇出现，但 E/O/U 仍有混淆。训练是独立十二重复字的合成录音，验证使用另生成的六重复字录音；小样本不是通用中文发音准确率。具体重现和数据见 [VALIDATION.md](VALIDATION.md)。', '',
        '短/长句各3次串行 CPU HTTP 基准：首PCM中位数0.124/0.125秒，完整WAV 0.305/1.322秒。流式先测、WAV后测，模型输出有随机变化；不是物理扬声器首音、DeepSeek端到端或NPU性能。', '',
        '尚未完成：真实外放 AEC/噪声/旁人声误接收评测、字级对齐、在线ASR首字质量、播放确认后的精确已听历史、连续声学流式模型和NPU合格推理。Pipecat empty-user-turn恢复是提示模型重生成，当前无播放ACK，不能直接当原音续播启用。原生AEC实验不能替代正确ADC/DAC播放参考。', '',
        '## 逐项目机制与移植决定', '']

    def items(value):
        return value if isinstance(value, list) else [value]

    for project in sorted(projects, key=lambda p: p['repo'].lower()):
        repo, commit = project['repo'], project['commit']
        assert commit == inventory[repo]['commit']
        lines += [f'### {repo}', '', f'源码：[{commit[:12]}](https://github.com/{repo}/tree/{commit})；许可：{project["license"]}。', '']
        for evidence in project['evidence']:
            source = ROOT / 'artifacts/upstream-archives' / repo.replace('/', '__') / evidence['path']
            assert source.is_file(), str(source)
            assert 0 < evidence['line'] <= len(source.read_text(encoding='utf-8', errors='replace').splitlines()), str(source)
            link = f'https://github.com/{repo}/blob/{commit}/{evidence["path"]}#L{evidence["line"]}'
            lines.append(f'- 证据：[{evidence["path"]}:{evidence["line"]}]({link}) — {evidence.get("finding", "源码机制") }。')
        lines += ['', '值得借鉴：' + '；'.join(items(project['advantage'])) + '。', '', '当前差距或移植成本：' + '；'.join(items(project['gap'])) + '。', '', '决定：' + project['decision'], '', '实际落地：' + project['implemented'], '', '依赖：' + '、'.join(items(project['dependencies'])) + '。', '']
    (ROOT / 'docs/OPEN_SOURCE_LANGUAGE_REVIEW.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Validated {len(projects)} projects and {sum(len(p["evidence"]) for p in projects)} source citations; rendered Markdown.')


if __name__ == '__main__':
    build()
