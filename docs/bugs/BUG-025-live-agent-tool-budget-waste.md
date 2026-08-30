# BUG-025：live 模式工具预算被浪费且失败无细节，分析问题得不到数值结论

- 日期：2026-08-30
- 模块：agent/model.py（系统提示词）、tools/base.py（错误边界）、
  sandbox/policy.py、tools/advanced.py
- 级别：P1
- 状态：已修复

## 现象

live 模式问"7 月销售额为什么下降？"，模型把 8 步预算的大部分花在
`inspect_dataset`×2、`register_dataset`×2、`define_relationship` 等无关
工具上；首次 `run_analysis` 失败但报错只有
`INTERNAL tool execution failed: ValueError`，底层原因（排序字段非法等）
被错误边界丢弃，模型无从自纠；`run_python_analysis` 把 `input_csv` 当
DataFrame 调用（`input_csv.copy()`）或写成 `pd.read_csv(str(input_csv))`
被策略拒绝。步数烧完后兜底总结只能承认"无法判断是否下降"。

## 根因

1. 系统提示词没有工具选择纪律，也没有 `run_analysis` 的参数示例，
   模型面对复杂嵌套 schema 只能盲试；
2. 工具边界的 INTERNAL 报错丢弃了 `str(exc)`，失败原因无法回流给模型；
3. `run_python_analysis` 的描述没有说明 `input_csv` 的用法约定。

## 修复与验证

- 工具边界报错改为携带底层异常：`tool execution failed: <类型>: <信息>`。
- 重写 SYSTEM_PROMPT：声明数据已导入并关联、禁止无关调用
  register_dataset/define_relationship、按问题类型选择工具、给出一份完整
  有效的 `plan` 参数 JSON 示例、写明 Python 沙箱的 `input_csv` 约定。
- `run_python_analysis` 描述写清 `input_csv` 是文件路径、需赋值给
  `result` 变量。
- 沙箱数据读取规则放宽为允许 `input_csv` 或 `str(input_csv)`，其余路径
  仍然拒绝；`run_python_analysis` 描述同步。

新增回归：INTERNAL 错误保留底层异常细节、`str(input_csv)` 放行但其他
路径仍拒绝。验证：86 个测试通过，全项目 ruff 通过；live 端到端复跑同一
问题（见 BUGLOG 修复记录）数值结论正常产出。
