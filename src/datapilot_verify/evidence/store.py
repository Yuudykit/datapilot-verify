from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datapilot_verify.domain.models import AnalysisSnapshot


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: AnalysisSnapshot) -> Path:
        path = self.root / f"{snapshot.snapshot_id}.json"
        self._assert_inside(path)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def load(self, snapshot_id: str) -> AnalysisSnapshot:
        if not snapshot_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in snapshot_id):
            raise ValueError("invalid snapshot id")
        path = self.root / f"{snapshot_id}.json"
        self._assert_inside(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return AnalysisSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json"))

    def _assert_inside(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise ValueError("snapshot path escapes root") from exc

