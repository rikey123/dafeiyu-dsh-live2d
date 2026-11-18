"""Bound persisted history before loading it into the voice framework."""


def context_messages(settings: dict, memories: list[dict], history: list[dict]) -> list[dict]:
    system = settings["system_prompt"]
    memory_text = "\n".join("- " + item["content"] for item in memories[:30])[:3000]
    if memory_text:
        system += "\n用户希望你记住的信息：\n" + memory_text
    remaining = 20000 - len(system)
    selected = []
    for row in reversed(history[-30:]):
        if len(row["content"]) > remaining:
            break
        selected.append({"role": row["role"], "content": row["content"]})
        remaining -= len(row["content"])
    selected.reverse()
    while selected and selected[0]["role"] == "assistant":
        selected.pop(0)
    return [{"role": "system", "content": system}, *selected]
