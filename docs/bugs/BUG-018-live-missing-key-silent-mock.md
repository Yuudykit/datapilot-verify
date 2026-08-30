# BUG-018：live 模式缺少 API Key 时静默降级 mock

- 日期：2026-08-30
- 模块：DesktopApp
- 级别：P2
- 状态：已修复

## 现象

`DATAPILOT_LLM_MODE=live` 但 `.env` 缺少 `DATAPILOT_LLM_API_KEY` 时，
`DesktopApp.analyze` 的条件 `if llm_mode == "live" and llm_api_key` 不成立，
静默走 mock 确定性图。用户以为在用真实模型，实际结果来自脚本工作流，
与 README"分析不调用模型时确认 Key 存在"的排查指引相互矛盾。API 侧
（/api/agent）对同样情形会返回 503，行为不一致。

## 根因

条件判断把"配置为 live"和"配置合法"合并成一个分支，配置非法时
隐式落入 mock。

## 修复与验证

`llm_mode == "live"` 且 Key 缺失时抛出带处置指引的 `ValueError`（配置
Key 后重启，或改用 mock），由界面/API 的既有错误处理呈现。新增
`test_live_mode_without_api_key_fails_loudly` 回归。
