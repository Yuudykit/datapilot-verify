# BUG-013：pytest basetemp 目录 ACL 损坏，测试会话无法启动

- 日期：2026-08-30
- 模块：pytest 测试基础设施
- 级别：P1
- 状态：已修复

## 现象

在项目根目录直接运行 `pytest`（README 的验证命令），会话在 setup 阶段报
18 个 ERROR：`TempPathFactory` 清理 `--basetemp=.pytest-tmp` 时
`os.rmdir` 抛 `PermissionError: [WinError 5]`。`icacls`/`takeown` 对
`.pytest-tmp`、`.pytest_cache`、`.pytest-tmp2` 连读权限都被拒绝，普通
Administrator 无法删除或修复；同目录下新建目录可正常删除，证明是这几个
历史沙箱进程留下的目录本身异常，不是环境策略。BUG-005 的修复只是把
basetemp 从系统 Temp 移进项目目录，没有对"目录损坏"做任何兜底，因此
复发时整个套件被阻断。

## 根因

`--basetemp` 固定指向项目内单一目录；pytest 会话启动时无条件
`rmtree(basetemp)`，删除失败即失败。目录 ACL 损坏后没有第二条路可走。

## 修复与验证

新增根目录 `conftest.py`：会话配置阶段先探测 basetemp 是否可清空，
清不掉时按 `.pytest-tmp-fallback`、`.pytest-tmp-fallback2` 依次重定向，
并同步改写已创建的 `TempPathFactory._given_basetemp`；全部后备目录也不
可用时才报错退出。`.pytest_cache` 的写入失败只产生非致命告警，cacheprovider
的配置读取先于 conftest 钩子，无法在会话内重定向，档案记录为外观问题，
需在沙箱外手动删除 `.pytest_cache` 消除。

验证：`pytest` 直接运行恢复为 `55 passed`（仅剩 cache 告警）。
