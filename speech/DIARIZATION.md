# 离线说话人聚类诊断

此工具只供离线研究，输出的数字是相对聚类标签，不是身份认证、本人提取、声源分离或实时能力。合成的两种声音测试中出现同一声音被分成两个标签以及不同声音混为一类的错误；不要将结果用于 owner gate 或自动控制。

使用已安装语音依赖的环境，先执行 `python -m speech.prepare speaker` 和 `python -m speech.prepare_diarization`。后者下载 sherpa 提供的 pyannote segmentation 3 转换包并校验固定 SHA-256；已存在的目标目录不会被覆盖。segmentation 转换包附 MIT 许可证，声纹模型许可见其下载目录。

执行 `python -m speech.diarization input.wav --speakers 2`。输入须为不超过 30 秒的 16 kHz、单声道 PCM16 WAV；不指定 `--speakers` 时使用聚类阈值自动估计。结果包含时间区间与相对标签，无准确率保证。真实录音、重叠说话和环境噪声尚未经过标注评测。
