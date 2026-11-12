$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".conda-env\python.exe"
if (-not (Test-Path $Python)) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python -m streamlit run webapp\streamlit_app.py `
  --server.address 127.0.0.1 --server.port 8767
