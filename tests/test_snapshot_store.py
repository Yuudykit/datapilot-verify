from datetime import datetime, timezone

import pytest

from datapilot_verify.domain.models import AnalysisSnapshot
from datapilot_verify.evidence import SnapshotStore


def test_snapshot_roundtrip(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    snapshot = AnalysisSnapshot(
        snapshot_id="snapshot_1",
        created_at=datetime.now(timezone.utc),
        question="why",
        dataset_hashes={"orders": "abc"},
        semantic_version="1",
        knowledge_version="2",
        replay_level="strong",
    )
    store.save(snapshot)
    assert store.load("snapshot_1") == snapshot
    assert store.list() == ["snapshot_1"]


def test_snapshot_rejects_unsafe_id(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        store.load("../secret")

