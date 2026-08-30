# DataPilot Verify 架构与运行逻辑

本文回答三个问题：**系统怎么运转**、**每个组件负责什么**、**为什么这么设计**。
与 [RUNTIME_LOGIC.md](RUNTIME_LOGIC.md)（运行时保留清单）互补；历史问题与修复见
[BUGLOG.md](BUGLOG.md)。

---

## 1. 项目定位与四条核心承诺

DataPilot Verify 是**本机单用户**经营分析软件：导入订单/门店数据，用自然语言提问，
Agent 调用工具完成分析，返回带审计证据的结论。

所有设计决策都服务于四条承诺：

| 承诺 | 落点 |
|---|---|
| 数值必须有真实计算依据，不编造 | 所有数值来自 SQL/受控 Python 执行，模型只做叙事 |
| 指标口径有权威定义 | `metrics.yml` 语义库 + RAG 知识文档，回答口径必引用 |
| 结论可审计、可重放 | 每次分析生成快照（数据哈希 + 版本 + SQL + 结果哈希） |
| 诚实失败 | 不支持的问题明确拒绝；校验不过不伪装成功；数据缺失如实说明 |

---

## 2. 整体分层

```
┌─ 接入层 ─────────────────────────────────────────────┐
│ streamlit_app.py（用户界面）  api.py（开发 API）  server.py（旧演示页） │
└──────────────┬───────────────────────────────────────┘
┌─ 服务层 ─────▼───────────────────────────────────────┐
│ DesktopApp：会话编排、live 结果归一化、快照落盘、报告/重放入口          │
└──────────────┬───────────────────────────────────────┘
┌─ Agent 层 ────▼───────────────────────────────────────┐
│ mock：LangGraph 确定性图（graph.py）                     │
│ live：模型工具循环（model.py，Chat/Responses 双适配器）     │
│ 测试：OfflineAgent（offline.py）                        │
└──────────────┬───────────────────────────────────────┘
┌─ 工具层 ──────▼───────────────────────────────────────┐
│ ToolRegistry（app.py 组装）：Pydantic 校验 + stage 允许清单      │
│ + trace_id + 统一错误边界；11 个工具                          │
└──────────────┬───────────────────────────────────────┘
┌─ 能力层 ──────▼───────────────────────────────────────┐
│ PlanCompiler(SQL 生成+校验)  DuckDB 引擎  Python 沙箱          │
│ 语义库(metrics.yml)  RAG 检索  贡献拆解  数值校验               │
└──────────────┬───────────────────────────────────────┘
┌─ 数据层 ──────▼───────────────────────────────────────┐
│ workspace/*.csv（用户数据）  data/semantic+knowledge（口径与知识）  │
│ artifacts/desktop/snapshots（快照与报告）                       │
└───────────────────────────────────────────────────────┘
```

---

## 3. 一次分析的完整运行逻辑

### 3.1 mock 模式（确定性图，无 Key 演示与回归基线）

```
streamlit 输入问题
→ DesktopApp.analyze()：llm_mode=mock（或缺 Key 时显式报错）
→ DataPilotGraph.invoke()（LangGraph 状态机）
   1. resolve_metric 节点：语义库解析问题中的指标
   2. _route_after_metric 按优先级路由：
      数据检查(字段/多少行/数据质量) → 口径歧义澄清(销售额≠净销售额)
      → 分析意图(下降/变化/比较/为什么) → 口径问答(定义/口径) → 兜底
   3a. inspect_dataset：按问题选 orders.csv / stores.csv，返回画像
   3b. clarify_metric：interrupt 暂停图执行，返回口径选项 + thread_id
   3c. search_docs → run_analysis（见 3.3），生成结论与快照
   3d. answer_metric：只返回口径定义文本并引用知识文档
→ 页面渲染结论、明细表、贡献图表、工具审计、证据引用
```

**澄清-恢复流程**：`clarify_metric` 节点用 LangGraph `interrupt()` 暂停，
结果携带 `thread_id` 和选项；用户在界面确认口径后，`DesktopApp.resume()`
以 `Command(resume=value)` 恢复同一线程，图从断点继续执行。检查点持久化在
`artifacts/langgraph/checkpoints.sqlite`，跨实例重建也能恢复。

### 3.2 live 模式（真实模型 Tool Calling）

```
DesktopApp.analyze()
→ llm_mode=live 且有 Key（缺 Key 直接 ValueError，不静默降级）
→ build_live_tool_loop()：base_url 含 deepseek → ChatToolLoop
                          其他 Responses 兼容服务 → ModelToolLoop
→ 循环（最多 DATAPILOT_MAX_TOOL_STEPS 步）：
   1. 模型收到系统提示词 + 工具 schema，产出文本或 tool_calls
   2. 解析 arguments（畸形 JSON 记为 arguments_error，不崩溃）
   3. ToolRegistry.execute() 逐个执行，结果按 call_id 回传模型
   4. 模型看到成功结果/失败原因，自纠或继续，直到不再调用工具
→ 步数耗尽：finalize 兜底——不带 tools 再问一次"只基于已有结果总结"，
  避免浪费已执行的证据
→ normalize_live_result()：抽取 run_analysis 的 rows/metric/evidence
  归一化成与 mock 一致的返回结构，成功的 run_analysis 落快照
```

### 3.3 run_analysis 工具内部（两条模式的公共终点）

```
入参：AnalysisPlan（Pydantic 强校验：期间不重叠、维度在指标允许清单内…）
→ SemanticRepository.get(metric)：取出指标表达式（如 sum(paid_amount - refund_amount)）
→ PlanCompiler.compile()：生成参数化 SQL（双 CTE 环比 + FULL OUTER JOIN 对齐分组）
→ SqlPolicy.validate()：sqlglot 解析，仅允许单条 SELECT，黑名单拦截写操作
→ DuckDBEngine.execute()：内存连接读入两个 CSV 为表，执行 SQL，返回行 + 结果哈希
→ 若有环比：verify_comparison_rows 校验每行 change/change_rate 自洽、有限性
→ 若 analysis=contribution：enrich_contribution 计算下降贡献率
→ 另跑一次无维度聚合得到 overall（整体值，比率类指标必需）
→ 组装证据（metric/query/result 三类 EvidenceRef）与逐值 EvidenceBinding
```

---

## 4. 组件职责明细

### 接入层

| 组件 | 职责 | 关键行为 |
|---|---|---|
| `webapp/streamlit_app.py` | 用户界面 | 渲染结论/图表/审计/证据；口径澄清交互（`_render_clarification`）；新请求前清理旧结果防残留；展示重放对比 |
| `webapp/desktop.py` | 单用户服务编排 | `analyze`（选模式）、`resume`（澄清恢复）、`upload`（角色校验+缺字段检查+Excel 转 CSV）、`datasets`（带缓存的档案）、`replay`/`report`（报告文件复用）；`normalize_live_result` 把 live 原始输出归一化成统一结构并落快照 |
| `webapp/api.py` | 开发联调 API | `/api/analyze|agent|datasets|evidence|replay|report`；数据面统一到 `artifacts/api-workspace`（启动时补样例种子）；live 返回结构与桌面端对齐 |
| `webapp/server.py` | 8765 旧演示页 | 仅历史视觉样例，不承担产品功能 |

### Agent 层

| 组件 | 职责 | 关键行为 |
|---|---|---|
| `agent/graph.py` | mock 确定性执行图 | 节点间状态传递（question/events/data/citations）；路由优先级；`interrupt` 澄清；`_run_analysis` 组计划、生成答案（按指标 unit 分支格式化）、落快照 |
| `agent/model.py` | live 模型循环 | `SYSTEM_PROMPT`（工具选择纪律 + plan 参数示例）；`OpenAIChatAdapter`/`ChatToolLoop`（DeepSeek）；`OpenAIModelAdapter`/`ModelToolLoop`（Responses 协议，靠 `previous_response_id` 回填上下文）；畸形 JSON → `arguments_error` → BAD_PARAMS 回传自纠；`FINALIZE_PROMPT` 兜底总结 |
| `agent/offline.py` | 脚本化代理 | 同一套工具链的确定性流程，用于测试；比率指标使用 overall 聚合而非分组求和 |
| `agent/periods.py` | 环比期间解析 | 优先解析问题中的 `（YYYY年）M月`（跨年回退），否则取数据 `paid_at` 最新月份；无法确定时返回 None 由调用方兜底 |

### 工具层

| 组件 | 职责 |
|---|---|
| `app.py` | 唯一组装点 `build_registry()`：注册全部 11 个工具，绑定语义库与知识目录 |
| `tools/base.py` | `Tool`（名称/描述/参数模型/handler/stage）与 `ToolRegistry`。`execute()` 是所有工具调用的唯一入口：stage 允许清单 → Pydantic 校验（BAD_PARAMS）→ 执行（异常归一为 INTERNAL 并携带细节）→ trace_id 全程跟踪 |
| `tools/analysis.py` | `run_analysis`：计划编译 → 执行 → 数值校验 → 贡献拆解 → overall 聚合 → 证据与逐值绑定 |
| `tools/advanced.py` | `run_python_analysis`（受控 Python，最多两次修复尝试，产物留档）；`analyze_contribution`（对任意校验过的行算贡献率并自检合计=1） |
| `tools/artifacts.py` | `get_evidence` / `replay_analysis`（按快照重放并对比数据/语义/知识/结果四个维度的哈希）/ `make_chart` / `export_report` |
| `tools/dataset.py` | `inspect_dataset`（画像）/ `register_dataset` / `define_relationship`（关系校验） |
| `tools/knowledge.py` | `resolve_metric`（指标解析）/ `search_metric_docs`（RAG 检索），均返回可引用证据 |

### 能力层

| 组件 | 职责 | 关键设计 |
|---|---|---|
| `compiler/sql.py` | 计划 → SQL | 维度/过滤字段白名单；双 CTE + FULL OUTER JOIN 保证只在当前期或上期出现的分组也不丢；参数顺序与占位符严格对应；`sqlglot` 只读校验 + 写操作黑名单 |
| `engine/duckdb_engine.py` | SQL 执行 | 内存连接 + `read_csv` 直读 CSV；512MB 内存/2 线程上限；结果 JSON 排序化后取 SHA-256 作为 `result_hash` |
| `engine/contribution.py` | 下降贡献率 | 负变化绝对值占比；全为上升时全 0，由上层语义处理 |
| `verification/numeric.py` | 数值自洽校验 | 每行 change = current - previous、rate 与分母一致性、有限性检查；失败进 `warnings` 且 `ok=False` |
| `sandbox/policy.py` | Python 静态策略 | 导入白名单；调用/属性黑名单（文件写出、进程、eval/exec/getattr…）；数据读取必须用注入的 `input_csv`（或 `str(input_csv)`）；dunder 全禁。定位：best-effort（单机单用户） |
| `sandbox/runner.py` | Python 执行 | 独立子进程 `sys.executable -I` + 最小环境变量；超时杀死；结果通过 `__DATAPILOT_RESULT__` 标记行以 JSON 取回；代码与产物留档 |
| `rag/retriever.py` | 混合检索 | BM25（jieba/字符 fallback）+ 字符 n-gram 哈希向量，RRF 融合；无信号不制造引用；`version` 取文档内容哈希，进快照 |
| `semantic/repository.py` | 指标语义库 | 别名/子串/相似度三级匹配；指标带 `expression/unit/allowed_dimensions/version` |
| `evidence/store.py` | 快照存储 | ID 白名单防路径逃逸；`.tmp` 写入失败自清理；快照含数据哈希、语义/知识版本、计划、SQL、结果哈希、校验状态 |

### 数据与契约

| 组件 | 职责 |
|---|---|
| `domain/models.py` | 全部 Pydantic 契约：`ToolResult`（ok/error 互斥校验）、`AnalysisPlan`（期间不重叠、contribution 必须有 comparison 和维度）、`ComparisonSpec`、`AnalysisSnapshot`、`EvidenceRef/ArtifactRef/FilterSpec/SortSpec` |
| `data/catalog.py` | 数据集画像：后缀白名单、根目录逃逸检查、逐列统计、时间范围、SHA-256 |
| `data/workspace.py` | 数据集注册表：`datasets.json` 持久化 schema 与关系，关系列必须真实存在 |
| `eval/runner.py` | Golden Set 评估：指标解析准确率、检索召回、执行准确率（对照 `data/golden`）、数值忠实度 |
| `config.py` | `.env` 配置（模式/模型/Key/步数/目录），启动时确保目录存在 |

---

## 5. 为什么这么设计（决策与理由）

**1. 为什么模型不直接写 SQL，而是产出 `AnalysisPlan` 结构再编译？**
直接生成 SQL 意味着注入面、不可校验、不可重放。结构化计划使三件事成立：
编译期就能校验维度/字段合法性；同一计划可复现同一 SQL（重放的基础）；
快照里存的 SQL 是系统生成的确定性产物而非模型输出，审计可信。
代价是模型需要填一个嵌套结构——所以系统提示词里给了完整参数示例（BUG-025 教训）。

**2. 为什么所有工具调用必须过 ToolRegistry 单一入口？**
集中实现四件模型自己无法保证的事：Pydantic 参数校验、stage 允许清单（防止
未授权阶段越权）、trace_id 审计、错误归一化。模型永远拿不到原始堆栈，但拿到
结构化错误码 + 失败细节——足以自纠（BUG-025：错误细节回传是自纠的前提）。

**3. 为什么 DuckDB 内存连接 + CSV 直读？**
零 ETL：用户上传 CSV 即刻可分析，无建库建表；单用户下无并发写，内存连接用完
即弃，不产生状态；`read_csv` 自动嗅探让日期格式等问题对用户透明；结果可整体
序列化取哈希，支撑重放。

**4. 为什么对比行要跑数值自洽校验，且 overall 单独聚合？**
校验（change/rate 自洽、有限性）是"结论不撒谎"的最后一道防线；overall 单独
聚合是因为**比率类指标（退款率/客单价）的整体值不等于分组值之和**——分组求和
会产生 0.34 这种假退款率（BUG-014 教训），凡整体结论必须取同口径聚合行。

**5. 为什么保留 mock 确定性图？**
live 模式的答案依赖模型，不可复现；mock 让 87 个回归测试和 Golden Set 8/8
可以在无 Key、无网络下稳定验收核心链路（编译、执行、校验、快照、重放）。
live 只改变"谁来决策调什么工具"，不改变工具层以下的任何东西——两条路径共享
同一套经过验证的计算设施。

**6. 为什么 live 有两个适配器？**
DeepSeek 不兼容 Responses API 的工具输出回填协议（BUG-009），必须走 Chat
Completions 显式消息拼接；Responses 兼容服务用 `previous_response_id` 省
token。两个循环行为保持对称（finalize 兜底、畸形 JSON 防护、trace 结构），
差异被压缩在协议层。

**7. 为什么步数耗尽要 finalize 而不是直接报错？**
预算耗尽≠没有产出。前几步成功执行的工具结果仍是有效证据，追加一次"不许再调
工具、只基于已有结果总结"的请求，把沉没成本转化为可用结论；彻底失败才返回
`budget_exhausted`。

**8. 为什么 RAG 用 BM25 + 哈希向量的混合检索？**
知识文档是中文小集合（口径说明/变更记录），BM25 保精确词命中，字符 n-gram
哈希向量兜底语义相似；两者都是本地确定性计算——无外部嵌入服务依赖、结果可
复现、断网可用。RRF 融合 + 无信号不制造引用，避免强行配证据。

**9. 为什么快照记录"哈希+版本"而不是只存结果？**
重放要回答的不是"结果是什么"，而是"**结果还能不能复现、是什么变了**"。
数据哈希、语义版本、知识版本、结果哈希四个维度分别对比，能把"数据变了"
"口径改了""文档更新了"区分开——这正是审计场景需要的归因。

**10. 为什么 Python 沙箱是 best-effort AST 检查 + 隔离子进程？**
威胁模型是单机单用户：用户本机已拥有全部数据，沙箱防的是模型生成代码的意外
破坏（递归、超时、误删）而非恶意攻击者。因此选择"AST 黑白名单 + `-I` 隔离 +
最小环境变量 + 超时 + 路径约束"的成本收益最优解，并在文档里如实标注残余
绕过面（f-string 属性访问等），不夸大"受控"的程度。

**11. 为什么错误码只有六种且每个失败必须有结构化语义？**
错误要流动三层：工具 → 模型 → 用户。六种码（BAD_PARAMS/NOT_FOUND/
POLICY_BLOCKED/EXECUTION_FAILED/TIMEOUT/INTERNAL）分别对应"参数可自纠/
对象不存在/越权/执行失败可重试/超时/实现错误"，模型据此决定重试、换路径
还是如实告知；`ToolResult` 的 ok/error 互斥校验在类型层面杜绝"失败却无
原因"的状态。

**12. 为什么产物（artifacts）与数据（workspace/data）分离？**
`workspace/` 是唯一承载用户业务数据的地方，删除前必须备份；`artifacts/`
任何时刻可整体清空重建（快照、报告、检查点、演示输出全部可再生）。
`.gitignore` 同步这一边界：数据与产物不进版本库，代码与文档进。

**13. 为什么界面只绑 127.0.0.1 且不做多租户？**
没有账号/权限/隔离设计（也刻意不做），开放到公网等于把业务数据与模型 Key
暴露给所有人。单机单用户是产品定位，不是待补的短板。

---

## 6. 安全边界清单

| 边界 | 实现位置 |
|---|---|
| 数据路径逃逸 | `DatasetCatalog._resolve`、`DuckDBEngine._authorized_path`、`run_python_analysis`、`SnapshotStore._assert_inside` |
| SQL 注入 | 计划结构化 + 字段白名单 + 全参数化 + sqlglot 只读校验 + 写操作黑名单 |
| Python 沙箱 | 导入白名单 / 调用属性黑名单 / reader 约束 / dunder 禁用 / `-I` 隔离 / 超时 |
| 快照 ID 注入 | 字符白名单 + 路径断言 |
| 密钥管理 | 仅存 `.env`（gitignore），代码/文档/日志不含 Key；`.env.example` 提供空模板 |
| 模型越权 | 模型只能调注册表工具，stage 允许清单可进一步收紧；文件写入只允许 `artifacts/` 会话目录 |

---

## 7. 失败语义速查

| 失败 | 呈现 | 去向 |
|---|---|---|
| 工具参数不合法 | `BAD_PARAMS` + 逐字段 errors | 回传模型自纠 |
| 引用不存在的对象 | `NOT_FOUND` | 回传模型，可如实告知用户 |
| 违反阶段/路径/沙箱约束 | `POLICY_BLOCKED` | 回传模型换合规路径 |
| SQL/校验失败 | `EXECUTION_FAILED` + 细节 | `run_analysis` 返回 ok=False，verification 警告随结果给出 |
| 超时 | `TIMEOUT` | 可重试语义 |
| 实现异常 | `INTERNAL` + 异常摘要 | 兜底码，暴露给模型与日志定位 |
| 模型畸形 JSON | `arguments_error` → BAD_PARAMS | 回传自纠，不崩溃（BUG-015） |
| 校验错误详情序列化 | `include_context=False` | 永不携带异常实例（BUG-026） |
| 预算耗尽 | finalize 兜底总结 + `tool_budget_exhausted` 标记 | 不浪费已执行证据（BUG-019） |
| 不支持的问题 | `unsupported` 明确拒绝 | 不编造 |
| live 缺 Key | 显式 ValueError 提示 | 不静默降级 mock（BUG-018） |

---

## 8. 历史教训的模式（详见 BUGLOG）

- **环境比代码脆弱**：basetemp/缓存目录损坏能阻断整个开发流程，固定路径必须有
  兜底（BUG-013/005）。
- **失败细节必须流动**：吞掉异常原因等于剥夺模型与开发者自纠能力（BUG-025/015）。
- **聚合口径是数值正确性的高危区**：比率不能求和、整体必须同口径聚合（BUG-014）。
- **两个实现路径要保持对称**：Chat/Responses 循环的行为差异就是用户可感知的
  功能差异（BUG-019）。
- **界面是产品的一部分**：后端通而界面断头（澄清流程）等于功能不存在（BUG-016）。

---

## 9. 目录速览

```
src/datapilot_verify/   核心库（Agent/工具/编译/执行/沙箱/检索/证据）
webapp/                 界面与服务（8767 桌面 / 8766 API / 8765 旧演示）
tests/                  87 个回归测试（含 Golden Set）
scripts/                启动脚本、造数脚本、演示脚本
data/                   口径定义 + 知识文档 + 样例数据 + 金标准（只读资产）
workspace/              用户业务数据（唯一需要备份的目录）
artifacts/              运行产物（快照/报告/检查点，可随时清空）
docs/                   本文档、RUNTIME_LOGIC、BUGLOG 与 bug 档案
```
