from __future__ import annotations

import json
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import plotly.graph_objects as go
import streamlit as st

from datapilot_verify.config import get_settings
from datapilot_verify.data.tables import OPERATIONS, workbook_sheets
from datapilot_verify.domain.models import TablePlan
from webapp.desktop import DesktopApp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION = "7 月净销售额为什么下降？"
DEFAULT_TABLE_QUESTION = "检查数据质量"
BUSINESS_SOURCE = "business"
EXAMPLES = (
    ("净销售额变化", DEFAULT_QUESTION),
    ("渠道退款率", "按渠道看退款率变化"),
    ("检查订单数据", "检查订单数据质量"),
)
DIMENSION_NAMES = {
    "region": "区域",
    "city": "城市",
    "store_id": "门店",
    "category": "品类",
    "channel": "渠道",
}
DIFF_LABELS = {
    "data": "源数据",
    "semantic": "指标口径",
    "knowledge": "知识文档",
    "result": "计算结果",
}

st.set_page_config(page_title="DataPilot Verify", page_icon="📊", layout="wide")


@st.cache_resource
def desktop_app() -> DesktopApp:
    return DesktopApp(ROOT)


def render_sidebar(app: DesktopApp) -> None:
    with st.sidebar:
        st.html(
            '<div class="workspace-brand"><span class="workspace-mark">DP</span>'
            '<div><strong>DataPilot</strong><span>VERIFY</span></div></div>'
        )
        st.markdown("#### 数据工作区")
        for profile in app.datasets():
            filename = profile["filename"]
            label = {"orders.csv": "订单明细", "stores.csv": "门店维表"}.get(filename, filename)
            with st.expander(f"{label} · {profile['row_count']:,} 行"):
                st.caption(filename)
                if time_range := profile.get("time_range"):
                    st.caption(f"{time_range[0]} 至 {time_range[1]}")
                st.write("、".join(column["name"] for column in profile["columns"]))
        with st.expander("导入数据"):
            role = st.selectbox(
                "导入方式",
                ["table", "orders", "stores"],
                format_func={
                    "table": "通用表格",
                    "orders": "替换经营订单明细",
                    "stores": "替换经营门店维表",
                }.__getitem__,
            )
            uploaded = st.file_uploader("选择 CSV 或 Excel", type=["csv", "xlsx", "xls"])
            sheet = None
            header_row = 1
            upload_error = False
            if role == "table" and uploaded is not None:
                try:
                    sheets = workbook_sheets(uploaded.name, uploaded.getvalue())
                except (ValueError, OSError, ImportError, BadZipFile, ParseError):
                    st.error("无法读取工作簿。请确认文件格式和内容，旧版 XLS 需要 xlrd。")
                    upload_error = True
                else:
                    if sheets:
                        sheet = st.selectbox("工作表", sheets)
                    header_row = st.number_input("表头所在行", min_value=1, value=1, step=1)
            if st.button(
                "导入工作区", key="upload_workspace",
                disabled=uploaded is None or upload_error, use_container_width=True,
            ):
                try:
                    profile = app.upload(
                        uploaded.name, uploaded.getvalue(), role, sheet=sheet, header_row=header_row
                    )
                except (OSError, ValueError, ImportError, BadZipFile, ParseError) as exc:
                    st.error(str(exc))
                else:
                    if role == "table":
                        st.session_state["analysis_source"] = profile["dataset_id"]
                        st.session_state["upload_notice"] = (
                            f"已导入 {profile['filename']} · {profile['row_count']:,} 行"
                        )
                    else:
                        st.session_state["analysis_source"] = BUSINESS_SOURCE
                        st.session_state["upload_notice"] = f"已替换 {profile['filename']}"
                    change_source()
                    st.rerun()
        if notice := st.session_state.pop("upload_notice", None):
            st.success(notice)


def choose_example(question: str) -> None:
    st.session_state["analysis_question"] = question


def change_source() -> None:
    st.session_state.pop("result", None)
    st.session_state.pop("replay", None)
    st.session_state["analysis_question"] = (
        DEFAULT_QUESTION if st.session_state["analysis_source"] == BUSINESS_SOURCE
        else DEFAULT_TABLE_QUESTION
    )


def render_question(app: DesktopApp) -> None:
    tables = {table["dataset_id"]: table for table in app.tables()}
    table_labels = {
        key: f"{table['filename']} / {table['sheet']}" if table["sheet"] else table["filename"]
        for key, table in tables.items()
    }
    duplicates = Counter(table_labels.values())
    labels = {
        BUSINESS_SOURCE: "经营指标 · 订单 + 门店",
        **{
            key: f"{label} · {key[-6:]}" if duplicates[label] > 1 else label
            for key, label in table_labels.items()
        },
    }
    st.session_state.setdefault("analysis_question", DEFAULT_QUESTION)
    with st.container(key="question_panel"):
        st.markdown("### 发起分析")
        if st.session_state.get("analysis_source", BUSINESS_SOURCE) not in labels:
            st.session_state["analysis_source"] = BUSINESS_SOURCE
            change_source()
        source = st.selectbox(
            "分析数据", list(labels), format_func=labels.__getitem__,
            key="analysis_source", on_change=change_source,
        )
        table = tables.get(source)
        if table:
            st.caption(f"{table['row_count']:,} 行 · {len(table['fields'])} 个字段 · 本地执行")
        question = st.text_area(
            "分析问题",
            value=None,
            key="analysis_question",
            height=68,
            label_visibility="collapsed",
            placeholder="例如：按状态统计数量" if table else "输入想分析的经营问题",
        )
        examples = EXAMPLES
        if table:
            first_field = table["fields"][0]
            examples = (
                ("检查数据质量", DEFAULT_TABLE_QUESTION),
                ("统计总行数", "统计总行数"),
                ("按字段计数", f"按「{first_field}」统计数量"),
            )
        shortcuts, action = st.columns([4, 1.25], vertical_alignment="center")
        with shortcuts:
            with st.container(horizontal=True, gap="small", key="analysis_examples"):
                for label, example in examples:
                    st.button(label, on_click=choose_example, args=(example,))
        with action:
            submitted = st.button("开始分析", type="primary", use_container_width=True)
        if submitted:
            run_question(app, question or "", source if table else None)
        if table:
            render_table_controls(app, table)


def run_question(app: DesktopApp, question: str, table: str | TablePlan | None) -> None:
    st.session_state.pop("result", None)
    st.session_state.pop("replay", None)
    if not question.strip():
        st.warning("请输入一个分析问题。")
        return
    with st.spinner("正在执行分析…"):
        try:
            st.session_state["result"] = (
                app.analyze_table(question, table) if table is not None else app.analyze(question)
            )
        except Exception as exc:
            st.error(f"分析失败 · {exc}")


def render_table_controls(app: DesktopApp, table: dict[str, Any]) -> None:
    fields = [None, *table["fields"]]
    with st.expander("按字段配置"):
        with st.form(f"table_options_{table['dataset_id']}"):
            operation = st.selectbox("操作", list(OPERATIONS), format_func=OPERATIONS.__getitem__)
            group = st.selectbox("分组字段", fields, format_func=lambda field: field or "不分组")
            value = st.selectbox("数值字段", fields, format_func=lambda field: field or "不指定")
            filter_column = st.selectbox(
                "筛选字段", fields, format_func=lambda field: field or "不筛选"
            )
            filter_value = st.text_input("等于", help="精确匹配。留空可筛选空白单元格。")
            submitted = st.form_submit_button("按配置执行")
        if submitted:
            try:
                plan = TablePlan(
                    dataset_id=table["dataset_id"], operation=operation,
                    group_by=group if operation != "profile" else None,
                    value_column=value if operation not in {"profile", "count"} else None,
                    filter_column=filter_column if operation != "profile" else None,
                    filter_value=filter_value.strip()
                    if filter_column and operation != "profile" else None,
                )
            except ValueError:
                st.error("请为合计、平均值、最小值或最大值选择一个数值字段。")
            else:
                run_question(app, OPERATIONS[operation], plan)


def render_clarification(result: dict[str, Any], app: DesktopApp) -> None:
    with st.container(key="clarification_panel"):
        st.markdown("### 确认指标口径")
        options = (result.get("clarification") or {}).get("options", [])
        if not options:
            st.warning(result.get("answer", "需要补充信息后才能继续。"))
            return
        labels = {item["label"]: item["value"] for item in options}
        choice = st.selectbox("本次分析采用的指标", list(labels), key="clarify_choice")
        if st.button("确认口径并继续", type="primary"):
            with st.spinner("正在继续分析…"):
                try:
                    st.session_state["result"] = app.resume(result["thread_id"], labels[choice])
                    st.rerun()
                except Exception as exc:
                    st.error(f"分析失败 · {exc}")


def format_value(value: Any, unit: str, *, change: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if change and value != 0 else ""
    if unit == "ratio":
        return f"{value * 100:{sign}.2f} 个百分点" if change else f"{value:.2%}"
    prefix = "¥" if unit in {"CNY", "CNY/order"} else ""
    precision = 0 if unit == "CNY" and float(value).is_integer() else 2
    sign = "−" if value < 0 else sign
    return f"{sign}{prefix}{abs(value):,.{precision}f}"


def period_label(period: list[str] | None) -> str:
    if not period:
        return ""
    start, end = period
    return f"{start} 至 {end}"


def render_metrics(data: dict[str, Any]) -> None:
    if not (overall := data.get("overall")):
        return
    metric = data.get("metric", {})
    unit = metric.get("unit", "")
    name = metric.get("name", "指标")
    comparison = (data.get("plan") or {}).get("comparison") or {}
    change_name = {"mom": "环比变化", "yoy": "同比变化"}.get(comparison.get("type"), "变化额")
    change_rate = overall.get("change_rate")
    tiles = (
        (
            f"本期{name}", format_value(overall.get("current_value"), unit),
            period_label(comparison.get("current_period")),
        ),
        (
            f"上期{name}", format_value(overall.get("previous_value"), unit),
            period_label(comparison.get("previous_period")),
        ),
        (
            change_name, format_value(overall.get("change_amount"), unit, change=True),
            f"相对变化 {change_rate:+.2%}" if change_rate is not None else "",
        ),
    )
    with st.container(key="summary_metrics"):
        columns = st.columns(3)
        for index, (label, value, detail) in enumerate(tiles):
            with columns[index], st.container(key=f"summary_metric_{index}"):
                st.metric(label, value)
                if detail:
                    st.caption(detail)


def render_table(
    rows: list[dict[str, Any]], labels: dict[str, str], formats: dict[str, str]
) -> None:
    if not rows:
        return
    fields = list(rows[0])
    columns = {
        key: st.column_config.NumberColumn(labels[key], format=formats[key])
        if key in formats else labels.get(key, key)
        for key in fields
    }
    if not st.session_state.get("use_basic_table"):
        try:
            st.dataframe(rows, hide_index=True, use_container_width=True, column_config=columns)
            return
        except ImportError:
            # The interactive grid needs PyArrow. The underlying analysis already ran.
            st.session_state["use_basic_table"] = True

    headers = "".join(f'<th scope="col">{escape(labels.get(key, key))}</th>' for key in fields)
    body = []
    for row in rows:
        cells = []
        for key in fields:
            value = row.get(key)
            if value is None:
                display = "—"
            elif formats.get(key) == "percent":
                display = f"{value:.2%}"
            elif formats.get(key) == "%+.2f":
                display = f"{value:+,.2f}"
            elif formats.get(key) == "localized":
                display = f"{value:,}"
            else:
                display = str(value)
            cells.append(f"<td>{escape(display)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.html(
        '<div class="workbench-table" tabindex="0" role="region" aria-label="分析数据表">'
        f"<table><thead><tr>{headers}</tr></thead><tbody>"
        + "".join(body) + "</tbody></table></div>"
    )
    st.caption("基础表格 · 当前环境的交互表格不可用")


def render_breakdown(data: dict[str, Any]) -> None:
    if "table_result" in data:
        render_table_result(data["table_result"], data["table_plan"])
        return
    rows = data.get("rows") or []
    if not rows:
        if profile := data.get("profile"):
            st.markdown("### 字段概览")
            render_table(
                [
                    {"字段": item["name"], "类型": item["dtype"], "空值数": item["null_count"]}
                    for item in profile.get("columns", [])
                ],
                {},
                {},
            )
        return
    dimensions = (data.get("plan") or {}).get("dimensions", [])
    unit = (data.get("metric") or {}).get("unit", "")
    if dimensions and all(row.get("change_amount") is not None for row in rows):
        names = " / ".join(DIMENSION_NAMES.get(key, key) for key in dimensions)
        st.markdown(f"### 按{names}拆解")
        if unit == "ratio":
            st.caption("本期减上期，单位为百分点")
        chart_rows = sorted(rows, key=lambda row: row["change_amount"])
        labels = [
            " / ".join("未归类" if row.get(key) is None else str(row[key]) for key in dimensions)
            for row in chart_rows
        ]
        changes = [row["change_amount"] for row in chart_rows]
        plot = go.Figure(go.Bar(
            x=[amount * 100 for amount in changes] if unit == "ratio" else changes,
            y=labels,
            orientation="h",
            marker_color=[
                "#c95153" if amount < 0 else "#15847b" if amount > 0 else "#8795ac"
                for amount in changes
            ],
            customdata=[format_value(amount, unit, change=True) for amount in changes],
            hovertemplate="%{y}<br>变化 %{customdata}<extra></extra>",
        ))
        plot.update_layout(
            height=min(480, max(240, 44 * len(rows) + 70)),
            margin=dict(l=6, r=12, t=8, b=45),
            bargap=0.40,
            font=dict(family="Inter, Microsoft YaHei, sans-serif", color="#40506a", size=12),
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            xaxis=dict(
                gridcolor="#e9edf4", zeroline=True, zerolinecolor="#526584",
                tickformat=",.0f" if unit == "CNY" else ",.2f",
                title=dict(text={"CNY": "变化额（元）", "CNY/order": "变化额（元/单）",
                                 "ratio": "变化（百分点）"}.get(unit, "变化额")),
                automargin=True,
                fixedrange=True,
            ),
            yaxis=dict(autorange="reversed", automargin=True, fixedrange=True),
        )
        st.plotly_chart(
            plot, use_container_width=True, theme=None, config={"displayModeBar": False}
        )
    else:
        st.markdown("### 结果明细")
    field_labels = {
        **DIMENSION_NAMES,
        "current_value": "本期",
        "previous_value": "上期",
        "change_amount": "变化（百分点）" if unit == "ratio" else "变化额",
        "change_rate": "相对变化",
        "decline_contribution_rate": "占负向变化",
        "value": "指标值",
    }
    table = rows
    if unit == "ratio" and "change_amount" in rows[0]:
        table = [
            {**row, "change_amount": row["change_amount"] * 100}
            if row.get("change_amount") is not None else row
            for row in rows
        ]
    value_format = "percent" if unit == "ratio" else "localized"
    formats = dict.fromkeys(("current_value", "previous_value", "value"), value_format)
    formats.update(
        change_rate="percent", decline_contribution_rate="percent", change_amount="%+.2f"
    )
    with st.expander("查看结果明细", expanded=not dimensions or "change_amount" not in rows[0]):
        render_table(table, field_labels, formats)


def render_table_result(data: dict[str, Any], plan: dict[str, Any]) -> None:
    operation = plan["operation"]
    st.markdown("### 字段质量" if operation == "profile" else "### 统计结果")
    if plan["filter_column"] is not None:
        value = plan["filter_value"] or "（空白）"
        st.text(f"筛选条件 · {plan['filter_column']} = {value}")
    if not data["rows"]:
        st.info("没有符合条件的分组记录。")
        return
    labels = {
        "name": "字段",
        "null_count": "空白数",
        "distinct_count": "非空不同值数",
        "group": plan["group_by"] or "分组",
        "value": OPERATIONS[operation],
        "valid": "有效数值数",
    }
    render_table(data["rows"], labels, {})


def render_replay(replay: dict[str, Any]) -> None:
    data = replay.get("data", {})
    if not replay.get("ok"):
        st.error((replay.get("error") or {}).get("message") or "重放执行失败")
        return
    if data.get("identical"):
        st.success("重放一致")
    elif data.get("changes", {}).get("result") is False:
        st.warning("结果哈希相同，证据版本有变化")
    else:
        st.warning("重放发现差异")
    for dimension, changed in data.get("changes", {}).items():
        st.caption(f"{DIFF_LABELS.get(dimension, dimension)} · {'有变化' if changed else '一致'}")


def render_audit(result: dict[str, Any], app: DesktopApp) -> None:
    st.markdown("### 执行审计")
    if events := result.get("events", result.get("tool_trace", [])):
        items = []
        for event in events:
            ok = event.get("ok", event.get("result", {}).get("ok", False))
            label = escape(str(event.get("label", event.get("name", "工具"))))
            status_class, status_label = ("ok", "成功") if ok else ("failed", "失败")
            items.append(
                f'<li><span>{label}</span><span class="audit-{status_class}">'
                f'{status_label}</span></li>'
            )
        st.html('<ul class="audit-list">' + "".join(items) + "</ul>")
    if snapshot := result.get("snapshot_id"):
        st.caption("分析快照")
        st.code(snapshot, language=None)
        replay_action, report_action = st.columns(2, gap="small")
        if replay_action.button("重放", use_container_width=True):
            with st.spinner("正在重放…"):
                st.session_state["replay"] = app.replay(snapshot)
        try:
            report = app.report(snapshot)
            report_action.download_button(
                "下载报告", report.read_bytes(), report.name, "text/markdown",
                use_container_width=True,
            )
        except (OSError, RuntimeError) as exc:
            st.error(f"报告导出失败 · {exc}")
        if replay := st.session_state.get("replay"):
            render_replay(replay)
    if citations := result.get("citations"):
        with st.expander("证据引用"):
            for citation in citations:
                st.write(citation.get("label", "证据"))
                st.caption(f"{citation.get('source', '')} {citation.get('locator') or ''}")
                if sql := (citation.get("metadata") or {}).get("sql"):
                    st.code(sql, language="sql")
    with st.expander("原始结果"):
        st.code(json.dumps(result, ensure_ascii=False, indent=2, default=str), language="json")


def render_result(result: dict[str, Any], app: DesktopApp) -> None:
    if result.get("status") == "clarification":
        render_clarification(result, app)
        return
    data = result.get("data") or {}
    with st.container(key="result_panel"):
        st.markdown("### 分析结论")
        if result.get("status") == "error":
            st.error(result.get("answer") or "分析执行失败。")
        elif result.get("status") == "unsupported":
            st.warning(result.get("answer") or "该问题超出当前数据范围。")
        else:
            st.markdown(result.get("answer", ""))
        if result.get("tool_budget_exhausted"):
            st.info("工具步数已用尽，请核对现有证据。")
    render_metrics(data)
    if data.get("rows") or data.get("profile") or "table_result" in data:
        with st.container(key="result_detail"):
            breakdown, audit = st.columns([1.85, 1], gap="medium")
            with breakdown, st.container(key="breakdown_panel"):
                render_breakdown(data)
            with audit, st.container(key="audit_panel"):
                render_audit(result, app)
    else:
        with st.container(key="audit_panel"):
            render_audit(result, app)


def main() -> None:
    st.html(Path(__file__).with_name("workbench.css"))
    app = desktop_app()
    settings = get_settings()
    render_sidebar(app)
    mode = "离线演示" if settings.llm_mode == "mock" else f"真实模型 · {settings.llm_model}"
    st.html(
        '<header class="workbench-heading"><div><h1>数据分析工作台</h1>'
        '<p>导入表格，检查数据质量并核对统计结果</p></div>'
        f'<span class="workbench-mode"><span></span>{escape(mode)}</span></header>'
    )
    render_question(app)
    if result := st.session_state.get("result"):
        render_result(result, app)


main()
