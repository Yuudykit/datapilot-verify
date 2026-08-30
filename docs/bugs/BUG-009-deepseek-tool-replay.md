# BUG-009 DeepSeek Tool 输出回填协议不兼容

## 影响

DeepSeek 兼容端点可以返回 Tool Call，但使用 Responses API 的 `previous_response_id` 和 `function_call_output` 回填时返回 HTTP 400，无法完成第二轮。

## 根因

配置端点实现的是 OpenAI Chat Completions Tool Calling 兼容协议，并未完整实现 Responses API 的 Tool replay 语义。

## 修复

- OpenAI 原生/Responses 兼容端点继续使用 `OpenAIModelAdapter`。
- DeepSeek 端点使用 `OpenAIChatAdapter`。
- 回填时保留完整 assistant tool call，并追加 `role=tool`、`tool_call_id` 和序列化 `ToolResult`。
- 两种协议共用 ToolRegistry、权限边界、步数预算和审计结构。

## 验证

- 离线假客户端完成两轮 Tool Call 回填测试。
- live 最小问题成功调用 `inspect_dataset` 并回答 3,123 行。
- live 主问题在 6 个模型轮次中完成 12 次 Tool 调用，所有 ToolResult 均成功。
