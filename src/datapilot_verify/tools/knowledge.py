from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from datapilot_verify.domain.models import EvidenceRef, ToolResult
from datapilot_verify.rag import HybridRetriever
from datapilot_verify.semantic import SemanticRepository
from datapilot_verify.tools.base import Tool, ToolContext, tool


class ResolveMetricArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=3, ge=1, le=10)


class SearchMetricDocsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


def build_knowledge_tools(
    semantic_path: Path, knowledge_dir: Path
) -> tuple[Tool, Tool]:
    semantic = SemanticRepository(semantic_path)
    retriever = HybridRetriever(knowledge_dir)

    @tool(
        name="resolve_metric",
        description="Resolve a business metric to its authoritative structured definition.",
        args_model=ResolveMetricArgs,
        stage="knowledge",
    )
    def resolve_metric(
        *, args: ResolveMetricArgs, context: ToolContext, trace_id: str
    ) -> ToolResult:
        matches = semantic.resolve(args.query, limit=args.limit)
        evidence = [
            EvidenceRef(
                evidence_id=f"metric:{match.metric.metric_id}:{match.metric.version}",
                kind="metric",
                label=match.metric.name,
                source=str(semantic.path),
                version=match.metric.version,
                metadata={"semantic_version": semantic.version},
            )
            for match in matches
        ]
        return ToolResult(
            ok=True,
            data={
                "matches": [
                    {
                        "score": round(match.score, 4),
                        "matched_text": match.matched_text,
                        "metric": match.metric.model_dump(mode="json"),
                    }
                    for match in matches
                ],
                "semantic_version": semantic.version,
            },
            evidence=evidence,
            warnings=[] if matches else ["No matching metric definition was found."],
            trace_id=trace_id,
        )

    @tool(
        name="search_metric_docs",
        description=(
            "Search metric explanations, changes, exceptions, and business guidance "
            "with citations."
        ),
        args_model=SearchMetricDocsArgs,
        stage="knowledge",
    )
    def search_metric_docs(
        *, args: SearchMetricDocsArgs, context: ToolContext, trace_id: str
    ) -> ToolResult:
        results = retriever.search(args.query, top_k=args.top_k)
        evidence = [
            EvidenceRef(
                evidence_id=f"doc:{result.chunk.chunk_id}",
                kind="document",
                label=result.chunk.heading,
                source=result.chunk.source,
                locator=f"line:{result.chunk.line_start}",
                version=result.chunk.version,
                metadata={"knowledge_version": retriever.version},
            )
            for result in results
        ]
        return ToolResult(
            ok=True,
            data={
                "results": [
                    {
                        "chunk_id": result.chunk.chunk_id,
                        "heading": result.chunk.heading,
                        "text": result.chunk.text,
                        "source": result.chunk.source,
                        "line_start": result.chunk.line_start,
                        "version": result.chunk.version,
                        "score": round(result.score, 6),
                    }
                    for result in results
                ],
                "knowledge_version": retriever.version,
            },
            evidence=evidence,
            warnings=[] if results else ["No supporting document was found."],
            trace_id=trace_id,
        )

    return resolve_metric, search_metric_docs

