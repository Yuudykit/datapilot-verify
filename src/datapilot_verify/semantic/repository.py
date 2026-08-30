from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from datapilot_verify.domain.models import MetricDefinition


@dataclass(frozen=True)
class MetricMatch:
    metric: MetricDefinition
    score: float
    matched_text: str


class SemanticRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = ""
        self._metrics: dict[str, MetricDefinition] = {}
        self._load()

    def _load(self) -> None:
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version = str(payload["version"])
        self._metrics = {
            metric_id: MetricDefinition.model_validate(definition)
            for metric_id, definition in payload["metrics"].items()
        }

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def get(self, metric_id: str) -> MetricDefinition | None:
        return self._metrics.get(metric_id)

    def all(self) -> list[MetricDefinition]:
        return list(self._metrics.values())

    def resolve(self, query: str, limit: int = 5) -> list[MetricMatch]:
        normalized = query.casefold().strip()
        matches: list[MetricMatch] = []
        for metric in self._metrics.values():
            candidates = [metric.metric_id, metric.name, *metric.aliases]
            best_score = 0.0
            best_text = metric.name
            for candidate in candidates:
                candidate_normalized = candidate.casefold()
                if candidate_normalized in normalized:
                    score = 1.0 if candidate_normalized == normalized else 0.95
                else:
                    score = SequenceMatcher(None, normalized, candidate_normalized).ratio()
                if score > best_score:
                    best_score = score
                    best_text = candidate
            if best_score >= 0.35:
                matches.append(MetricMatch(metric=metric, score=best_score, matched_text=best_text))
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]

