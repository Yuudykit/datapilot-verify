# BUG-008 LangGraph 工具重复执行

## 影响

LangGraph 的 `run_analysis` 节点最初复用 `OfflineAgent.ask()`。该方法会从指标解析开始重跑整条链路，导致 `resolve_metric` 和 `search_metric_docs` 各执行两次，审计事件与真实调用次数不一致。

## 复现

执行明确口径的问题后检查事件列表，修复前会出现重复的知识工具事件。

## 根因

图节点复用了面向完整请求的编排入口，而不是直接调用节点所属的领域 Tool。

## 修复

`run_analysis` 节点直接构造 `AnalysisPlan` 并通过 `ToolRegistry.execute()` 调用已有的 `run_analysis` Tool。图中的每个节点现在只负责一个阶段。

## 验证

- 新增 `tests/test_langgraph_agent.py`。
- 明确口径链路严格为 `resolve_metric -> search_metric_docs -> run_analysis`。
- 歧义口径可通过 LangGraph interrupt/checkpoint 恢复。
- 全量测试 34 项通过。
