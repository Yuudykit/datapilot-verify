# DataPilot Verify

DataPilot Verify 支持本地表格分析和订单经营指标分析。通用表格按导入列执行可复核的统计，经营指标由 DuckDB 按统一口径计算。成功的分析保存计划和证据版本，支持重放核对。

## 快速演示

在仓库根目录执行。Windows 上已有项目内的 `.conda-env` 时，直接使用其中的解释器。

```powershell
.\.conda-env\python.exe scripts/run_demo.py
```

首次克隆后，在 Windows PowerShell 中用 Python 3.11 创建独立环境并运行演示。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[agent,ui,dev]"
.\.venv\Scripts\python.exe scripts/run_demo.py
```

如果当前的 `python` 已指向 Python 3.11，也可以用 `python -m venv .venv` 创建环境。

演示使用仓库自带的 **3,123 条合成订单和 11 家门店**，无需模型 API Key。运行后会打印结论、快照 ID 和重放结果，并将明细及 Markdown 报告写入 `artifacts/demo/`。分析、重放或导出失败时，命令会以非零状态退出。

Windows 上可用以下命令启动离线界面。脚本优先使用仓库内的 `.conda-env` 或 `.venv`。

```powershell
.\scripts\start_desktop.ps1 -Mock
```

手动启动时，请使用已激活的项目环境中的 Python。

```powershell
$env:DATAPILOT_LLM_MODE = "mock"
python -m streamlit run webapp/streamlit_app.py --server.address 127.0.0.1 --server.port 8767
```

打开 [本地界面](http://127.0.0.1:8767) 后可以走完以下流程。

1. 点 **开始分析**，查看默认问题「7 月净销售额为什么下降？」的结果。净销售额从 **908,631** 降到 **798,458**，环比 **−12.13%**。华东变化额为 **−113,950**，是下降最多的区域。区域拆解解释变化额的构成，业务原因需要结合额外证据。
2. 点 **重放**核对四项差异，或下载 Markdown 审计报告。结果哈希相同但证据版本变化时，界面会明确提示。
3. 把问题改成「7 月销售额为什么下降？」，确认指标口径后继续。mock 工作流会保存澄清状态，确认后从中断处恢复。

## 实现

| 能力 | 实现 |
| --- | --- |
| 工具编排与状态 | mock 模式使用 LangGraph 确定性路由与 SQLite 检查点。live 模式使用有步数预算的模型工具循环。两个入口共用工具注册表、参数校验、结构化错误和调用 ID。 |
| 指标口径与检索 | YAML 定义净销售额、退款率和客单价。口径文档用 BM25 与字符 n-gram 哈希向量混合检索，返回引用。 |
| 数据计算 | Pydantic 校验 `AnalysisPlan`，编译器生成参数化 SQL。DuckDB 执行前检查门店键非空且唯一，避免关联放大销售额。整体比率按同一口径重新聚合。 |
| 审计与重放 | 快照记录数据哈希、指标版本及语义文件哈希、知识版本、计划、SQL 和分组结果哈希。重放在当前工作区运行原计划，四项均无变化且执行成功时才报告一致。 |

## 分析自己的表格

1. 在侧栏的 **导入数据** 里选 **通用表格**，上传 CSV 或 Excel。Excel 可以指定工作表；标题或说明在表头上方时，填写实际表头行号。
2. 导入后页面会选中新表。可以问 `检查数据质量`、`按状态统计数量`、`状态=待投的记录数` 或 `计算金额的合计`，把示例字段换成自己的列名。
3. 也可以展开 **按字段配置**，直接选择分组、数值字段或等值筛选。支持记录数、合计、平均值、最小值和最大值。

通用表格在本地执行，按单张工作表处理。整行空白会被跳过；数值汇总跳过空白单元格，遇到非数值内容会报出具体字段。Excel 公式使用文件中保存的计算值。每次通用分析保存表格来源、结构化计划、数据哈希和结果哈希。

[LangGraph 工作流](src/datapilot_verify/agent/graph.py) · [SQL 编译器](src/datapilot_verify/compiler/sql.py) · [证据与重放](src/datapilot_verify/tools/artifacts.py) · [架构说明](docs/ARCHITECTURE.md)

## 验证

```powershell
python -m pytest
python -m datapilot_verify.eval.runner
```

- **回归测试**覆盖通用表格导入与分析、口径澄清、SQL 执行、API、模型协议适配、门店键异常、证据变更和明细表降级。
- **Golden Set 8/8** 包含 4 项指标解析、3 项口径检索和 1 项使用固定计划的 SQL 分析。SQL 分析核对两个月的总额、总变化额及四个区域的变化额。`numeric_consistency` 表示计算结果的数值自洽性，真实模型的选工具能力和最终回答质量需要单独评测。
- [GitHub Actions 配置](.github/workflows/checks.yml)定义了 Windows 上的安装、静态检查、回归测试、Golden Set、命令行演示和 MCP 入口检查。

## 数据与运行范围

- 在导入方式中选择替换经营订单明细或门店维表，可使用项目原有的经营指标。内置 [订单样例](data/sample/orders.csv) 和 [门店样例](data/sample/stores.csv) 可用作模板。支持 CSV 和 XLSX，旧版 XLS 需要额外安装 `xlrd`。
- 导入数据保存在被 Git 忽略的 `workspace/`。首次启动会补齐缺少的样例文件。快照记录哈希，重放使用当前数据。复核旧版本时需要自行保留对应的源数据。
- 项目按本机单用户使用设计，服务监听 `127.0.0.1`。Python 分析工具的 AST 检查和子进程超时用于约束常见误用。项目尚无生产负载与多用户隔离验证。
- 如需测试真实模型，可将 [`.env.example`](.env.example)复制到仓库根目录的 `.env`，配置 `DATAPILOT_LLM_MODE=live` 及模型、端点、API Key 后重启。若 PowerShell 已设置 `DATAPILOT_LLM_MODE=mock`，先移除该环境变量。live 模式会向配置的模型端点发送问题及工具上下文。
- 本地 API 可通过 `python -m uvicorn webapp.api:app --host 127.0.0.1 --port 8766` 启动，在 [Swagger](http://127.0.0.1:8766/docs) 试用分析、证据查询、重放和导出。

## 可选的 MCP 入口

在项目环境中安装 MCP 扩展，然后从仓库根目录启动 stdio 服务。以下命令使用内置样例数据。

```powershell
python -m pip install -e ".[mcp]"
python -m datapilot_verify.mcp_server --workspace data/sample
```

在本机 MCP 客户端中配置项目环境的 Python 路径和上述启动参数。默认暴露数据检查、口径解析、知识检索、SQL 分析、证据读取和图表生成工具。使用 `--expose` 加工具名称可缩小可调用范围。

[运行逻辑](docs/RUNTIME_LOGIC.md) · [问题记录](docs/BUGLOG.md) · [MIT License](LICENSE)
