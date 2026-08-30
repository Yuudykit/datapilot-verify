# BUGLOG

| ID | 日期 | 模块 | 级别 | 状态 | 根因 | 档案 |
|---|---|---|---|---|---|---|
| BUG-001 | 2026-08-30 | Conda 环境 | P1 | 已修复 | 默认包缓存和环境注册目录不可写 | [BUG-001](bugs/BUG-001-conda-cache-permission.md) |
| BUG-002 | 2026-08-30 | 依赖安装 | P1 | 部分缓解 | PyPI/国内镜像链路不稳定，大依赖下载超时 | [BUG-002](bugs/BUG-002-pip-resolver-backtracking.md) |
| BUG-003 | 2026-08-30 | 样例数据 | P1 | 已修复 | 植入的 7 月下降信号未达到演示目标 | [BUG-003](bugs/BUG-003-sample-signal-too-weak.md) |
| BUG-004 | 2026-08-30 | Windows CLI | P1 | 已修复 | Python stdout 与终端解码不一致导致中文乱码 | [BUG-004](bugs/BUG-004-windows-stdout-encoding.md) |
| BUG-005 | 2026-08-30 | pytest | P1 | 已修复 | 默认用户 Temp 目录不可访问 | [BUG-005](bugs/BUG-005-pytest-temp-permission.md) |
| BUG-006 | 2026-08-30 | RAG 依赖 | P2 | 已修复 | jieba 源码构建隔离阻塞环境安装 | [BUG-006](bugs/BUG-006-jieba-build-isolation.md) |
| BUG-007 | 2026-08-30 | DuckDB | P1 | 已修复 | CREATE VIEW 的表函数路径不支持预处理参数 | [BUG-007](bugs/BUG-007-duckdb-view-parameter.md) |
| BUG-008 | 2026-08-30 | LangGraph | P1 | 已修复 | 分析节点复用 OfflineAgent 导致知识工具重复执行 | [BUG-008](bugs/BUG-008-langgraph-duplicate-tools.md) |
| BUG-009 | 2026-08-30 | Live LLM | P1 | 已修复 | DeepSeek 不兼容 Responses API 的 Tool 输出回填协议 | [BUG-009](bugs/BUG-009-deepseek-tool-replay.md) |
| BUG-010 | 2026-08-30 | Streamlit | P1 | 已修复 | 页面配置晚于资源初始化，可能阻止界面启动 | [BUG-010](bugs/BUG-010-streamlit-page-config-order.md) |
| BUG-011 | 2026-08-30 | Python Worker | P2 | 已修复 | Windows 子进程非 UTF-8 输出触发解码异常 | [BUG-011](bugs/BUG-011-python-worker-output-encoding.md) |
| BUG-012 | 2026-08-30 | Streamlit | P1 | 已修复 | 新请求失败时复用上一条结果，造成答案残留 | [BUG-012](bugs/BUG-012-stale-streamlit-result.md) |
| BUG-013 | 2026-08-30 | pytest | P1 | 已修复 | 项目内 basetemp 目录 ACL 损坏且清理失败即会话失败 | [BUG-013](bugs/BUG-013-pytest-basetemp-corruption.md) |
| BUG-014 | 2026-08-30 | OfflineAgent | P1 | 已修复 | 比率类指标按分组值求和，整体结论数值错误 | [BUG-014](bugs/BUG-014-offline-ratio-metric-sum.md) |
| BUG-015 | 2026-08-30 | live 模型适配器 | P1 | 已修复 | 模型畸形 tool-call JSON 未捕获，整个会话崩溃 | [BUG-015](bugs/BUG-015-model-adapter-malformed-json.md) |
| BUG-016 | 2026-08-30 | Streamlit / DesktopApp | P1 | 已修复 | 界面无澄清交互，口径确认流程断头 | [BUG-016](bugs/BUG-016-streamlit-clarification-dead-end.md) |
| BUG-018 | 2026-08-30 | DesktopApp | P2 | 已修复 | live 缺 API Key 时静默降级 mock | [BUG-018](bugs/BUG-018-live-missing-key-silent-mock.md) |

## 记录规则

1. 先记录复现方式和影响，再实施修复。
2. 能自动化复现的 bug 必须增加回归测试。
3. 修复完成需记录根因、改动和验证结果。
