from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from datapilot_verify.domain.models import ColumnProfile, DatasetProfile


class DatasetCatalog:
    SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}

    def __init__(self, allowed_root: Path) -> None:
        self.allowed_root = allowed_root.resolve()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.allowed_root / relative_path).resolve()
        try:
            candidate.relative_to(self.allowed_root)
        except ValueError as exc:
            raise ValueError("dataset path escapes the allowed root") from exc
        if candidate.suffix.casefold() not in self.SUPPORTED_SUFFIXES:
            raise ValueError(f"unsupported dataset type: {candidate.suffix}")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate

    def load(self, relative_path: str, max_rows: int | None = None) -> pd.DataFrame:
        path = self._resolve(relative_path)
        if path.suffix.casefold() == ".csv":
            return pd.read_csv(path, nrows=max_rows)
        return pd.read_excel(path, nrows=max_rows)

    def profile(self, relative_path: str) -> DatasetProfile:
        path = self._resolve(relative_path)
        frame = self.load(relative_path)
        columns = []
        for name in frame.columns:
            series = frame[name]
            samples = series.dropna().head(3).tolist()
            columns.append(
                ColumnProfile(
                    name=str(name),
                    dtype=str(series.dtype),
                    nullable=bool(series.isna().any()),
                    null_count=int(series.isna().sum()),
                    distinct_count=int(series.nunique(dropna=True)),
                    sample_values=samples,
                )
            )
        time_range = None
        for candidate in ("paid_at", "created_at", "date"):
            if candidate in frame.columns:
                parsed = pd.to_datetime(frame[candidate], errors="coerce").dropna()
                if not parsed.empty:
                    time_range = (parsed.min().date(), parsed.max().date())
                    break
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return DatasetProfile(
            dataset_id=path.stem,
            filename=path.name,
            sha256=digest,
            row_count=len(frame),
            columns=columns,
            time_range=time_range,
        )

