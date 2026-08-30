from pathlib import Path

from datapilot_verify.rag import HybridRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_retrieves_metric_definition_with_citation() -> None:
    retriever = HybridRetriever(ROOT / "data" / "knowledge")
    results = retriever.search("净销售额要扣除退款吗")
    assert results
    assert results[0].chunk.heading == "净销售额"
    assert "退款金额" in results[0].chunk.text
    assert results[0].chunk.source == "01_核心指标口径.md"


def test_retrieves_version_change() -> None:
    retriever = HybridRetriever(ROOT / "data" / "knowledge")
    results = retriever.search("净销售额历史口径什么时候变更")
    assert any("2026-01-01" in result.chunk.heading for result in results[:3])

