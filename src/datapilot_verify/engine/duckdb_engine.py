from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datapilot_verify.compiler import CompiledQuery


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    result_hash: str


class DuckDBEngine:
    def __init__(self, data_root: Path, memory_limit: str = "512MB", threads: int = 2) -> None:
        self.data_root = data_root.resolve()
        self.memory_limit = memory_limit
        self.threads = threads

    def execute(self, query: CompiledQuery) -> QueryResult:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("duckdb is required for analysis execution") from exc

        orders = self._authorized_path("orders.csv")
        stores = self._authorized_path("stores.csv")
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(f"SET memory_limit='{self.memory_limit}'")
            connection.execute(f"SET threads={self.threads}")
            connection.read_csv(str(orders), header=True).create_view("orders")
            connection.read_csv(str(stores), header=True).create_view("stores")
            cursor = connection.execute(query.sql, query.parameters)
            columns = [item[0] for item in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            connection.close()
        encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            result_hash=hashlib.sha256(encoded).hexdigest(),
        )

    def _authorized_path(self, filename: str) -> Path:
        path = (self.data_root / filename).resolve()
        try:
            path.relative_to(self.data_root)
        except ValueError as exc:
            raise ValueError("data path escapes allowed root") from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
