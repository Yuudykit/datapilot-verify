# BUG-019：Responses 工具循环步数用尽后不尝试总结，已执行的 Tool 结果被浪费

- 日期：2026-08-30
- 模块：OpenAIModelAdapter / ModelToolLoop
- 级别：P2
- 状态：已修复

## 现象

`ModelToolLoop`（Responses 路径）步数用尽时直接返回
`status=budget_exhausted`，而 `ChatToolLoop`（DeepSeek 路径）在同样情形下会
追加一条"只基于已有结果总结"的请求并返回可用的结论。两条 live 路径行为
不对称；Responses 路径上最后一步已经执行的 Tool 结果全部作废，
RUNTIME_LOGIC.md 描述的兜底行为只存在于 Chat 路径。

## 根因

`OpenAIModelAdapter` 没有 finalize 实现，`ModelToolLoop.run` 循环结束后
没有兜底分支。

## 修复与验证

- 步数用尽的总结提示词抽取为模块常量 `FINALIZE_PROMPT`，两条循环共用。
- `OpenAIModelAdapter.finalize(inputs, previous_response_id)`：不带
  `tools` 再请求一次（模型无法再调用工具），请求体携带最后一批
  `function_call_output` 与 `previous_response_id` 以保留上下文。
- `ModelToolLoop.run` 步数用尽后尝试 finalize，成功则返回
  `completed` + `tool_budget_exhausted=True`，失败才回退
  `budget_exhausted`，语义与 ChatToolLoop 完全对齐。

新增回归测试 `test_responses_loop_finalizes_without_tools_at_budget_limit`，
断言兜底请求不含 tools、携带 previous_response_id 与工具输出。验证：
7 个适配器测试全部通过。
