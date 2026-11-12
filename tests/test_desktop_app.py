from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from datapilot_verify.data.catalog import DatasetCatalog
from datapilot_verify.domain.models import AnalysisPlan, TablePlan
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


@pytest.fixture
def custom_workbook() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "说明"
    book.active.append(["说明内容"])
    sheet = book.create_sheet("进度")
    sheet.append(["项目跟踪"])
    sheet.append(["编号", "状态", "工时"])
    sheet.append(["001", "待办", 2.5])
    sheet.append(["002", "已完成", 4])
    sheet.append(["003", "待办", None])
    sheet.append(["004", None, 1])
    with BytesIO() as stream:
        book.save(stream)
        return stream.getvalue()


def test_custom_workbook_uses_selected_sheet_and_preserves_business_data(
    desktop: DesktopApp, custom_workbook: bytes
) -> None:
    orders = desktop.workspace / "orders.csv"
    original = orders.read_bytes()
    imported = desktop.upload("进度.xlsx", custom_workbook, sheet="进度", header_row=2)
    dataset_id = imported["dataset_id"]
    assert imported["fields"] == ["编号", "状态", "工时"]
    assert imported["row_count"] == 4
    assert orders.read_bytes() == original
    assert desktop.tables() == [imported]
    profile = desktop.analyze_table("检查数据质量", dataset_id)
    assert profile["data"]["table_result"]["rows"][1]["null_count"] == 1
    grouped = desktop.analyze_table("按状态统计数量", dataset_id)
    assert grouped["data"]["table_result"]["rows"] == [
        {"group": "已完成", "value": 1},
        {"group": "待办", "value": 2},
        {"group": None, "value": 1},
    ]
    assert desktop.replay(grouped["snapshot_id"])["data"]["identical"]
    assert "table_plan" in desktop.report(grouped["snapshot_id"]).read_text(encoding="utf-8")
    result = desktop.analyze_table("平均工时", TablePlan(
        dataset_id=dataset_id, operation="mean", value_column="工时",
        filter_column="状态", filter_value="待办",
    ))
    assert result["data"]["table_result"]["rows"] == [{"value": "2.5", "valid": 1}]
    exact = desktop.analyze_table("编号=001的记录数", dataset_id)
    assert exact["data"]["table_result"]["rows"] == [{"value": 1}]
    with pytest.raises(ValueError, match="非数值"):
        desktop.analyze_table("计算状态的平均值", dataset_id)
    with pytest.raises(ValueError, match="没有字段"):
        desktop.analyze_table("按不存在的列统计数量", dataset_id)


def test_general_csv_handles_gb18030_and_rejects_duplicate_headers(desktop: DesktopApp) -> None:
    content = "城市,记录\n上海,甲\n,\n杭州,乙\n".encode("gb18030")
    imported = desktop.upload("台账.csv", content)
    assert imported["row_count"] == 2
    with pytest.raises(ValueError, match="重复字段"):
        desktop.upload("重复.csv", b"city,city\na,b\n")
    assert desktop.tables() == [imported]


def test_general_csv_header_row_counts_blank_lines(desktop: DesktopApp) -> None:
    content = b"\n\ncity,amount\n\nShanghai,1\n"
    with pytest.raises(ValueError):
        desktop.upload("summary.csv", content, header_row=1)
    imported = desktop.upload("summary.csv", content, header_row=3)
    assert imported["fields"] == ["city", "amount"]
    assert imported["row_count"] == 1


def test_ui_uploads_and_queries_non_business_workbook(
    desktop: DesktopApp, custom_workbook: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATAPILOT_LLM_MODE", "mock")
    monkeypatch.setattr("webapp.desktop.DesktopApp", lambda _: desktop)
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: SimpleNamespace(
        name="进度.xlsx", getvalue=lambda: custom_workbook,
    ))
    source = Path(__file__).resolve().parents[1] / "webapp" / "streamlit_app.py"
    app = AppTest.from_file(str(source)).run()
    next(select for select in app.selectbox if select.label == "工作表").set_value("进度")
    app.number_input[0].set_value(2).run()
    app.button(key="upload_workspace").click().run()
    assert not app.exception
    assert app.selectbox(key="analysis_source").value == desktop.tables()[0]["dataset_id"]
    assert app.text_area[0].value == "检查数据质量"
    app.text_area[0].set_value("按状态统计数量")
    next(button for button in app.button if button.label == "开始分析").click().run()
    assert not app.exception
    assert app.dataframe[0].value["value"].tolist() == [1, 2, 1]
    for label, value in (("操作", "mean"), ("数值字段", "工时"), ("筛选字段", "状态")):
        next(select for select in app.selectbox if select.label == label).set_value(value)
    next(field for field in app.text_input if field.label == "等于").set_value("待办")
    next(button for button in app.button if button.label == "按配置执行").click().run()
    assert not app.exception
    assert app.dataframe[0].value["value"].tolist() == ["2.5"]


def test_duplicate_store_rejects_analysis_and_replay(desktop: DesktopApp) -> None:
    initial = desktop.analyze("7 月净销售额为什么下降？")
    stores = desktop.workspace / "stores.csv"
    contents = stores.read_bytes()
    stores.write_bytes(contents + contents.splitlines(keepends=True)[1])

    result = desktop.analyze("7 月净销售额为什么下降？")
    assert result["status"] == "error"
    assert "store_id" in result["answer"]
    assert not result.get("snapshot_id")
    assert "rows" not in result["data"]

    replay = desktop.replay(initial["snapshot_id"])
    assert not replay["ok"]
    assert not replay["data"]["identical"]
    assert replay["error"]["code"] == "EXECUTION_FAILED"


def test_ui_falls_back_when_interactive_table_cannot_import(
    desktop: DesktopApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    def unavailable(*args, **kwargs):
        raise ImportError("numpy.core.multiarray failed to import")

    monkeypatch.setenv("DATAPILOT_LLM_MODE", "mock")
    monkeypatch.setattr("webapp.desktop.DesktopApp", lambda _: desktop)
    monkeypatch.setattr(st, "dataframe", unavailable)
    source = Path(__file__).resolve().parents[1] / "webapp" / "streamlit_app.py"
    app = AppTest.from_file(str(source)).run()
    next(button for button in app.button if button.label == "开始分析").click().run()
    assert not app.exception
    assert any("华东" in item.proto.body for item in app.get("html"))
    assert app.get("download_button")
    next(button for button in app.button if button.label == "重放").click().run()
    assert any(item.value == "重放一致" for item in app.success)
    next(button for button in app.button if button.label == "检查订单数据").click().run()
    next(button for button in app.button if button.label == "开始分析").click().run()
    assert not app.exception
    assert any("空值数" in item.proto.body for item in app.get("html"))


@pytest.mark.parametrize("changed", ["data", "semantic", "knowledge"])
def test_replay_distinguishes_unchanged_results_from_changed_evidence(
    desktop: DesktopApp, changed: str
) -> None:
    initial = desktop.analyze("7 月净销售额为什么下降？")
    paths = {
        "data": desktop.workspace / "stores.csv",
        "semantic": desktop.project_root / "data" / "semantic" / "metrics.yml",
        "knowledge": next((desktop.project_root / "data" / "knowledge").glob("*.md")),
    }
    additions = {
        "semantic": b"\n# Same metric, different source file.\n",
        "knowledge": b"\n\nAdditional documentation.\n",
    }
    path = paths[changed]
    if changed == "data":
        # Change an unused store column while keeping keys and regions intact.
        path.write_bytes(path.read_bytes().replace(b"2023-01-01", b"2023-01-02", 1))
    else:
        with path.open("ab") as handle:
            handle.write(additions[changed])

    replay = desktop.replay(initial["snapshot_id"])
    assert replay["ok"]
    assert not replay["data"]["identical"]
    assert replay["data"]["changes"] == {
        dimension: dimension == changed for dimension in ("data", "semantic", "knowledge", "result")
    }


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


def test_normalize_live_result_surfaces_failed_analysis(desktop: DesktopApp) -> None:
    result = desktop._normalize_live(
        "test",
        {
            "status": "completed",
            "answer": "净销售额为 100 元。",
            "tool_trace": [
                {
                    "name": "run_analysis",
                    "result": {"ok": False, "error": {"message": "store_id 重复。"}},
                }
            ],
        },
    )
    assert result["status"] == "error"
    assert result["answer"] == "store_id 重复。"
    assert not result.get("snapshot_id")


def test_datasets_profile_is_cached_until_files_change(
    desktop: DesktopApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}
    original = DatasetCatalog.profile

    def counting_profile(self: object, path: str) -> object:
        calls["count"] += 1
        return original(self, path)

    monkeypatch.setattr(
        "datapilot_verify.data.catalog.DatasetCatalog.profile", counting_profile
    )
    desktop.datasets()
    after_first = calls["count"]
    desktop.datasets()
    assert calls["count"] == after_first
    desktop.upload(
        "orders.csv",
        b"order_id,paid_at,store_id,category,channel,paid_amount,refund_amount\n"
        b"o-1,2025-07-01,s-1,food,online,10,0\n",
        "orders",
    )
    desktop.datasets()
    assert calls["count"] > after_first


def test_report_export_reuses_existing_file(
    desktop: DesktopApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datapilot_verify.app as app_module

    result = desktop.analyze("7 月净销售额为什么下降？")
    snapshot_id = result["snapshot_id"]
    calls = {"count": 0}
    real_builder = app_module.build_registry

    def counting_builder(root: Path) -> object:
        calls["count"] += 1
        return real_builder(root)

    monkeypatch.setattr(app_module, "build_registry", counting_builder)
    first_path = desktop.report(snapshot_id)
    assert calls["count"] == 1
    assert desktop.report(snapshot_id) == first_path
    assert calls["count"] == 1
