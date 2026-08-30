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
        ("import pandas as pd\ngetattr(pd, 'read_csv')", "blocked Python call"),
        ("import pandas as pd\nvars(pd)", "blocked Python call"),
        ("import pandas as pd\npd.eval('1+1')", "blocked Python attribute"),
        (
            "import pandas as pd\ndf.to_csv('out.csv')",
            "blocked Python attribute",
        ),
        (
            "import pandas as pd\npd.read_json('http://example.com/x.json')",
            "injected input_csv",
        ),
        (
            "import pandas as pd\npd.read_pickle(input_csv)",
            None,
        ),
        (
            "import pandas as pd\npd.read_csv(str(input_csv))",
            None,
        ),
        (
            "import pandas as pd\npd.read_csv(str(some_other_path))",
            "injected input_csv",
        ),
    ],
)
def test_blocks_unsafe_code(code: str, message: str | None) -> None:
    if message is None:
        assert PythonPolicy().validate(code) is not None
    else:
        with pytest.raises(ValueError, match=message):
            PythonPolicy().validate(code)

