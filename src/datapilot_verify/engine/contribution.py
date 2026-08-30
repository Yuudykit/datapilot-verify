from __future__ import annotations

from typing import Any


def enrich_contribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_decline = sum(abs(float(row["change_amount"])) for row in rows if row["change_amount"] < 0)
    enriched = []
    for row in rows:
        item = dict(row)
        change = float(item["change_amount"])
        item["decline_contribution_rate"] = (
            abs(change) / total_decline if change < 0 and total_decline else 0.0
        )
        enriched.append(item)
    return enriched

