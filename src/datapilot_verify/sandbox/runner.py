from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datapilot_verify.sandbox.policy import PythonPolicy


@dataclass(frozen=True)
class PythonRunResult:
    ok: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None
    timed_out: bool = False


class PythonRunner:
    """Best-effort local worker for trusted single-user analysis code."""

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds
        self.policy = PythonPolicy()

    def run(self, code: str, input_csv: Path, output_dir: Path) -> PythonRunResult:
        self.policy.validate(code)
        input_csv = input_csv.resolve()
        output_dir = output_dir.resolve()
        if not input_csv.is_file():
            raise FileNotFoundError(input_csv)
        output_dir.mkdir(parents=True, exist_ok=True)
        harness = self._harness(code, input_csv, output_dir)
        script_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                prefix="analysis_",
                dir=output_dir,
                encoding="utf-8",
                delete=False,
            ) as handle:
                handle.write(harness)
                script_path = Path(handle.name)
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                cwd=output_dir,
                env=self._clean_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return PythonRunResult(
                ok=False,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
            )
        finally:
            if script_path is not None:
                script_path.unlink(missing_ok=True)
        marker = "__DATAPILOT_RESULT__="
        result = None
        stdout_lines = []
        for line in completed.stdout.splitlines():
            if line.startswith(marker):
                result = json.loads(line[len(marker) :])
            else:
                stdout_lines.append(line)
        return PythonRunResult(
            ok=completed.returncode == 0 and result is not None,
            result=result,
            stdout="\n".join(stdout_lines),
            stderr=completed.stderr[-4000:],
            return_code=completed.returncode,
        )

    @staticmethod
    def _harness(code: str, input_csv: Path, output_dir: Path) -> str:
        return f'''import json
from pathlib import Path

input_csv = Path({str(input_csv)!r})
output_dir = Path({str(output_dir)!r})
result = None

{code}

print("__DATAPILOT_RESULT__=" + json.dumps(result, ensure_ascii=False, default=str))
'''

    @staticmethod
    def _clean_environment() -> dict[str, str]:
        keep = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        return {key: value for key, value in os.environ.items() if key.upper() in keep}
