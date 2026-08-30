# BUG-015：模型返回畸形 tool-call JSON 时整个分析会话崩溃

- 日期：2026-08-30
- 模块：live 模型适配器（agent/model.py）
- 级别：P1
- 状态：已修复

## 现象

live 模式下模型输出的 `tool_calls[].arguments` 偶尔不是合法 JSON（长参数、
中文转义或限流截断时更常见）。`OpenAIChatAdapter.turn` 与
`OpenAIModelAdapter.turn` 直接 `json.loads`，`JSONDecodeError` 未捕获，
一路冒泡到 Streamlit 显示"分析失败：Expecting property name ..."，
本次提问彻底失败且无法自愈。这是全链路里唯一绕过 ToolRegistry 错误
边界的未捕获路径。

## 根因

JSON 解析发生在适配器层，位于工具注册表 `except Exception` 边界之外；
解析失败后既没有降级也没有把失败信息回传给模型。

## 修复与验证

- 新增 `_parse_arguments`：解析失败时返回带 `arguments_error` 的
  `ToolCall`（`arguments` 置空 dict），不再抛异常。
- 新增 `_invalid_arguments_result`：把畸形参数包装成
  `BAD_PARAMS`/"malformed JSON arguments" 的失败 ToolResult。
- 两条循环（`ModelToolLoop.execute_calls`、`ChatToolLoop` 内联执行）遇到
  带 `arguments_error` 的调用都走失败结果路径，错误内容回传给模型，
  模型可在剩余步数内自行纠正后重新调用。

新增回归测试：Chat 与 Responses 两个适配器各一条"首次坏 JSON、第二次
正常作答"的用例，断言会话恢复 completed 且 trace 中有 BAD_PARAMS 失败
记录。验证：13 个适配器/Agent 测试全部通过。
