# BUG-026：BAD_PARAMS 错误详情携带异常实例，序列化时自身崩溃

- 日期：2026-08-30
- 模块：tools/base.py（错误边界）
- 级别：P1
- 状态：已修复

## 现象

live 模式下模型提交了不合法的 `AnalysisPlan`（如 contribution 缺少
comparison），工具边界返回 BAD_PARAMS 后，`ToolResult.model_dump(mode="json")`
直接抛 `PydanticSerializationError: Unable to serialize unknown type:
<class 'ValueError'>`，整个分析请求崩溃，界面显示
"分析失败：Unable to serialize unknown type ..."。

## 根因

pydantic v2 的 `ValidationError.errors()` 默认包含 `ctx`，其中
`ctx["error"]` 是校验器抛出的**异常实例**（如 ValueError），无法按 JSON
序列化。该 details 进入 ToolError 后，任何 `model_dump(mode="json")`
调用（工具循环回传、API 返回）都会崩溃。这是基线代码的潜伏缺陷，
BUG-025 修复后模型真正开始提交 run_analysis 参数，才被触发。

## 修复与验证

错误边界改为 `exc.errors(include_url=False, include_context=False)`，
剔除 ctx 中的异常实例，只保留 type/loc/msg/input 等可序列化字段。
新增回归测试 `test_registry_bad_params_details_stay_json_serializable`：
非法参数返回 BAD_PARAMS 且 `model_dump(mode="json")` 不再抛异常。
验证：87 个测试通过，全项目 ruff 通过。
