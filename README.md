# DataPilot Verify

DataPilot Verify 是本机单用户经营分析软件：导入订单与门店数据，用自然语言提问，Agent
调用指标语义、RAG、SQL/Python 执行和数值校验工具，返回带审计证据的结论，并生成可重放
快照与 Markdown 报告。普通用户入口是 Streamlit：<http://127.0.0.1:8767>；FastAPI
仅用于开发和自动化联调。

## 快速启动

固定使用 `D:\agent-gpt\.conda-env`，不要创建第二个环境。

```powershell
Set-Location D:\agent-gpt
.\scripts\start_desktop.ps1
```

然后打开 <http://127.0.0.1:8767>。启动窗口需保持运行，退出按 `Ctrl+C`。直接启动命令：

```powershell
D:\agent-gpt\.conda-env\python.exe -m streamlit run webapp\streamlit_app.py --server.address 127.0.0.1 --server.port 8767
```

## 配置模型

根目录 `.env` 示例：

```dotenv
DATAPILOT_LLM_MODE=live
DATAPILOT_LLM_MODEL=deepseek-v4-flash
DATAPILOT_LLM_BASE_URL=https://api.deepseek.com
DATAPILOT_LLM_API_KEY=你的APIKey
DATAPILOT_MAX_TOOL_STEPS=8
```

`live` 使用真实模型 Tool Calling，`mock` 使用本地确定性工作流。修改 `.env` 后需重启。
Key 只能放在 `.env`，不要写入 README、源码、日志或 `.env.example`。DeepSeek 使用
Chat Completions 适配器。

## 普通用户流程

1. 启动后左侧会自动显示内置 `orders.csv`、`stores.csv` 样例。
2. 选择“订单明细”或“门店维表”，上传 CSV/XLSX/XLS，点击“导入工作区”。导入只替换
   `workspace/` 中对应角色，不修改 `data/sample/`。
3. 输入问题并点击“开始分析”。例如：
   `7 月净销售额为什么下降？请先核对指标口径，再按区域分析贡献。`
4. 当问题里只写“销售额”这类多口径词时，界面会先弹出口径确认，选择
   “净销售额”或“支付金额”后点击“确认口径并继续”。
5. 查看结论、明细表、图表、Tool 执行审计和证据引用。
6. 出现快照 ID 后点击“重放”检查结果哈希，或点击“下载报告”保存审计报告。

支持的问题示例：

```text
请检查订单数据有多少行，并只返回行数
按渠道比较 6 月和 7 月的退款率变化
净销售额的正式定义是什么？是否扣除退款？
```

## 数据格式

当前版本是订单经营分析专用软件，不是能理解任意 Excel 的通用 BI。额外列可以保留，但
以下列名必须存在。

订单明细 `orders`：`order_id`, `paid_at`, `store_id`, `category`, `channel`,
`paid_amount`, `refund_amount`。

门店维表 `stores`：`store_id`, `region`, `city`。

程序会校验缺失字段；Excel 在本地转为 UTF-8 CSV。建议金额列为数字、时间列为标准日期，
且两表 `store_id` 可关联。上传数据保存在 `D:\agent-gpt\workspace`。

## 结果与边界

- 执行审计列出实际 Tool，失败步骤不会伪装成成功。
- 证据引用包含数据、指标定义、知识文档或查询定位。
- 快照保存数据哈希、指标/知识版本、分析计划、SQL、结果哈希和校验信息。
- “重放一致”表示当前数据下结果哈希一致；数据或定义变化会显示差异。
- 贡献拆解表示数值贡献，不等同于统计因果。
- 未覆盖的问题会明确返回不支持，不编造答案。
- 服务只绑定 `127.0.0.1`，没有账号、权限隔离和多人并发，不适合作为公网多租户服务。
- live 模式会把问题及必要 Tool 上下文发送给配置的模型服务商，敏感数据请先确认合规。

## 开发/测试 API

```powershell
D:\agent-gpt\.conda-env\python.exe -m uvicorn webapp.api:app --host 127.0.0.1 --port 8766
```

Swagger <http://127.0.0.1:8766/docs>、ReDoc `/redoc`、OpenAPI `/openapi.json`。接口包括
`/api/analyze`, `/api/agent`, `/api/datasets`, `/api/evidence`, `/api/replay`, `/api/report`。
普通用户不需要操作 Swagger。`8765` 是早期固定演示页，仅作历史视觉样例。

## 验证与目录

```powershell
D:\agent-gpt\.conda-env\python.exe -m pip check
D:\agent-gpt\.conda-env\python.exe -m pytest
D:\agent-gpt\.conda-env\Scripts\ruff.exe check src webapp tests scripts conftest.py
```

当前基线：`83 passed`，Golden Set `8/8`。主要目录：`webapp/streamlit_app.py`（界面）、
`webapp/desktop.py`（单用户服务）、`src/datapilot_verify/`（Agent/Tool/RAG/执行/证据）、
`workspace/`（用户数据）、`artifacts/desktop/`（快照和报告）、`docs/BUGLOG.md`（修改记录）。

## 常见问题

`8767` 打不开时确认启动窗口仍在运行，并用 `netstat -ano | Select-String ':8767'` 检查
端口。`llm_mode=live` 但 `.env` 缺少 Key 时分析会直接报错提示，不会静默改用 mock；
确认 `.env` 位于 `D:\agent-gpt` 且 Key 存在后重启。导入报缺字段时按上面的 schema
修正表头。要恢复样例，退出后删除 workspace 中对应文件，重新启动会自动补回；
删除业务数据前请备份。

完整修改记录见 [docs/BUGLOG.md](docs/BUGLOG.md) 和 `docs/bugs/`；架构与运行逻辑、
组件职责和设计理由见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
