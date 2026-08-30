# BUG-011：Python Worker 非 UTF-8 输出导致分析线程异常

- 日期：2026-08-30
- 模块：受控 Python 执行器
- 级别：P2
- 状态：已修复

## 现象

Windows 本机分析时，子进程输出包含非 UTF-8 字节，父进程 reader thread 抛出
`UnicodeDecodeError`。虽然结果通常已经产生，但会污染日志并让调用方误判执行失败。

## 修复

`subprocess.run` 保持 UTF-8 解码，同时增加 `errors="replace"`。非 UTF-8 的诊断字符会以替换
字符保留，结构化结果标记和错误信息仍可正常解析。

## 验证

全量测试 `54 passed`；桌面 live 链路完成分析、快照、重放和报告导出。
