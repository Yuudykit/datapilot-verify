# BUG-014：OfflineAgent 对比率指标把分组值求和，答案数值错误

- 日期：2026-08-30
- 模块：OfflineAgent（agent/offline.py）
- 级别：P1
- 状态：已修复

## 现象

问"按渠道比较 6 月和 7 月的退款率变化"，答案为"7 月退款率为 0.34，较 6 月变化
0.12。小程序贡献了全部变化项的 0.0%，是最主要的可观察贡献因素。"三个渠道的
比率被直接相加（真实整体约 9.7%），单位没有按百分比呈现；当所有分组变化为正
时 `decline_contribution_rate` 全为 0，还会拼出"贡献 0.0% 却是最主要因素"的
自相矛盾句子。客单价（AOV）同样受影响：整体客单价不等于各分组客单价之和。

## 根因

`_run_decline_analysis` 用 `sum(row["current_value"] for row in rows)` 汇总
分组行生成整体结论。该算法只对可加指标（如净销售额）成立；比率类指标必须
用相同口径的整体聚合值。`run_analysis` 工具在 comparison+dimensions 时已经
内部计算并返回 `overall` 聚合行（graph.py 一直在用），OfflineAgent 没有使用。

## 修复与验证

答案改用 `analysis.data["overall"]` 的整体值，并按指标 `unit` 分支呈现：
ratio 用百分比/百分点格式，金额用千分位；贡献句改为取变化绝对值最大的分组，
只有真实存在下降分组时才给出下降贡献率，否则如实说明"各分组未见下降"。
新增 `_dimension_label` 辅助方法，维度取不到时显示"未知分组"而非 None。

新增回归测试 `test_ratio_metric_answer_reports_overall_rate_not_row_sum`，
用 pandas 从原始订单数据独立计算整体退款率作为期望值。验证：整体退款率
9.7%、+2.5 个百分点，净销售额口径输出保持不变，全量测试通过。
