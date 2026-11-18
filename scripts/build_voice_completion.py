"""Render and validate the exhaustive implementation ledger from the fixed audit.

Every audited capability retains its own stable ID, including existing and
different-purpose capabilities. Work items group equivalent mechanisms without
pretending that installing every alternative engine improves the product.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/VOICE_COMPLETION.json"
STATES = {"已有", "进行中", "待实现", "待实测", "条件受限", "非同类候选", "已验收"}


def validate(data, audit):
    expected = [(p["repo"], c["mechanism"]) for p in audit["projects"] for c in p["capabilities"]]
    actual = [(r["repo"], r["mechanism"]) for r in data["capabilities"]]
    if expected != actual:
        raise ValueError("Ledger must preserve every audit capability in its original order")
    tasks = {t["id"]: t for t in data["tasks"]}
    if len(tasks) != len(data["tasks"]):
        raise ValueError("Duplicate work item ID")
    for index, row in enumerate(data["capabilities"], 1):
        if row["id"] != f"V{index:03}" or not row["tasks"]:
            raise ValueError("Unnumbered or unassigned capability")
        if len(row["tasks"]) != len(set(row["tasks"])):
            raise ValueError(f"Duplicate work item in capability: {row['id']}")
        if any(t not in tasks for t in row["tasks"]):
            raise ValueError(f"Unknown work item: {row['id']}")
    for t in tasks.values():
        if t["status"] not in STATES or not t["acceptance"] or not t["remaining"]:
            raise ValueError(f"Incomplete task: {t['id']}")
        if not t.get("engineering"):
            raise ValueError(f"Missing engineering integration state: {t['id']}")
        if t["status"] == "已验收" and (not t["evidence"] or not t.get("result")):
            raise ValueError(f"Task lacks acceptance evidence: {t['id']}")
        for path in t["evidence"]:
            if not (ROOT / path).is_file():
                raise ValueError(f"Evidence does not exist: {path}")
    extras = {(p["repo"], value) for p in audit["projects"] for value in p.get("missing_top", [])}
    covered = {(r["repo"], r["finding"]) for r in data["additional_findings"]}
    if extras != covered or len(covered) != len(data["additional_findings"]):
        raise ValueError("missing_top audit findings are not completely covered")
    for row in data["additional_findings"]:
        if not row["tasks"] or len(row["tasks"]) != len(set(row["tasks"])) or any(t not in tasks for t in row["tasks"]):
            raise ValueError(f"Unassigned or invalid additional finding: {row['repo']}")


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render(data, audit):
    tasks = {t["id"]: t for t in data["tasks"]}
    counts = Counter(t["status"] for t in tasks.values())
    lines = ["# 语音差距逐项补齐表", "", f"来源：46 个固定上游，{len(data['capabilities'])} 项原始能力；审计基线 `{audit['baseline_commit']}`。更新：{data['updated']}。", "",
             "本表是实施与验收记录。原始审计保留于 [CURRENT_VOICE_GAPS.md](CURRENT_VOICE_GAPS.md)。同一能力的不同开源实现关联到同一工作项；保留每个出处，避免遗漏，也避免重复引入互斥的推理/播放栈。已有能力保留回归项；非同类架构保留候选评估项。", "",
             "**状态以证据为准：代码接入、合成样本通过、真人/物理设备验收分别记录。待实测与条件受限均不是已完成。CPU 推理不能作为 NPU 验收。**", "",
             "任务状态：" + "；".join(f"{k} {v}" for k, v in sorted(counts.items())) + "。", "",
             "工程接入与验收状态分列。CPU 耗时不作为推迟代码接入的条件；独立诊断工具不算生产链路接入，未实现路径不能仅写成待测试。", "",
             "## 实施工作项与验收", "", "| 工作项 | 优先级 / 负责人 | 工程接入 | 验收状态 | 实现与验收条件 | 本轮证据 / 结果 | 尚需完成 |", "|---|---|---|---|---|---|---|"]
    for t in tasks.values():
        proof = "；".join(f"[{p}]({Path(p).name if p.startswith('docs/') else '../' + p})" for p in t["evidence"])
        lines.append("| " + " | ".join(map(cell, [t["id"] + " · " + t["title"], t["priority"] + " / " + t["owner"], t["engineering"], t["status"], t["acceptance"], proof + ("；" + t.get("result", "") if t.get("result") else ""), t["remaining"]])) + " |")
    lines += ["", "## 全部 99 项能力对照", "", "| 编号 | 开源项目 / 能力 | 审计判定 | 补齐工作项 | 当前任务状态 |", "|---|---|---|---|---|"]
    for row in data["capabilities"]:
        lines.append("| " + " | ".join(map(cell, [row["id"], row["repo"] + " · " + row["mechanism"], row["baseline_state"], ", ".join(row["tasks"]), "；".join(f"{t}: {tasks[t]['status']}" for t in row["tasks"])])) + " |")
    lines += ["", "## 审计补充发现（逐条保留）", "", "| 项目 | 补充发现 | 对应任务 |", "|---|---|---|"]
    for row in data["additional_findings"]:
        lines.append("| " + " | ".join(map(cell, [row["repo"], row["finding"], ", ".join(row["tasks"])])) + " |")
    lines += ["", "## 复现与更新", "", "运行 `.venv\\Scripts\\python.exe scripts/build_voice_completion.py` 校验 46 仓库、99 项能力和全部补充发现无遗漏，再生成本表及可导入表格的 UTF-8 CSV。JSON 是状态唯一来源；验收更新必须填写证据和未解决条件。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate tracked artifacts without rewriting")
    args = parser.parse_args()
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "docs/CURRENT_VOICE_GAPS.json").read_text(encoding="utf-8"))
    validate(data, audit)
    markdown = render(data, audit)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["编号", "项目", "能力", "原始判定", "工作项", "当前状态", "当前结果", "尚需完成"])
    tasks = {t["id"]: t for t in data["tasks"]}
    for row in data["capabilities"]:
        writer.writerow([row["id"], row["repo"], row["mechanism"], row["baseline_state"], ";".join(row["tasks"]), ";".join(tasks[t]["status"] for t in row["tasks"]), "；".join(t + ": " + tasks[t].get("result", "") for t in row["tasks"]), "；".join(t + ": " + tasks[t]["remaining"] for t in row["tasks"])])
    task_stream = io.StringIO(newline="")
    task_writer = csv.writer(task_stream)
    task_writer.writerow(["工作项", "任务", "优先级", "负责人", "工程接入", "验收状态", "验收条件", "当前结果", "尚需完成", "证据"])
    for task in tasks.values():
        task_writer.writerow([task["id"], task["title"], task["priority"], task["owner"], task["engineering"], task["status"], task["acceptance"], task.get("result", ""), task["remaining"], ";".join(task["evidence"])])
    for path, content in [(ROOT / "docs/VOICE_COMPLETION.md", markdown), (ROOT / "docs/VOICE_COMPLETION.csv", "\ufeff" + stream.getvalue()), (ROOT / "docs/VOICE_TASKS.csv", "\ufeff" + task_stream.getvalue())]:
        if args.check:
            if path.read_text(encoding="utf-8").replace("\r\n", "\n") != content.replace("\r\n", "\n"):
                raise ValueError(f"Stale generated artifact: {path.name}")
        else:
            path.write_bytes(content.encode("utf-8"))
    print(json.dumps({"repositories": len(audit["projects"]), "capabilities": len(data["capabilities"]), "additional_findings": len(data["additional_findings"]), "tasks": len(tasks), "status_counts": dict(Counter(t["status"] for t in tasks.values()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
