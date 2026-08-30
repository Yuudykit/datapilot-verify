# BUG-023：API 各端点数据面不一致，上传的数据集永远无法被分析

- 日期：2026-08-30
- 模块：webapp/api.py
- 级别：P2
- 状态：已修复

## 现象

- `/api/datasets` 把上传文件注册到 `artifacts/api-workspace`，但
  `/api/analyze` 的图与 `/api/agent` 的 live 循环始终读 `data/sample`——
  通过 API 上传的数据集永远无法被分析。
- `/api/evidence`、`/api/replay`、`/api/report` 使用 `GRAPH.context`
  （sample + artifacts/langgraph），与 `/api/analyze` 生成快照的目录
  混用，历史快照归属不清。
- `/api/agent` 的 live 返回是工具循环原始输出，缺少
  `events/citations/data/snapshot_id`，与 `/api/analyze` 的返回结构
  不一致。

## 根因

API 模块没有统一的会话数据面：图实例、注册表与各端点各自绑定不同的
工作区/产物目录；live 归一化逻辑只存在于 DesktopApp。

## 修复与验证

- API 启动时为 `api-workspace` 补齐样例种子；`GRAPH.context` 显式绑定
  `api-workspace/api-output`，`_context()` 不再借用图实例的内部状态。
- `DesktopApp._normalize_live` 的主体抽取为模块级
  `normalize_live_result(question, result, workspace, output_dir)`，
  `/api/agent` 的 live 路径复用，返回结构与 `/api/analyze` 对齐，
  快照统一写入 `artifacts/api-output/snapshots`。

验证：test_fastapi 全链路（analyze→evidence→replay）与桌面端 11 个
测试通过；上传→分析现在作用于同一数据面。
