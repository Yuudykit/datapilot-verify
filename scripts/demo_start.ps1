# DataPilot Verify 面试演示一键启动
# 用法：右键"使用 PowerShell 运行"，或命令行执行 .\demo_start.ps1
# 功能：检测服务是否已启动 -> 未启动则启动 -> 等待健康检查通过 -> 打开浏览器

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "$Root\.conda-env\python.exe"
if (-not (Test-Path $Python)) { $Python = "$Root\.venv\Scripts\python.exe" }
$Port = 8767
$Url = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "==== DataPilot Verify 演示启动 ====" -ForegroundColor Cyan

# ---- 1. 环境自检 ----
if (-not (Test-Path $Python)) {
    Write-Host "[X] 未找到 Python 环境: $Python" -ForegroundColor Red
    Write-Host "    期望位置: $Root\.conda-env\python.exe 或 $Root\.venv\Scripts\python.exe" -ForegroundColor Yellow
    Read-Host "按回车退出"; exit 1
}
if (-not (Test-Path "$Root\webapp\streamlit_app.py")) {
    Write-Host "[X] 未找到应用入口: $Root\webapp\streamlit_app.py" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

# ---- 2. 检测服务是否已在运行 ----
function Test-Service {
    try {
        $resp = Invoke-WebRequest -Uri "$Url/_stcore/health" -TimeoutSec 2 -UseBasicParsing
        return ($resp.StatusCode -eq 200 -and $resp.Content -match "ok")
    } catch { return $false }
}

$env:DATAPILOT_QUIET = "1"
if (Test-Service) {
    Write-Host "[OK] 服务已在运行，无需重复启动" -ForegroundColor Green
} else {
    # 端口被非本服务进程占用时给出提示（Streamlit 会启动失败）
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $owner = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "[X] 端口 $Port 被其他进程占用: $($owner.ProcessName) (PID $($conn.OwningProcess))" -ForegroundColor Red
        Write-Host "    请先关闭该进程或更换端口后重试" -ForegroundColor Yellow
        Read-Host "按回车退出"; exit 1
    }

    Write-Host "[..] 正在启动服务（独立窗口运行）..." -ForegroundColor Yellow
    Start-Process -FilePath $Python `
        -ArgumentList "-m", "streamlit", "run", "webapp\streamlit_app.py", `
                      "--server.address", "127.0.0.1", "--server.port", "$Port" `
        -WorkingDirectory $Root

    # ---- 3. 健康检查轮询（最多 30 秒）----
    $ok = $false
    foreach ($i in 1..15) {
        Start-Sleep -Seconds 2
        if (Test-Service) { $ok = $true; break }
        Write-Host "    等待服务就绪... ($($i*2)s)" -ForegroundColor DarkGray
    }
    if (-not $ok) {
        Write-Host "[X] 30 秒内服务未就绪，请查看弹出的启动窗口报错信息" -ForegroundColor Red
        Read-Host "按回车退出"; exit 1
    }
    Write-Host "[OK] 服务启动成功" -ForegroundColor Green
}

# ---- 4. 工作区数据自检 ----
$ordersOk = Test-Path "$Root\workspace\orders.csv"
$storesOk = Test-Path "$Root\workspace\stores.csv"
if ($ordersOk -and $storesOk) {
    Write-Host "[OK] 工作区数据就绪 (orders.csv + stores.csv)" -ForegroundColor Green
} else {
    Write-Host "[!] 工作区缺数据文件，服务会自动从样例补回，首次分析前请确认侧边栏已显示数据" -ForegroundColor Yellow
}

# ---- 5. 模式提示 ----
$envFile = "$Root\.env"
if (Test-Path $envFile) {
    $mode = (Select-String -Path $envFile -Pattern "DATAPILOT_LLM_MODE=(\w+)").Matches[0].Groups[1].Value
    Write-Host "[OK] 当前模式: $mode" -ForegroundColor $(if ($mode -eq "live") { "Magenta" } else { "Green" })
    if ($mode -eq "live") { Write-Host "    每次分析将调用真实模型（DeepSeek），演示前确认额度充足" -ForegroundColor DarkGray }
}

# ---- 6. 打开浏览器 ----
Write-Host "[..] 打开浏览器: $Url"
Start-Process $Url

Write-Host ""
Write-Host "==== 就绪。演示完成后直接关闭 Streamlit 窗口即可停止服务 ====" -ForegroundColor Cyan
Write-Host "提示：如需停止服务，关闭弹出的 Python/Streamlit 控制台窗口，或在其按 Ctrl+C" -ForegroundColor DarkGray
Read-Host "按回车关闭本窗口"
