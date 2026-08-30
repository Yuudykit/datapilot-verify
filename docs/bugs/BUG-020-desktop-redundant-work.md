# BUG-020：桌面端每次分析/重渲染都重建整条链路并重复导出报告

- 日期：2026-08-30
- 模块：DesktopApp / Streamlit
- 级别：P2
- 状态：已修复

## 现象

- 每次点击"开始分析"都执行一次 `build_graph`：重新解析 metrics.yml、重建
  混合检索器（分词 + BM25 + embedding），新开一个永不显式关闭的 sqlite
  checkpoint 连接。单用户场景下这些对象在整个应用生命周期内只需一份。
- 侧边栏每次 Streamlit 重渲染都对工作区全部 CSV 重新读取、逐列统计并整
  文件 SHA-256，数据量增大后每次点击按钮都会卡顿。
- 结果显示期间，任何一次重渲染（包括点击"重放"）都会重新执行
  `export_report` 重写报告文件。
- `artifacts/langgraph/checkpoints.sqlite` 及历史快照目录只增不减。

## 根因

`DesktopApp` 没有任何会话级缓存；Streamlit 的脚本重执行模型放大了重复
开销。

## 修复与验证

- `DesktopApp._mock_graph()` 惰性构建并复用同一 LangGraph 实例，
  `analyze`/`resume` 共用（单实例长连接不再泄漏；同一进程内澄清恢复
  也因此更直接）。
- `datasets()` 以文件名 + mtime_ns + size 作为签名缓存档案，文件被替换
  （上传）后自动失效。
- `report()` 在报告文件已存在且 snapshot_id 合法时直接复用，不再重复导出。

新增两条缓存行为回归测试（档案计数、报告执行计数）。验证：桌面端
8 个测试通过，全量测试无回归。
