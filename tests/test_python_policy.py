import pytest

from datapilot_verify.sandbox import PythonPolicy


def test_allows_data_analysis_code() -> None:
    code = "import pandas as pd\nresult = pd.DataFrame({'x': [1, 2]}).sum()"
    PythonPolicy().validate(code)


@pytest.mark.parametrize(
    "code, message",
    [
        ("import os", "blocked Python import"),
        ("open('secret.txt').read()", "blocked Python call"),
        ("import pandas as pd\npd.io.common.os.remove('x')", "blocked Python attribute"),
        ("x = (1).__class__", "blocked Python attribute"),
    ],
)
def test_blocks_unsafe_code(code: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PythonPolicy().validate(code)

