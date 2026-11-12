from pathlib import Path

from datapilot_verify.eval.runner import run_eval

ROOT = Path(__file__).resolve().parents[1]


def test_offline_eval_is_all_green() -> None:
    report = run_eval(ROOT)
    assert report.passed == report.total
    assert report.metric_resolution_accuracy == 1.0
    assert report.retrieval_recall_at_5 == 1.0
    assert report.execution_accuracy == 1.0
    assert report.numeric_consistency == 1.0

