# 项目运行逻辑

## 用户入口

`scripts/start_desktop.ps1` 使用固定的 `D:\datapilot-verify\.conda-env` 启动
`webapp/streamlit_app.py`，监听 `127.0.0.1:8767`。页面初始化一个缓存的
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

用户在页面选择 `orders` 或 `stores` 角色并上传 CSV/Excel。`DesktopApp.upload` 校验扩展名
和必需列，Excel 转成 UTF-8 CSV，覆盖 `workspace/orders.csv` 或 `workspace/stores.csv`。
`data/sample/` 只作为缺文件时的初始化模板，不参与业务数据覆盖。

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

## 运行时保留清单

必须保留：`.env`、`.env.example`、`pyproject.toml`、`requirements*.txt`、`environment.yml`、
`src/`、`webapp/streamlit_app.py`、`webapp/desktop.py`、`data/`、`workspace/`、
`scripts/start_desktop.ps1` 和 `artifacts/desktop/`。

可再生但暂未删除：`.conda-pkgs`、Python `__pycache__`、pytest/Ruff 缓存、安装日志和旧的
API/演示/测试 artifacts。它们不属于运行链路，但删除动作因 Windows 审批服务 503 未执行。
