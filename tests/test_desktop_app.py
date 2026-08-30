from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from datapilot_verify.domain.models import AnalysisPlan
from webapp.desktop import DesktopApp


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DesktopApp:
    monkeypatch.setattr(
        "webapp.desktop.get_settings",
        lambda: SimpleNamespace(
            workspace_root=Path("workspace"),
            artifact_root=Path("artifacts"),
            llm_mode="mock",
            llm_api_key=None,
            llm_model="mock",
            llm_base_url="",
            max_tool_steps=4,
        ),
    )
    sample = Path(__file__).parents[1] / "data" / "sample"
    target = tmp_path / "data" / "sample"
    target.mkdir(parents=True)
    for name in ("orders.csv", "stores.csv"):
        (target / name).write_bytes((sample / name).read_bytes())
    semantic = tmp_path / "data" / "semantic"
    knowledge = tmp_path / "data" / "knowledge"
    semantic.mkdir(parents=True)
    knowledge.mkdir(parents=True)
    (semantic / "metrics.yml").write_bytes(
        (Path(__file__).parents[1] / "data" / "semantic" / "metrics.yml").read_bytes()
    )
    for item in (Path(__file__).parents[1] / "data" / "knowledge").glob("*.md"):
        (knowledge / item.name).write_bytes(item.read_bytes())
    return DesktopApp(tmp_path)


def test_initializes_sample_workspace(desktop: DesktopApp) -> None:
    names = {item["filename"] for item in desktop.datasets()}
    assert names == {"orders.csv", "stores.csv"}


def test_upload_valid_orders_replaces_workspace(desktop: DesktopApp) -> None:
    content = (
        b"order_id,paid_at,store_id,category,channel,paid_amount,refund_amount\n"
        b"o-1,2025-07-01,s-1,food,online,10,0\n"
    )
    profile = desktop.upload("new-orders.csv", content, "orders")
    assert profile["filename"] == "orders.csv"
    assert profile["row_count"] == 1


def test_upload_rejects_missing_columns(desktop: DesktopApp) -> None:
    with pytest.raises(ValueError, match="缺少字段"):
        desktop.upload("bad.csv", b"order_id\no-1\n", "orders")


def test_clarification_round_trip_through_desktop(desktop: DesktopApp) -> None:
    first = desktop.analyze("7 月销售额为什么下降？")
    assert first["status"] == "clarification"
    assert first["clarification"]["options"]
    resumed = desktop.resume(first["thread_id"], "net_sales")
    assert resumed["status"] == "completed"
    assert resumed["snapshot_id"]


def test_live_mode_without_api_key_fails_loudly(
    desktop: DesktopApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    import webapp.desktop as desktop_module

    monkeypatch.setattr(
        desktop_module,
        "get_settings",
        lambda: SimpleNamespace(
            workspace_root=Path("workspace"),
            artifact_root=Path("artifacts"),
            llm_mode="live",
            llm_api_key=None,
            llm_model="fake",
            llm_base_url="",
            max_tool_steps=4,
        ),
    )
    with pytest.raises(ValueError, match="DATAPILOT_LLM_API_KEY"):
        desktop.analyze("7 月净销售额为什么下降？")


def test_normalize_live_result_creates_snapshot(desktop: DesktopApp) -> None:
    plan = AnalysisPlan(
        plan_id="p1",
        dataset_ids=["orders"],
        metric="net_sales",
        analysis="aggregate",
        question="test",
    )
    result = desktop._normalize_live(
        "test",
        {
            "status": "completed",
            "answer": "ok",
            "tool_trace": [
                {
                    "name": "run_analysis",
                    "result": {
                        "ok": True,
                        "trace_id": "t1",
                        "data": {
                            "plan": plan.model_dump(mode="json"),
                            "metric": {"version": "v1"},
                            "result_hash": "h1",
                        },
                        "evidence": [],
                    },
                }
            ],
        },
    )
    assert result["snapshot_id"].startswith("snap_")
    assert len(list((desktop.output / "snapshots").glob("*.json"))) == 1
