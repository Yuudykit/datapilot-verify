# BUG-021：Python 沙箱策略存在多处绕过口

- 日期：2026-08-30
- 模块：sandbox/policy.py
- 级别：P2
- 状态：已修复

## 现象（策略可被绕过）

- `getattr/setattr/delattr/vars` 不在调用黑名单，可绕过属性黑名单
  （如 `getattr(pd, "read_csv")` 任意读取器）。
- 数据读取约束只覆盖 `read_csv/read_excel/scan_csv` 三个白名单名，
  `pandas.read_json("http://…")`（支持 URL，可外发数据）、
  `read_pickle` 等不受"必须使用 input_csv"约束。
- 属性黑名单缺 `eval`（`pandas.eval` 可用）、缺文件写出类
  （`to_csv/to_pickle/write_text/mkdir` 等），沙箱代码可写任意路径。

## 根因

策略按"点名"维护，新增绕过面未同步；定位虽然是 best-effort（单机单
用户、`-I` 隔离 + 最小环境变量），但缺口与 README 的"受控"承诺不符。

## 修复与验证

- BLOCKED_CALLS 增加 `getattr/setattr/delattr/vars`。
- 属性黑名单增加 `eval` 与写出类：`to_csv/to_excel/to_json/to_pickle/
  to_parquet/to_hdf/to_sql/write_text/write_bytes/mkdir/symlink`。
- 数据读取约束从白名单三元组放宽为前缀规则：任何 `read_*`/`scan_*`
  调用的首个参数必须是注入的 `input_csv` 变量。
- 新增策略用例：getattr/vars 调用、`pd.eval`、`to_csv`、
  `read_json(URL)` 均被拒；`read_pickle(input_csv)` 允许。

验证：沙箱策略/执行器/高级工具 16 个测试通过，全量无回归。
说明：字符串 `format`、f-string 属性访问等残余绕过面仍属 best-effort
边界，档案与 README 均已明确沙箱定位。
