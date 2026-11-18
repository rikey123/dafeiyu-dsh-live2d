# 本地 OpenVINO 对话模型

这是 OpenAI 兼容的本机流式对话服务，仅提供 `/v1/models` 和流式 `/v1/chat/completions`。建议绑定 `127.0.0.1`。模型默认读取项目目录 `models/qwen3-1.7b-int4`，需要完整的 OpenVINO IR、tokenizer 和配置文件；该目录不提交到 Git。

安装 `requirements-llm.txt`，在项目根目录运行：

```powershell
$env:DAFEIYU_LLM_DEVICE = 'CPU'
.venv\Scripts\python.exe -m uvicorn inference.app:app --host 127.0.0.1 --port 8767
```

模型首次加载可能需要较长时间，`GET http://127.0.0.1:8767/health` 显示 `loading`、`ready` 或 `error`。应用设置中把模型地址设置为 `http://127.0.0.1:8767/v1`，模型名为 `qwen3-1.7b-int4`，密钥留空。

可通过 `DAFEIYU_LLM_MODEL_DIR` 指定模型目录，`DAFEIYU_LLM_MODEL_ID` 指定模型名称，`DAFEIYU_LLM_DEVICE` 指定 OpenVINO 设备。默认 `CPU`；`GPU` 或 `NPU` 必须先确认设备、驱动和模型兼容，并实际测量。服务不会在设备加载失败时声称成功，也不会静默回退。Qwen3 模板通过 `enable_thinking=False` 关闭思考输出，默认最多生成 256 token。生成任务单次串行，客户端断开后请求取消；生成线程实际退出后才允许下一请求执行。

模型和运行库的许可、用途及分发条件需分别遵守。对话自然度和延迟依赖模型、设备和上下文长度，应以实际体验为准。
