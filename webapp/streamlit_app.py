from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import plotly.express as px
import streamlit as st

from datapilot_verify.config import get_settings
from webapp.desktop import DesktopApp

ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="DataPilot Verify", page_icon="◈", layout="wide")


@st.cache_resource
def desktop_app() -> DesktopApp:
    return DesktopApp(ROOT)


app = desktop_app()
settings = get_settings()

st.title("DataPilot Verify")
st.caption(f"本机单用户 · {settings.llm_mode.upper()} · {settings.llm_model}")

with st.sidebar:
    st.subheader("数据工作区")
    role = st.selectbox(
        "数据角色",
        ["orders", "stores"],
        format_func=lambda x: "订单明细" if x == "orders" else "门店维表",
    )
    uploaded = st.file_uploader("上传 CSV / Excel", type=["csv", "xlsx", "xls"])
    if uploaded is not None and st.button("导入工作区", use_container_width=True):
        try:
            profile = app.upload(uploaded.name, uploaded.getvalue(), role)
            st.success(f"已替换 {profile['filename']}（{profile['row_count']:,} 行）")
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("已注册数据")
    for profile in app.datasets():
        st.write(f"**{profile['filename']}** · {profile['row_count']:,} 行")
        with st.expander("字段"):
            st.write("、".join(item["name"] for item in profile["columns"]))

question = st.text_area(
    "经营问题",
    value="7 月净销售额为什么下降？",
    height=90,
    placeholder="例如：按渠道看退款率变化、检查订单数据质量……",
)
if st.button("开始分析", type="primary", use_container_width=True) and question.strip():
    # Clear the previous answer before starting a new request. Otherwise a failed
    # or interrupted request would leave the old answer rendered below the new question.
    st.session_state.pop("result", None)
    st.session_state.pop("replay", None)
    with st.spinner("Agent 正在执行工具并验证结果…"):
        try:
            st.session_state["result"] = app.analyze(question)
        except Exception as exc:
            st.error(f"分析失败：{exc}")

def _render_clarification(result: dict[str, Any], app: DesktopApp) -> None:
    options = result.get("clarification", {}).get("options", [])
    if not options:
        st.warning(result.get("answer", "需要补充信息后才能继续。"))
        return
    st.info("问题中的指标存在多个口径，请先确认本次分析采用哪一个：")
    labels = {item["label"]: item["value"] for item in options}
    choice = st.selectbox("分析口径", list(labels), key="clarify_choice")
    if st.button("确认口径并继续", type="primary"):
        with st.spinner("Agent 正在按确认的口径继续执行…"):
            try:
                st.session_state["result"] = app.resume(
                    result["thread_id"], labels[choice]
                )
                st.rerun()
            except Exception as exc:
                st.error(f"分析失败：{exc}")


result = st.session_state.get("result")
if result and result.get("status") == "clarification":
    _render_clarification(result, app)
elif result:
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("结论")
        if result.get("status") == "completed":
            st.success("分析完成")
        else:
            st.warning(result.get("status", "unknown"))
        if result.get("tool_budget_exhausted"):
            st.info("分析已使用全部 Tool 步数；结论由现有成功证据生成。")
        st.markdown(result.get("answer", ""))
        data = result.get("data", {})
        rows = data.get("rows", [])
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
            dimension = next(
                (
                    key
                    for key in rows[0]
                    if key
                    not in {
                        "current_value",
                        "previous_value",
                        "change_amount",
                        "change_rate",
                        "decline_contribution_rate",
                    }
                ),
                None,
            )
            if dimension and "change_amount" in rows[0]:
                figure = px.bar(
                    rows,
                    x=dimension,
                    y="change_amount",
                    color="change_amount",
                    color_continuous_scale=["#b23a48", "#e7eaed", "#217a53"],
                )
                figure.update_layout(
                    height=340,
                    coloraxis_showscale=False,
                    margin=dict(l=10, r=10, t=20, b=10),
                )
                st.plotly_chart(figure, use_container_width=True)
    with right:
        st.subheader("执行审计")
        for item in result.get("events", result.get("tool_trace", [])):
            status = "成功" if item.get("ok", item.get("result", {}).get("ok", False)) else "失败"
            st.write(f"**{item.get('label', item.get('name', 'tool'))}** · {status}")
        snapshot_id = result.get("snapshot_id")
        if snapshot_id:
            st.caption("分析快照")
            st.code(snapshot_id, language="text")
            action_a, action_b = st.columns(2)
            if action_a.button("重放", use_container_width=True):
                st.session_state["replay"] = app.replay(snapshot_id)
            report_path = app.report(snapshot_id)
            action_b.download_button(
                "下载报告",
                data=report_path.read_bytes(),
                file_name=report_path.name,
                mime="text/markdown",
                use_container_width=True,
            )
        replay = st.session_state.get("replay")
        if replay:
            if replay.get("data", {}).get("identical"):
                st.success("重放一致")
            else:
                st.warning("重放发现差异")
            st.json(replay.get("data", {}).get("changes", {}))
        with st.expander("证据引用"):
            for citation in result.get("citations", []):
                st.write(f"**{citation.get('label', citation.get('kind', '证据'))}**")
                st.caption(f"{citation.get('source', '')} {citation.get('locator', '')}")
        with st.expander("原始结果"):
            st.code(json.dumps(result, ensure_ascii=False, indent=2, default=str), language="json")

st.divider()
st.caption("所有分析均受 Tool、SQL/Python 策略和证据链约束；贡献拆解不代表因果关系。")
