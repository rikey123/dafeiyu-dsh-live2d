# Windows 原生 MFA 音素对齐（历史归档）

> **2026-11-14 当前状态：MFA 运行功能已退役。** 本文涉及 MFA 的实现、安装、命令、测试和结果均为历史记录，不是当前可选功能；相关启动/安装/浏览器时间轴验收入口已经移除。当前仅使用实时 PCM 口型，见 [实时口型](REALTIME_LIPSYNC.md)。E 盘历史环境与权重未自动删除。下文旧“当前”描述不再代表现行状态。

## 历史实现

Windows 启动器默认使用独立的 **Windows 原生 CPU MFA**，不再要求安装 Linux、WSL、Ubuntu 或启用虚拟机功能。这里改变的是可选的音素对齐服务，不替换 GPU/CPU TTS、ASR 或后台 DeepSeek。

默认实时口型仍使用实际播放 PCM 的 wLipSync/MFCC；选择 MFA 后，流程是：

```text
本次本地 TTS 完整 WAV → 16kHz 单声道 PCM16
  → 原生 MFA align_one → 校验 WAV SHA256、时长、音素时间轴
  → 同一 epoch 的音素消息和 PCM → 浏览器实际消费样本驱动口型
```

**MFA 不是低延迟实时模式。** 它必须等待本段合成和对齐完成；服务缺失、对齐失败或超时会明确失败，不偷偷换成实时口型。API 和 MOSS-Live 语音模式不经过这条本地对齐链。

## 安装与路径

本机已经安装并完成实际对齐；以下是重新准备命令，不需要每次启动时执行：

```powershell
.venv/Scripts/python.exe scripts/prepare_mfa.py
```

若官方通道不可达，本机实际使用过的镜像命令为：

```powershell
.venv/Scripts/python.exe scripts/prepare_mfa.py --channel https://mirrors.sustech.edu.cn/anaconda/cloud/conda-forge --index-url https://mirrors.aliyun.com/pypi/simple
```

脚本安装 micromamba 2.10.0、conda-forge MFA 3.4.3、Python 3.11、CPU Kaldi/kalpy/pynini 和中文分词依赖；不在网关或系统 Python 中混装。下载保留 TLS 证书/主机名校验，micromamba 包和分词 ZIP 有固定 SHA256。完整 Conda/Pip 版本与模型校验信息写入安装记录。

准备脚本复用项目已经准备的 `models/mfa-mandarin` 普通话 v3 词典、声学模型、官方 `spacy_ontonotes.zip` 和 `postag.zip`；缺少资源会明确报错，不伪称完成安装。分词 ZIP 标记和解压模型同时保留，避免首次对齐重新联网下载。

| 内容 | 默认绝对路径 |
| --- | --- |
| 独立原生解释器 | `E:/Dafeiyu/runtimes/mfa/python.exe` |
| MFA 模型和词典 | `E:/Dafeiyu/models/mfa-mandarin` |
| 缓存、请求临时文件、分词模型 | `E:/Dafeiyu/cache/mfa` |
| 编译后的词典/声学模型缓存 | `E:/Dafeiyu/cache/mfa/compiled` |
| 安装记录和依赖清单 | `E:/Dafeiyu/cache/mfa/installation.json`、`conda-explicit.txt`、`pip-freeze.txt` |

原生环境是 Conda 布局，解释器直接位于环境根目录，不是 `Scripts/python.exe`。启动器只为子进程配置 DLL/PATH 与 E 盘缓存，不修改系统环境变量。可通过 ignored `.env` 中的 `DAFEIYU_MFA_RUNTIME`、`DAFEIYU_MFA_PYTHON`、`DAFEIYU_MFA_MODELS`、`DAFEIYU_MFA_CACHE` 覆盖路径；示例见根目录 `.env.example`。生成的 sidecar 配置仅包含白名单字段，不带云端密钥。

## 启用与生命周期

应用设置中选择本地 GPU 或 CPU TTS，并选择“MFA 音素对齐”。按保存配置启动：

```powershell
.venv/Scripts/python.exe scripts/run.py
```

启动器按保存配置管理 `127.0.0.1:8771`；切换 API/MOSS-Live 或退出时停止自己拥有的对齐服务，不终止用户外部服务。原生运行时不存在时提示运行准备脚本，**不自动回退 WSL**。保留旧 WSL 部署的用户必须显式设置 `DAFEIYU_MFA_BACKEND=wsl` 及对应 Linux 运行时路径。

- 每服务仅接受一个对齐请求，忙时返回 503；音频最多 30 秒，文本最多 1000 字。
- 独立请求进程在运行前即加入 Windows Job，包含 MFA 和 Kaldi 子进程；取消、断线、超时、服务退出时回收整棵自有进程树。Linux 兼容路径继续使用进程组。
- 服务 300 秒总期限，网关对齐读超时 305 秒；模型/依赖错误返回 503，超时返回 504，日志位于 `G:/dafeiyu/data/logs/8771.log`。
- 使用上游 `mfa align_one`，避免每句话完整创建 corpus。缓存以 MFA 版本、词典和声学模型内容为键；请求使用独立副本，只在时间轴验证通过后发布模型缓存，不把用户 WAV/转写放入共享模型缓存。
- 机器结果写入单独 JSON 文件，依赖诊断留在日志，不让 stdout 信息污染协议。
- `/health` 区分依赖准备与实际对齐：`runtime=windows-native`、`verification=not_probed|aligned`、`last_alignment`。健康查询不进行推理；`/api/status` 将 MFA 可用性计入整条本地 TTS 输出链，而非只检查 GPU。

## 本机验收（2026-11-14）

真实 Edge、正式前端构建、本地 GPU/CPU 模型和 Web Audio worklet；LLM 使用隔离的固定文本服务，**没有调用付费 API，也不是 DeepSeek/真人麦克风端到端测试**。测试文本为“你好，很高兴和你聊天。”。

| 场景 | 实测结果 |
| --- | --- |
| GPU GPT-SoVITS + MFA | 26 个真实音素区间，浏览器消费 52,800 samples；MFA 内部耗时 14.201 秒，从提交到播放 ACK 共 19.736 秒 |
| CPU MOSS-TTS-Nano ONNX + MFA | 26 个真实音素区间，浏览器消费 61,440 samples；复用编译模型后 MFA 7.899 秒，从提交到播放 ACK 共 22.648 秒，包含该模式按需准备 |
| CPU 对齐中停止，再发下一句 | 202ms 内观察到 busy 释放；下一句实际播放及入库，ACK 11.666 秒，MFA 6.908 秒 |
| MFA 地址不可达 | 整条 TTS 状态不可用，前端 0 PCM，收到“MFA 音素对齐失败”，未自动降级 |

三项浏览器用例均通过，`pageErrors=[]`，音素 epoch/SHA 与实际音频匹配；这是时间轴、播放和恢复链路验证，**不是人工唇形准确率或音质评测**。这些是单条样本，不是时延保证；取消 GPU 合成后立即续说仍有此前记录的独立重载窗口问题，本次没有声称修复。

证据：`E:/Dafeiyu/verification/mfa-native/browser-audit-MFA.json`。首次旧 corpus 路径的独立 smoke 曾用时 91.14 秒且包含分词资源联网检查，不应用作当前 `align_one` 热路径性能。其原始结果及第一次浏览器尝试作为历史保留。

MFA 单元/生命周期测试（包括真实 Windows 父子进程取消）共 28 项通过；缓存单测覆盖版本/模型变更失效、私有副本复用、失败/中断不发布、无用户音频/转写进入共享缓存和旧 corpus 兼容路径：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mfa_native.py tests/test_native_voice_launch.py speech/test_mfa_sidecar_health.py speech/test_mfa_alignment.py -q
```

额外回归：98 项后端测试、87 项前端测试通过，前端生产构建成功；构建仍有现有的大 bundle 体积警告。日志保存在同一验收目录的 `backend-regression.log`、`frontend-regression.log`、`frontend-build.log`。

本轮测试结束后已停止隔离 QA、ASR 和模型服务，保留用户原生产配置，不常驻占用显卡。旧审计结论见 `FEATURE_AUDIT_2026-11-14.md`，其中“MFA 本机不可用”已被本次原生验收取代；其他未验收/未修复项仍有效。
