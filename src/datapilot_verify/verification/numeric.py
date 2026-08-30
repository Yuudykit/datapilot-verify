from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerificationReport:
    passed: bool
    checks: dict[str, bool]
    warnings: list[str] = field(default_factory=list)


def verify_comparison_rows(
    rows: list[dict[str, Any]], tolerance: float = 1e-9
) -> VerificationReport:
    checks = {
        "change_amount_consistent": True,
        "change_rate_consistent": True,
        "finite_values": True,
    }
    warnings: list[str] = []
    for index, row in enumerate(rows):
        current = float(row.get("current_value", 0) or 0)
        previous = float(row.get("previous_value", 0) or 0)
        change = float(row.get("change_amount", 0) or 0)
        expected_change = current - previous
        if abs(change - expected_change) > tolerance:
            checks["change_amount_consistent"] = False
            warnings.append(f"row {index}: change amount is inconsistent")
        actual_rate = row.get("change_rate")
        if previous == 0:
            if actual_rate is not None:
                checks["change_rate_consistent"] = False
                warnings.append(f"row {index}: zero denominator should yield null rate")
        elif actual_rate is None or abs(
            float(actual_rate) - expected_change / previous
        ) > tolerance:
            checks["change_rate_consistent"] = False
            warnings.append(f"row {index}: change rate is inconsistent")
        for value in (current, previous, change):
            if value != value or value in (float("inf"), float("-inf")):
                checks["finite_values"] = False
                warnings.append(f"row {index}: non-finite numeric value")
                break
    return VerificationReport(passed=all(checks.values()), checks=checks, warnings=warnings)

