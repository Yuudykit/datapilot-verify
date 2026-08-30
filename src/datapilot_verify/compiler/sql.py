from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot_verify.domain.models import AnalysisPlan, FilterSpec, MetricDefinition


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: list[Any]
    replay_level: str = "strong"


class SqlPolicy:
    BLOCKED_TOKENS = {
        "ALTER",
        "ATTACH",
        "CALL",
        "COPY",
        "CREATE",
        "DELETE",
        "DETACH",
        "DROP",
        "EXPORT",
        "IMPORT",
        "INSERT",
        "INSTALL",
        "LOAD",
        "PRAGMA",
        "UPDATE",
    }

    def validate(self, sql: str) -> None:
        try:
            import sqlglot
            from sqlglot import expressions as exp
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("sqlglot is required to validate SQL") from exc

        statements = sqlglot.parse(sql, read="duckdb")
        if len(statements) != 1:
            raise ValueError("exactly one SQL statement is allowed")
        statement = statements[0]
        if not isinstance(statement, (exp.Select, exp.Union)):
            raise ValueError("only read-only SELECT queries are allowed")
        upper_sql = sql.upper()
        blocked = sorted(token for token in self.BLOCKED_TOKENS if token in upper_sql)
        if blocked:
            raise ValueError(f"blocked SQL operation: {blocked[0]}")


class PlanCompiler:
    DIMENSIONS = {
        "region": 's."region"',
        "city": 's."city"',
        "store_id": 'o."store_id"',
        "category": 'o."category"',
        "channel": 'o."channel"',
    }
    FILTER_FIELDS = {
        "paid_at": 'o."paid_at"',
        **DIMENSIONS,
    }

    def __init__(self, policy: SqlPolicy | None = None) -> None:
        self.policy = policy or SqlPolicy()

    def compile(self, plan: AnalysisPlan, metric: MetricDefinition) -> CompiledQuery:
        invalid = sorted(set(plan.dimensions) - set(metric.allowed_dimensions))
        if invalid:
            raise ValueError(f"dimensions are not allowed for metric {metric.metric_id}: {invalid}")
        dimensions = [self.DIMENSIONS[name] for name in plan.dimensions]
        aliases = [f'"{name}"' for name in plan.dimensions]
        parameters: list[Any] = []

        if plan.comparison:
            query = self._compile_comparison(plan, metric, dimensions, aliases, parameters)
        else:
            where = self._compile_filters(plan.filters, parameters)
            select_dimensions = ", ".join(
                f"{expression} AS {alias}" for expression, alias in zip(dimensions, aliases)
            )
            select_parts = [part for part in (select_dimensions, f"{metric.expression} AS value") if part]
            query = (
                f"SELECT {', '.join(select_parts)}\n"
                'FROM "orders" o\n'
                'LEFT JOIN "stores" s ON o."store_id" = s."store_id"\n'
                f"WHERE {where}"
            )
            if dimensions:
                query += "\nGROUP BY " + ", ".join(dimensions)
            query += self._compile_order_limit(plan)

        self.policy.validate(query)
        return CompiledQuery(sql=query, parameters=parameters)

    def _compile_comparison(
        self,
        plan: AnalysisPlan,
        metric: MetricDefinition,
        dimensions: list[str],
        aliases: list[str],
        parameters: list[Any],
    ) -> str:
        assert plan.comparison is not None
        current_start, current_end = plan.comparison.current_period
        previous_start, previous_end = plan.comparison.previous_period
        parameters.extend([current_start, current_end])
        current_filters = self._compile_filters(plan.filters, parameters, prefix=" AND ")
        parameters.extend([previous_start, previous_end])
        previous_filters = self._compile_filters(plan.filters, parameters, prefix=" AND ")
        dimension_select = ", ".join(
            f"{expression} AS {alias}" for expression, alias in zip(dimensions, aliases)
        )
        select_prefix = f"{dimension_select}, " if dimension_select else ""
        group_by = "\nGROUP BY " + ", ".join(dimensions) if dimensions else ""
        join_keys = " AND ".join(f"c.{alias} = p.{alias}" for alias in aliases) or "TRUE"
        projected_dims = ", ".join(
            f"COALESCE(c.{alias}, p.{alias}) AS {alias}" for alias in aliases
        )
        projected_prefix = f"{projected_dims}, " if projected_dims else ""
        query = f'''WITH current_period AS (
  SELECT {select_prefix}{metric.expression} AS value
  FROM "orders" o
  LEFT JOIN "stores" s ON o."store_id" = s."store_id"
  WHERE o."paid_at" BETWEEN ? AND ?{current_filters}{group_by}
), previous_period AS (
  SELECT {select_prefix}{metric.expression} AS value
  FROM "orders" o
  LEFT JOIN "stores" s ON o."store_id" = s."store_id"
  WHERE o."paid_at" BETWEEN ? AND ?{previous_filters}{group_by}
)
SELECT {projected_prefix}
       COALESCE(c.value, 0) AS current_value,
       COALESCE(p.value, 0) AS previous_value,
       COALESCE(c.value, 0) - COALESCE(p.value, 0) AS change_amount,
       CASE WHEN COALESCE(p.value, 0) = 0 THEN NULL
            ELSE (COALESCE(c.value, 0) - p.value) / p.value END AS change_rate
FROM current_period c
FULL OUTER JOIN previous_period p ON {join_keys}'''
        return query + self._compile_order_limit(plan)

    def _compile_filters(
        self, filters: list[FilterSpec], parameters: list[Any], prefix: str = ""
    ) -> str:
        clauses = []
        operators = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        for item in filters:
            field = self.FILTER_FIELDS.get(item.field)
            if field is None:
                raise ValueError(f"filter field is not allowed: {item.field}")
            if item.operator in operators:
                clauses.append(f"{field} {operators[item.operator]} ?")
                parameters.append(item.value)
            elif item.operator == "between":
                clauses.append(f"{field} BETWEEN ? AND ?")
                parameters.extend(item.value)
            elif item.operator == "in":
                placeholders = ", ".join("?" for _ in item.value)
                clauses.append(f"{field} IN ({placeholders})")
                parameters.extend(item.value)
        if not clauses:
            return "TRUE" if not prefix else ""
        joined = " AND ".join(clauses)
        return f"{prefix}{joined}" if prefix else joined

    @staticmethod
    def _compile_order_limit(plan: AnalysisPlan) -> str:
        suffix = ""
        if plan.sort:
            allowed_outputs = {*plan.dimensions, "value", "current_value", "previous_value", "change_amount", "change_rate"}
            order = []
            for item in plan.sort:
                if item.field not in allowed_outputs:
                    raise ValueError(f"sort field is not available: {item.field}")
                order.append(f'"{item.field}" {item.direction.upper()}')
            suffix += "\nORDER BY " + ", ".join(order)
        if plan.limit:
            suffix += f"\nLIMIT {plan.limit}"
        return suffix
