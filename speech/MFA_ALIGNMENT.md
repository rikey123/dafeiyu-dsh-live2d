# 离线普通话音素对齐

> **2026-11-14 当前状态：MFA 运行功能已退役。** 本文涉及 MFA 的实现、安装、命令、测试和结果均为历史记录，不是当前可选功能；相关启动/安装/浏览器时间轴验收入口已经移除。当前仅使用实时 PCM 口型，见 [实时口型](../docs/REALTIME_LIPSYNC.md)。E 盘历史环境与权重未自动删除。下文旧“当前”描述不再代表现行状态。

此工具使用 Montreal Forced Aligner 3.3.9、官方 `mandarin_mfa` 声学模型和 `mandarin_china_mfa` 字典。它从原生 TextGrid 的 `words` 和 `phones` 层读取实际对齐区间，不按字符均分时间。输入文本必须与音频匹配；普通话词典缺词、识别错误、音色或环境变化会影响结果。尚无人工标注准确率验收，不能直接当作经过验证的口型数据。

Windows 先在项目根目录运行 `python -m speech.prepare_mfa`，下载固定地址并校验声学模型、词典、中文分词资源和 Linux micromamba 的 SHA-256。需要 WSL Ubuntu x86_64、Python 3 和网络；在 WSL 中执行：

```bash
cd /mnt/d/project/dafeiyu
bash speech/setup_mfa_wsl.sh /mnt/d/project/dafeiyu/models/mfa-mandarin/micromamba-linux-64-2.5.0.tar.bz2 "$HOME/.local/share/dafeiyu/mfa"
export MAMBA_ROOT_PREFIX="$HOME/.local/share/dafeiyu/mfa/root"
export PKUSEG_HOME="$HOME/.local/share/dafeiyu/mfa/pkuseg"
"$HOME/.local/share/dafeiyu/mfa/bin/micromamba" run -p "$HOME/.local/share/dafeiyu/mfa/env" python -m speech.mfa_alignment /mnt/d/project/dafeiyu/input.wav '你好 今天 过 得 怎么样' --dictionary /mnt/d/project/dafeiyu/models/mfa-mandarin/mandarin_china_mfa-v3.0.0.dict --acoustic-model /mnt/d/project/dafeiyu/models/mfa-mandarin/mandarin_mfa-v3.0.0.zip --textgrid /mnt/d/project/dafeiyu/output.TextGrid
```

安装位置使用 WSL 原生持久用户目录；不要将环境放在可能被清理的 `/tmp`。输出 JSON 的 `phones` 是 `{text,start_s,end_s,unit}` 列表，`unit` 为 `phoneme`，秒数相对于该 WAV 起点，空白表示静音；`words` 使用同样结构。`audio_sha256` 标识输入 WAV 文件字节，`sample_rate` 为音频采样率；播放 epoch 须由调用方绑定。`--textgrid` 可选，目标已存在时拒绝覆盖。输入限 30 秒、16 kHz 单声道 PCM16 WAV。

首次安装需下载数百 MB conda 包。已缓存资源后，本机三次对 1.65 秒语音分别耗时 32.29、32.23、32.08 秒（包含每次启动和临时语料准备）。应用提供明确的可选 MFA 模式，等待本次真实音频对齐再播放；默认仍使用实时 MFCC。CPU 速度不再阻止接入，但该模式不宣称低延迟。实际 VITS→MFA→浏览器播放、取消和回执分别按证据验收，见 [可选服务说明](../docs/OPTIONAL_VOICE_SERVICES.md)。`MFA` 和其模型、字典及中文分词资源各自的许可证和条款需在分发前分别核查。
