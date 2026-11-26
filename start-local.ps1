# Local, Docker-free launcher. Everything lives in .tools/ inside the project.
# Postgres runs on 5433 and Redis on 6380 to avoid clashing with other local services.
# Usage: powershell -File start-local.ps1            (fast local mode: staggered startup, cron worker disabled)
#        powershell -File start-local.ps1 -WithCron  (also runs the ARQ cron maintenance worker)
param(
  [switch]$WithCron
)

$r = $PSScriptRoot
$t = "$r\.tools"
$env:UV_CACHE_DIR = "$t\uv-cache"
$env:XDG_CACHE_HOME = "$t\cache"
$env:TORCH_HOME = "$t\cache\torch"
$env:TEMP = "$t\tmp"
$env:TMP = "$t\tmp"
$env:WORKER_CPU_THREADS = "2"
$env:FFMPEG_THREADS = "2"
$env:OMP_NUM_THREADS = "2"
$env:MKL_NUM_THREADS = "2"
New-Item -ItemType Directory -Force "$t\cache\torch", "$t\tmp" | Out-Null
$env:Path = "$t\pnpm\node_modules\.bin;$t\tesseract;$env:Path"

function Start-Svc($title, $cmd) {
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='$title'; $cmd"
}

function Wait-Port($port, $timeoutSec = 180) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $c = New-Object System.Net.Sockets.TcpClient
      $ar = $c.BeginConnect('127.0.0.1', $port, $null, $null)
      if ($ar.AsyncWaitHandle.WaitOne(500) -and $c.Connected) { $c.Close(); return $true }
      $c.Close()
    } catch {}
    Start-Sleep -Milliseconds 500
  }
  return $false
}

Start-Svc "postgres" "& '$t\pgsql\bin\postgres.exe' -D '$t\pgdata' -p 5433"
Start-Svc "redis" "Set-Location '$t\redis'; .\redis-server.exe --port 6380"
Wait-Port 5433 60 | Out-Null
Wait-Port 6380 60 | Out-Null

# Stagger heavy Python/Node startups so they don't thrash RAM/pagefile simultaneously.
Start-Svc "backend" "Set-Location '$r\backend'; & .\.venv\Scripts\uvicorn.exe src.main:app --host 0.0.0.0 --port 8000"
Write-Host "Waiting for backend API on port 8000..."
Wait-Port 8000 300 | Out-Null

$cronFlag = if ($WithCron) { '1' } else { '0' }
Start-Svc "worker" "Set-Location '$r\backend'; `$env:EMBED_CRON_WORKER='$cronFlag'; & .\.venv\Scripts\python.exe -m src.workers.run_workers"

# Production server (fast). Build once first: cd frontend; $env:NEXT_OUTPUT='default'; pnpm exec next build --turbopack
Start-Svc "frontend" "`$env:NEXT_OUTPUT='default'; `$env:Path='$t\pnpm\node_modules\.bin;'+`$env:Path; Set-Location '$r\frontend'; pnpm exec next start --port 3107"
Wait-Port 3107 180 | Out-Null
Write-Host "Open http://localhost:3107  (API docs: http://localhost:8000/docs)"
