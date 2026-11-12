# 项目运行逻辑

## 用户入口

`scripts/start_desktop.ps1` 依次查找仓库内的 `.conda-env`、`.venv` 和 PATH 中的 Python，
再启动 `webapp/streamlit_app.py`，监听 `127.0.0.1:8767`。页面初始化一个缓存的
`DesktopApp`，工作区是 `workspace/`，桌面产物是 `artifacts/desktop/`。

## 一次分析的主链路

```text
Streamlit 输入问题
  -> DesktopApp.analyze
  -> live: build_live_tool_loop / mock: build_graph
  -> ToolRegistry 路由工具
  -> 指标语义 + RAG 文档
  -> AnalysisPlan
  -> PlanCompiler 生成只读 SQL
  -> DuckDB 读取 workspace/orders.csv + stores.csv
  -> 数值校验 / 贡献拆解 / EvidenceBinding
  -> 返回答案、rows、events、citations
  -> live 结果归一化并写入 AnalysisSnapshot
  -> 页面展示结论、图表和 Tool 审计
```

## 数据导入

经营分析可上传订单明细或门店维表。`DesktopApp.upload` 校验扩展名和必需列，将数据保存到
`workspace/orders.csv` 或 `workspace/stores.csv`。`data/sample/` 提供缺文件时的初始化模板。
通用表格按选定的工作表和表头导入，在 `workspace/tables/` 保存 UTF-8 CSV 及其元数据。

## Tool 层

`src/datapilot_verify/app.py` 集中组装 ToolRegistry。当前 Tool 分为：数据检查/注册、
指标解析、知识文档检索、`run_analysis`、受控 Python、贡献分析、快照证据、重放和报告导出。
模型只能通过注册表执行工具；每个结果都有 `ok`、`trace_id`、证据、告警或结构化错误。

## 两种执行模式

- `DATAPILOT_LLM_MODE=mock`：使用 LangGraph 确定性图，适合离线回归和无 Key 演示。
- `DATAPILOT_LLM_MODE=live`：使用配置模型进行 Tool Calling。DeepSeek 走 Chat Completions
  循环，Responses 兼容服务走 Responses 循环。达到 Tool 步数上限时会尝试只基于已有结果
  总结，避免丢失已经完成的分析。

## 快照、重放和报告

成功的 live `run_analysis` 会生成快照，记录问题、数据 SHA-256、指标/知识版本、分析计划、
SQL、Tool trace ID、结果哈希和校验状态。点击“重放”时，系统按原 AnalysisPlan 重新执行，
比较数据、语义、知识和结果哈希；点击“下载报告”时把快照导出为 Markdown。

## 其他入口的定位

- `webapp/api.py` / `8766`：开发和自动化 API，不是普通用户入口。
- `webapp/server.py` / `8765`：早期固定视觉演示页，结果不代表当前完整产品链路。
- `tests/`：回归验证，不参与用户运行。
- `artifacts/langgraph`、`artifacts/live`：历史或开发运行状态；桌面用户产物使用
  `artifacts/desktop`。

## 本地配置与产物

离线模式可直接用随仓库发布的样例运行。真实模型的本机配置以 `.env.example` 为模板，
写入 Git 忽略的 `.env`。导入数据与运行产物分别保存在 `workspace/` 和 `artifacts/`，
两者均由 Git 忽略。
