from __future__ import annotations

from pathlib import Path

from datapilot_verify.tools import ToolRegistry
from datapilot_verify.tools.advanced import analyze_contribution, run_python_analysis
from datapilot_verify.tools.analysis import build_run_analysis_tool
from datapilot_verify.tools.artifacts import build_artifact_tools
from datapilot_verify.tools.dataset import define_relationship, inspect_dataset, register_dataset
from datapilot_verify.tools.knowledge import build_knowledge_tools


def build_registry(project_root: Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(inspect_dataset)
    registry.register(register_dataset)
    registry.register(define_relationship)
    for item in build_knowledge_tools(
        project_root / "data" / "semantic" / "metrics.yml",
        project_root / "data" / "knowledge",
    ):
        registry.register(item)
    registry.register(build_run_analysis_tool(project_root / "data" / "semantic" / "metrics.yml"))
    registry.register(run_python_analysis)
    registry.register(analyze_contribution)
    for item in build_artifact_tools(
        project_root / "data" / "semantic" / "metrics.yml",
        project_root / "data" / "knowledge",
    ):
        registry.register(item)
    return registry
