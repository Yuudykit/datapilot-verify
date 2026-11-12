from __future__ import annotations

import json
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from datapilot_verify.agent import build_graph
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    graph = build_graph(ROOT, checkpointer=InMemorySaver())
    graph.context = ToolContext("demo", ROOT / "data" / "sample", ROOT / "artifacts" / "demo")
    question = "7 月净销售额为什么下降？"
    analysis = graph.invoke(question)
    if analysis["status"] != "completed" or not analysis.get("snapshot_id"):
        raise SystemExit(f"演示分析失败：{analysis['answer']}")

    args = {"snapshot_id": analysis["snapshot_id"]}
    replay = graph.registry.execute("replay_analysis", args, graph.context)
    if not replay.ok or not replay.data.get("identical"):
        raise SystemExit("演示快照重放出现差异。")
    report = graph.registry.execute("export_report", args, graph.context)
    if not report.ok:
        raise SystemExit("演示报告导出失败。")

    path = graph.context.output_dir / "demo_result.json"
    payload = {
        "question": question,
        "answer": analysis["answer"],
        "snapshot_id": analysis["snapshot_id"],
        "events": analysis["events"],
        "overall": analysis["data"]["overall"],
        "rows": analysis["data"]["rows"],
        "citations": analysis["citations"],
        "replay_changes": replay.data["changes"],
        "report": str(report.artifacts[0].path.relative_to(ROOT)),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(analysis["answer"])
    print(f"快照：{analysis['snapshot_id']}，重放一致")
    print(f"结果：{path.relative_to(ROOT)}")
    print(f"报告：{payload['report']}")


if __name__ == "__main__":
    main()

