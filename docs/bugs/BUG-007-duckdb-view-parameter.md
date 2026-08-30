# BUG-007：DuckDB 创建 CSV 视图时不接受路径参数

## 复现与影响

端到端执行 `CREATE VIEW orders AS SELECT * FROM read_csv_auto(?)` 时，DuckDB 1.5.5 抛出 `BinderException: Unexpected prepared parameter`，导致分析计划无法执行。

## 根因

DuckDB 的 `CREATE VIEW` DDL 中表函数路径不能作为 prepared parameter 绑定。普通查询过滤参数仍可正常绑定。

## 修复

先由 `_authorized_path` 将固定数据文件解析并校验在允许根目录内，再使用 DuckDB Relation API：

```python
connection.read_csv(str(path), header=True).create_view("orders")
```

分析 SQL 中的日期和过滤条件继续使用参数绑定。

## 验证

区域贡献分析端到端测试需与 Golden 数据的华东下降额完全一致。

