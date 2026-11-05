@echo off
rem Client side of the Cloudflare Tunnel bonus on Windows: start "cloudflared access tcp"
rem in the background, wait until its local port listens, start the game client on
rem 127.0.0.1:<local port>, and stop cloudflared when the game window closes.
rem
rem   scripts\tunnel_client.bat maze.example.com --name alice --room demo
rem   set LOCAL_PORT=15051 & scripts\tunnel_client.bat maze.example.com --name bob --room demo
rem
rem First argument: the tunnel hostname. Everything after it goes to the game client.
rem Env: LOCAL_PORT (default 15050), CLOUDFLARED (default: cloudflared on PATH).
rem Close the game window to quit. If you press Ctrl-C and answer Y instead, cloudflared
rem keeps running: taskkill /IM cloudflared.exe /F

setlocal
cd /d "%~dp0.."

if "%~1"=="" (
    echo usage: scripts\tunnel_client.bat maze.^<your domain^> [--name alice --room demo]
    exit /b 2
)
set "TUNNEL_HOST=%~1"
shift
set "CLIENT_ARGS="
:collect
if "%~1"=="" goto collected
set "CLIENT_ARGS=%CLIENT_ARGS% %1"
shift
goto collect
:collected

if "%LOCAL_PORT%"=="" set "LOCAL_PORT=15050"
if "%CLOUDFLARED%"=="" set "CLOUDFLARED=cloudflared"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if not exist logs mkdir logs
set "CF_LOG=%CD%\logs\cloudflared_access_%LOCAL_PORT%.log"

where "%CLOUDFLARED%" >nul 2>&1
if errorlevel 1 if not exist "%CLOUDFLARED%" (
    echo cloudflared not found. Install it: winget install --id Cloudflare.cloudflared
    echo then open a NEW terminal so PATH is updated. See docs\cloudflare_tunnel.md
    exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %LOCAL_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
    echo local port %LOCAL_PORT% is already in use ^(an old cloudflared?^). Use another one:
    echo   set LOCAL_PORT=15051 ^& scripts\tunnel_client.bat %TUNNEL_HOST% ...
    echo or stop the old one: taskkill /IM cloudflared.exe /F
    exit /b 1
)

echo cloudflared access tcp --hostname %TUNNEL_HOST% --url localhost:%LOCAL_PORT%  (log: %CF_LOG%)
set "CF_PID="
for /f %%P in ('powershell -NoProfile -Command "(Start-Process -FilePath '%CLOUDFLARED%' -ArgumentList 'access','tcp','--hostname','%TUNNEL_HOST%','--url','localhost:%LOCAL_PORT%' -NoNewWindow -RedirectStandardError '%CF_LOG%' -PassThru).Id"') do set "CF_PID=%%P"
if "%CF_PID%"=="" (
    echo could not start cloudflared
    exit /b 1
)

powershell -NoProfile -Command "$end = (Get-Date).AddSeconds(15); while ((Get-Date) -lt $end) { if (Get-NetTCPConnection -LocalPort %LOCAL_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 }; if (-not (Get-Process -Id %CF_PID% -ErrorAction SilentlyContinue)) { exit 2 }; Start-Sleep -Milliseconds 200 }; exit 1"
if errorlevel 2 (
    echo cloudflared exited:
    type "%CF_LOG%"
    exit /b 1
)
if errorlevel 1 (
    echo localhost:%LOCAL_PORT% not open after 15 s, see %CF_LOG%
    taskkill /PID %CF_PID% /F >nul 2>&1
    exit /b 1
)

echo local port %LOCAL_PORT% open; starting the game on 127.0.0.1:%LOCAL_PORT%
"%PY%" -m client_ui.ui --proto tcp --host 127.0.0.1 --port %LOCAL_PORT%%CLIENT_ARGS%
set "RC=%ERRORLEVEL%"

echo stopping cloudflared (pid %CF_PID%)
taskkill /PID %CF_PID% /F >nul 2>&1
exit /b %RC%
