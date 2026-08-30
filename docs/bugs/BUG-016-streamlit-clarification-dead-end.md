# BUG-016：Streamlit 主界面没有澄清交互，口径确认流程断头

- 日期：2026-08-30
- 模块：Streamlit 用户界面 / DesktopApp
- 级别：P1
- 状态：已修复

## 现象

mock 模式下问"7 月销售额为什么下降？"，Agent 图会 interrupt 返回
`status=clarification` 和两个口径选项（净销售额/支付金额）。图与 API 层的
`resume(thread_id)` 链路本身是通的（有专项测试覆盖），但 Streamlit 只把
状态渲染成一个 warning，没有展示选项，也没有任何入口调用
`DesktopApp.resume`。用户在主入口被卡死，只能自己改写问题。

## 根因

Streamlit 只实现了结果展示分支，没有实现 clarification 分支；
`DesktopApp` 也没有暴露 resume 方法。

## 修复与验证

- `DesktopApp` 新增 `resume(thread_id, value)`，与 `analyze` 一样绑定
  用户工作区与桌面产物目录。
- Streamlit 新增 `_render_clarification`：状态为 clarification 时渲染
  口径单选与"确认口径并继续"按钮，确认后调用 `app.resume` 并重跑页面；
  失败显示错误，不残留旧结果。
- 测试夹具补齐 tmp 项目所需的 semantic/knowledge 文件；新增
  `test_clarification_round_trip_through_desktop` 覆盖
  analyze→clarification→resume→completed 全链路。

验证：`streamlit.testing.v1.AppTest` 启动零异常；桌面端 6 个测试通过。
