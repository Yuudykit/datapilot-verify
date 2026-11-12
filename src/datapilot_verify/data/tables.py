from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from datapilot_verify.domain.models import TablePlan

OPERATIONS = {
    "profile": "数据质量检查",
    "count": "记录数",
    "sum": "合计",
    "mean": "平均值",
    "min": "最小值",
    "max": "最大值",
}
TABLE_ID = re.compile(r"table_[0-9a-f]{12}")


def workbook_sheets(filename: str, content: bytes) -> list[str]:
    if Path(filename).suffix.casefold() == ".csv":
        return []
    with pd.ExcelFile(io.BytesIO(content)) as book:
        return book.sheet_names


def import_table(
    workspace: Path, filename: str, content: bytes, sheet: str | None, header_row: int
) -> dict[str, Any]:
    if header_row < 1:
        raise ValueError("表头行号必须从 1 开始。")
    suffix = Path(filename).suffix.casefold()
    options = {"header": None, "skiprows": header_row - 1, "dtype": str, "keep_default_na": False}
    if suffix == ".csv":
        options["skip_blank_lines"] = False
        try:
            frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", **options)
        except UnicodeDecodeError:
            frame = pd.read_csv(io.BytesIO(content), encoding="gb18030", **options)
        sheet = None
    elif suffix in {".xlsx", ".xls"}:
        with pd.ExcelFile(io.BytesIO(content)) as book:
            sheet = sheet if sheet is not None else book.sheet_names[0]
            frame = book.parse(sheet, **options)
    else:
        raise ValueError("仅支持 CSV、XLSX、XLS 文件。")
    if frame.empty:
        raise ValueError("找不到指定的表头行。")
    frame = frame.apply(lambda column: column.str.strip())
    if not frame.iloc[0].ne("").any():
        raise ValueError("指定的表头行为空，请检查表头行号。")
    frame = frame.loc[:, frame.ne("").any(axis=0)]
    headers = [
        name or f"未命名列 {position}" for position, name in zip(
            frame.columns + 1, frame.iloc[0], strict=True
        )
    ]
    if len(set(headers)) != len(headers):
        raise ValueError("发现重复字段名，请检查表头行或重命名重复列。")
    frame = frame.iloc[1:]
    frame = frame.loc[frame.ne("").any(axis=1)]
    if frame.empty:
        raise ValueError("表头下面没有可分析的数据行，请检查工作表和表头行号。")
    frame.columns = headers

    dataset_id = f"table_{uuid.uuid4().hex[:12]}"
    metadata = {
        "dataset_id": dataset_id,
        "filename": Path(filename).name,
        "sheet": sheet,
        "header_row": header_row,
        "row_count": len(frame),
        "fields": list(frame.columns),
    }
    manifest = _table_path(workspace, dataset_id, ".json")
    data = _table_path(workspace, dataset_id, ".csv")
    temporary = manifest.with_suffix(".tmp")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_csv(data, index=False, encoding="utf-8")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        temporary.replace(manifest)
    except Exception:
        data.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise
    return metadata


def _table_path(workspace: Path, dataset_id: str, suffix: str) -> Path:
    if not TABLE_ID.fullmatch(dataset_id):
        raise ValueError("无效的表格编号。")
    path = (workspace / "tables" / f"{dataset_id}{suffix}").resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError("表格路径超出了数据工作区。")
    return path


def table_metadata(workspace: Path, dataset_id: str) -> dict[str, Any]:
    path = _table_path(workspace, dataset_id, ".json")
    return json.loads(path.read_text(encoding="utf-8"))


def list_tables(workspace: Path) -> list[dict[str, Any]]:
    return [
        table_metadata(workspace, path.stem)
        for path in sorted((workspace / "tables").glob("table_*.json"))
        if TABLE_ID.fullmatch(path.stem)
    ]


def parse_question(dataset_id: str, question: str) -> TablePlan:
    text = question.strip().rstrip("？?。")
    if text in {"检查数据质量", "数据质量", "查看字段", "字段概览", "检查这张表"}:
        return TablePlan(dataset_id=dataset_id, operation="profile")
    if text in {
        "这张表有多少行", "有多少行", "有多少条记录", "这张表有多少条记录",
        "统计总行数", "统计记录数", "总记录数",
    }:
        return TablePlan(dataset_id=dataset_id, operation="count")
    if match := re.fullmatch(r"按\s*(.+?)\s*(?:分组)?(?:统计|计算)(?:数量|记录数|行数)", text):
        return TablePlan(dataset_id=dataset_id, operation="count", group_by=_unquote(match[1]))
    if match := re.fullmatch(r"(.+?)\s*[=＝]\s*(.+?)的记录数", text):
        return TablePlan(
            dataset_id=dataset_id, operation="count",
            filter_column=_unquote(match[1]), filter_value=_unquote(match[2]),
        )
    if match := re.fullmatch(r"(?:按(.+?))?计算(.+?)(?:的)?(合计|平均值|最小值|最大值)", text):
        operations = {"合计": "sum", "平均值": "mean", "最小值": "min", "最大值": "max"}
        return TablePlan(
            dataset_id=dataset_id, operation=operations[match[3]],
            group_by=_unquote(match[1]) if match[1] else None, value_column=_unquote(match[2]),
        )
    raise ValueError("可输入「检查数据质量」「按字段名统计数量」，或展开「按字段配置」。")


def _unquote(value: str) -> str:
    return value.strip().strip("「」`").strip()


def execute_table_plan(
    workspace: Path, plan: TablePlan
) -> tuple[dict[str, Any], str, str]:
    source = _table_path(workspace, plan.dataset_id, ".csv").read_bytes()
    reader = csv.DictReader(io.StringIO(source.decode("utf-8"), newline=""))
    fields = reader.fieldnames or []
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("已导入表格的表头无效，请重新导入。")
    for column in (plan.group_by, plan.value_column, plan.filter_column):
        if column is not None and column not in fields:
            raise ValueError(f"表格中没有字段「{column}」。请在「按字段配置」中选择实际列名。")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("已导入表格的行列不一致，请重新导入。")
    if plan.operation == "profile":
        data = _profile(rows, fields)
    else:
        if plan.filter_column is not None:
            rows = [row for row in rows if row[plan.filter_column] == plan.filter_value]
        data = _aggregate(rows, plan)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return data, hashlib.sha256(source).hexdigest(), digest


def _profile(rows: list[dict[str, str]], fields: list[str]) -> dict[str, Any]:
    columns = [
        {
            "name": name,
            "null_count": sum(row[name] == "" for row in rows),
            "distinct_count": len({row[name] for row in rows if row[name]}),
        }
        for name in fields
    ]
    return {
        "row_count": len(rows),
        "duplicate_rows": len(rows) - len({tuple(row[name] for name in fields) for row in rows}),
        "rows": columns,
    }


def _aggregate(rows: list[dict[str, str]], plan: TablePlan) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    if plan.group_by:
        for row in rows:
            groups[row[plan.group_by]].append(row)
    else:
        groups[""] = rows

    results = []
    for key, group in groups.items():
        if plan.value_column is None:
            value: int | str | None = len(group)
            valid = len(group)
        else:
            numbers = [_number(row[plan.value_column], plan.value_column) for row in group
                       if row[plan.value_column] != ""]
            valid = len(numbers)
            value = _summarize(numbers, plan.operation)
        record = {"value": value}
        if plan.value_column is not None:
            record["valid"] = valid
        if plan.group_by:
            record = {"group": key or None, **record}
        results.append(record)
    if plan.group_by:
        results.sort(key=lambda row: (row["group"] is None, row["group"] or ""))
    return {"row_count": len(rows), "rows": results}


def _number(value: str, column: str) -> Decimal:
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    try:
        number = Decimal(value)
        if number.is_finite():
            return number
    except InvalidOperation:
        pass
    raise ValueError(f"「{column}」含有非数值内容，无法汇总。请检查该列或改用记录数。")


def _summarize(numbers: list[Decimal], operation: str) -> str | None:
    if not numbers:
        return None
    if operation == "sum":
        value = sum(numbers, Decimal(0))
    elif operation == "mean":
        value = sum(numbers, Decimal(0)) / len(numbers)
    else:
        value = min(numbers) if operation == "min" else max(numbers)
    return str(value)
