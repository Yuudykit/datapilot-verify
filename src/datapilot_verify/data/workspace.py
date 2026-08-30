from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datapilot_verify.data.catalog import DatasetCatalog


class WorkspaceRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "datasets.json"

    def register(self, relative_path: str) -> dict[str, Any]:
        profile = DatasetCatalog(self.root).profile(relative_path)
        payload = self.load()
        payload["datasets"][profile.dataset_id] = profile.model_dump(mode="json")
        self._save(payload)
        return payload["datasets"][profile.dataset_id]

    def add_relationship(
        self, left_dataset: str, left_column: str, right_dataset: str, right_column: str
    ) -> dict[str, str]:
        payload = self.load()
        for dataset in (left_dataset, right_dataset):
            if dataset not in payload["datasets"]:
                raise ValueError(f"dataset is not registered: {dataset}")
        relationship = {
            "left_dataset": left_dataset,
            "left_column": left_column,
            "right_dataset": right_dataset,
            "right_column": right_column,
        }
        columns = {
            name: {item["name"] for item in payload["datasets"][name]["columns"]}
            for name in (left_dataset, right_dataset)
        }
        if left_column not in columns[left_dataset] or right_column not in columns[right_dataset]:
            raise ValueError("relationship column is not present in the registered schema")
        if relationship not in payload["relationships"]:
            payload["relationships"].append(relationship)
            self._save(payload)
        return relationship

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"datasets": {}, "relationships": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        temporary.replace(self.path)
