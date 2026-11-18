"""Spawn entry point. No provider credentials cross this process boundary."""
import logging


def serve(pipe, kind, config):
    try:
        import os
        os.chdir(config["source"])
        from speech.model_engines import create_engine
        engine = create_engine(kind, config)
        if config.get("preload"):
            # Run the same inference path once, retaining reference encodings
            # and CUDA graphs. Discard PCM locally; never play or persist it.
            import time
            pipe.send(("warming", None))
            started = time.monotonic()
            size = sum(len(audio) for audio in engine.stream("你好，我已经准备好了。", "default"))
            if not size:
                raise RuntimeError("模型预热没有返回音频")
            if kind in {"index_tts", "gpt_sovits"} and engine.metadata.get("device") != "cuda":
                raise RuntimeError("GPU 预热未使用 CUDA；不允许 CPU 回退")
            engine.metadata.update(warmed_up=True, warmup_seconds=round(time.monotonic()-started, 3))
        pipe.send(("ready", engine.metadata))
        while True:
            text, voice = pipe.recv()
            for audio in engine.stream(text, voice):
                for offset in range(0, len(audio), 4800):
                    pipe.send(("audio", audio[offset:offset+4800]))
            pipe.send(("done", engine.metadata))
    except EOFError:
        pass
    except Exception:
        logging.exception("Local model worker failed")
        try:
            pipe.send(("error", "模型加载或合成失败，请查看本地模型服务日志"))
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        pipe.close()
