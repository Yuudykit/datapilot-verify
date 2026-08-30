from pathlib import Path

import pytest

from datapilot_verify.sandbox import PythonRunner

ROOT = Path(__file__).resolve().parents[1]


def test_runs_controlled_pandas_analysis(tmp_path: Path) -> None:
    code = (
        "import pandas as pd\n"
        "frame = pd.read_csv(input_csv)\n"
        "result = {'rows': int(len(frame)), "
        "'net': int((frame['paid_amount'] - frame['refund_amount']).sum())}\n"
    )
    run = PythonRunner(timeout_seconds=10).run(
        code,
        ROOT / "data" / "sample" / "orders.csv",
        tmp_path,
    )
    assert run.ok, run.stderr
    assert run.result["rows"] == 3123


def test_reader_cannot_choose_arbitrary_path(tmp_path: Path) -> None:
    code = "import pandas as pd\nresult = pd.read_csv('C:/secret.csv').head().to_dict()"
    with pytest.raises(ValueError, match="injected input_csv"):
        PythonRunner().run(code, ROOT / "data" / "sample" / "orders.csv", tmp_path)

