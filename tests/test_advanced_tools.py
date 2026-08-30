from pathlib import Path

from datapilot_verify.app import build_registry
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[1]


def test_contribution_tool_preserves_decline_sum() -> None:
    registry = build_registry(ROOT)
    result = registry.execute(
        "analyze_contribution",
        {
            "rows": [
                {"region": "A", "change_amount": -20},
                {"region": "B", "change_amount": -5},
                {"region": "C", "change_amount": 10},
            ]
        },
        ToolContext("test", ROOT / "data" / "sample", ROOT / "artifacts" / "test"),
    )
    assert result.ok
    assert result.data["verification"]["contribution_sum"] == 1.0


def test_python_tool_returns_policy_error() -> None:
    registry = build_registry(ROOT)
    result = registry.execute(
        "run_python_analysis",
        {"code": "import os\nresult = {}"},
        ToolContext("test", ROOT / "data" / "sample", ROOT / "artifacts" / "test"),
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "POLICY_BLOCKED"


def test_python_tool_can_repair_once() -> None:
    registry = build_registry(ROOT)
    result = registry.execute(
        "run_python_analysis",
        {
            "code": "raise ValueError('first attempt')",
            "repair_candidates": [
                "import pandas as pd\nframe = pd.read_csv(input_csv)\nresult = {'rows': len(frame)}"
            ],
        },
        ToolContext("test", ROOT / "data" / "sample", ROOT / "artifacts" / "test"),
    )
    assert result.ok
    assert result.data["result"]["rows"] == 3123
    assert len(result.data["attempts"]) == 2
