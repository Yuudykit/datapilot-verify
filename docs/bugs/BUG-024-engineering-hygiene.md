# BUG-024：工程卫生批次——快照错误码、.tmp 残留、lint 债务与文档漂移

- 日期：2026-08-30
- 模块：tools/artifacts.py、evidence/store.py、data/workspace.py、全项目 lint
- 级别：P3
- 状态：已修复

## 现象

- `get_evidence`/`replay_analysis`/`export_report` 对不存在或非法的快照
  抛异常，被 Tool 边界统一转成 `INTERNAL`，调用方无法区分"快照不存在"
  与"实现出错"。
- `SnapshotStore.save`/`WorkspaceRegistry._save` 在写 `.json.tmp` 与
  `replace` 之间崩溃时会残留写了一半的临时文件。
- 全项目 `ruff check src webapp tests scripts` 有 48 处告警（E501 长行、
  I001 导入排序、UP017、F401、B905 `zip` 无 strict、retriever B023 闭包
  共享循环变量），而 README 的验证命令只定点检查 3 个文件，掩盖了债务。
- README 基线写"54 passed"与实际用例数漂移；未反映口径澄清交互与
  live 缺 Key 报错行为。

## 修复与验证

- 快照工具增加 `_load_snapshot` 统一入口：非法 ID 返回 `BAD_PARAMS`，
  不存在返回 `NOT_FOUND`。
- 两处 `.json.tmp` 写入增加失败清理（`unlink(missing_ok=True)` 后重抛）。
- `SnapshotStore.load` 的 ID 白名单改为类级 `frozenset` 常量，消除超长行。
- retriever 的分节 flush 从闭包改为模块级 `_build_chunk`（消除 B023）。
- `zip` 全部显式 `strict=True`（B905）；其余 E501/I001/UP017/F401 修复
  或重构，全项目 ruff 清零。
- README：验证命令改为全量 ruff，基线更新，补充澄清流程与缺 Key 报错
  说明。

验证：`83 passed`（较修复前基线 55 新增 28 条回归测试），Golden Set
`8/8`，`ruff check src webapp tests scripts conftest.py` 全绿。
