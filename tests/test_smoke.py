from datapilot_verify import __version__
from datapilot_verify.config import Settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_default_mode_is_mock(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspace",
        artifact_root=tmp_path / "artifacts",
    )
    assert settings.llm_mode == "mock"

