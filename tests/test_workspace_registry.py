import shutil
from pathlib import Path

from datapilot_verify.data import WorkspaceRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_registers_schema_and_relationship(tmp_path: Path) -> None:
    shutil.copy(ROOT / "data" / "sample" / "orders.csv", tmp_path / "orders.csv")
    shutil.copy(ROOT / "data" / "sample" / "stores.csv", tmp_path / "stores.csv")
    registry = WorkspaceRegistry(tmp_path)
    orders = registry.register("orders.csv")
    stores = registry.register("stores.csv")
    assert orders["row_count"] == 3123
    assert stores["row_count"] == 11
    relationship = registry.add_relationship("orders", "store_id", "stores", "store_id")
    assert relationship["left_column"] == "store_id"
    assert len(registry.load()["relationships"]) == 1
