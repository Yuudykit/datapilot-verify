from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

try:
    import jieba
except ImportError:  # Optional tokenizer; deterministic fallback keeps setup light.
    jieba = None


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    source: str
    heading: str
    text: str
    version: str | None
    line_start: int


@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: float
    bm25_rank: int | None
    vector_rank: int | None


def _tokenize(text: str) -> list[str]:
    if jieba is not None:
        return [token.strip().casefold() for token in jieba.lcut(text) if token.strip()]
    normalized = re.sub(r"\s+", "", text.casefold())
    latin = re.findall(r"[a-z0-9_]+", normalized)
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    bigrams = ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]
    return latin + chinese + bigrams


class HashingEmbedder:
    """Deterministic offline embedding fallback based on character n-grams."""

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def encode(self, text: str) -> np.ndarray:
        normalized = re.sub(r"\s+", "", text.casefold())
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for size in (1, 2, 3):
            for index in range(max(0, len(normalized) - size + 1)):
                ngram = normalized[index : index + size]
                digest = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest, "little") % self.dimensions
                vector[bucket] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


def _build_chunk(
    path: Path,
    version: str | None,
    section_buffer: list[str],
    section_heading: str,
    section_start: int,
) -> DocumentChunk | None:
    text = "\n".join(section_buffer).strip()
    if not text:
        return None
    raw_id = f"{path.name}:{section_start}:{section_heading}"
    return DocumentChunk(
        chunk_id=hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12],
        source=path.name,
        heading=section_heading,
        text=text,
        version=version,
        line_start=section_start,
    )


class HybridRetriever:
    def __init__(self, knowledge_dir: Path, rrf_k: int = 60) -> None:
        self.knowledge_dir = knowledge_dir
        self.rrf_k = rrf_k
        self.embedder = HashingEmbedder()
        self.chunks = self._load_chunks()
        if not self.chunks:
            raise ValueError(f"no knowledge chunks found in {knowledge_dir}")
        self._bm25 = BM25Okapi([_tokenize(chunk.text) for chunk in self.chunks])
        self._vectors = np.vstack([self.embedder.encode(chunk.text) for chunk in self.chunks])

    @property
    def version(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.knowledge_dir.glob("*.md")):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()[:16]

    def _load_chunks(self) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for path in sorted(self.knowledge_dir.glob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            version = next(
                (line.split("：", 1)[1].strip() for line in lines if line.startswith("版本：")),
                None,
            )
            heading = path.stem
            buffer: list[str] = []
            start = 1
            for line_number, line in enumerate(lines, 1):
                if line.startswith("## "):
                    chunk = _build_chunk(path, version, buffer, heading, start)
                    if chunk is not None:
                        chunks.append(chunk)
                    buffer = []
                    heading = line[3:].strip()
                    start = line_number
                buffer.append(line)
            chunk = _build_chunk(path, version, buffer, heading, start)
            if chunk is not None:
                chunks.append(chunk)
        return chunks

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if not query.strip():
            return []
        bm25_scores = self._bm25.get_scores(_tokenize(query))
        query_vector = self.embedder.encode(query)
        vector_scores = self._vectors @ query_vector
        bm25_order = np.argsort(-bm25_scores).tolist()
        vector_order = np.argsort(-vector_scores).tolist()
        bm25_ranks = {index: rank + 1 for rank, index in enumerate(bm25_order)}
        vector_ranks = {index: rank + 1 for rank, index in enumerate(vector_order)}
        fused: list[tuple[int, float]] = []
        for index in range(len(self.chunks)):
            score = 1 / (self.rrf_k + bm25_ranks[index]) + 1 / (
                self.rrf_k + vector_ranks[index]
            )
            # Queries with no lexical or vector signal should not manufacture a citation.
            lexical = float(bm25_scores[index])
            semantic = float(vector_scores[index])
            if lexical > 0 or semantic > 0.08:
                fused.append((index, score))
        fused.sort(key=lambda item: item[1], reverse=True)
        return [
            SearchResult(
                chunk=self.chunks[index],
                score=score,
                bm25_rank=bm25_ranks[index],
                vector_rank=vector_ranks[index],
            )
            for index, score in fused[:top_k]
        ]
