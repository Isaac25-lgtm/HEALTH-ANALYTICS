# Start (or restart) the local live stack: API on 127.0.0.1:8010 and the web app on http://localhost:3100.
#
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1            # start both
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Rebuild   # rebuild the web app first
#
# Settings come from the gitignored .env in this folder; nothing secret is printed. With
# DASHBOARD_PRECOMPUTE_ENABLED and DHIS2_REFRESH_SCHEDULE_ENABLED set to true there, the API then
# prepares the common dashboards and refreshes DHIS2 data by itself when it is due.
# Logs: %TEMP%\hpip-live. Only processes listening on ports 8010 and 3100 are restarted.
param([switch]$Rebuild)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $env:TEMP "hpip-live"
New-Item -ItemType Directory -Force $log | Out-Null

function Stop-Port([int]$port) {
  $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force -Confirm:$false -ErrorAction SilentlyContinue
  }
}

function Wait-Url([string]$url, [string]$name) {
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
      if ((Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5).StatusCode -eq 200) { "$name is up"; return }
    } catch {}
  }
  "$name did not answer within a minute; see $log"
}

if ($Rebuild) {
  Push-Location (Join-Path $root "frontend")
  npm run build
  Pop-Location
}

Stop-Port 8010
Stop-Port 3100
Start-Sleep -Seconds 2

$env:WEB_ORIGIN = "http://localhost:3100"
Start-Process -FilePath "python" `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010" `
  -WorkingDirectory (Join-Path $root "backend") `
  -RedirectStandardOutput (Join-Path $log "api.out.log") -RedirectStandardError (Join-Path $log "api.err.log") `
  -WindowStyle Hidden
Wait-Url "http://127.0.0.1:8010/health" "API"

$env:BACKEND_INTERNAL_URL = "http://127.0.0.1:8010"
Start-Process -FilePath "node" `
  -ArgumentList "node_modules/next/dist/bin/next", "start", "-p", "3100" `
  -WorkingDirectory (Join-Path $root "frontend") `
  -RedirectStandardOutput (Join-Path $log "web.out.log") -RedirectStandardError (Join-Path $log "web.err.log") `
  -WindowStyle Hidden
Wait-Url "http://localhost:3100/login" "Web app"

"Open http://localhost:3100/login"
