@echo off
rem Join the public Maze Arena server, TCP version (Windows). Run from the repo folder after
rem the setup in docs\JOIN.md. The server address comes from deploy\public_addresses.env.
rem
rem   scripts\join_tcp.bat --name alice
rem   scripts\join_tcp.bat --name alice --cloudflare    (backup route, needs cloudflared)

setlocal
cd /d "%~dp0.."
set "ROOM=demo"
set "NAME="
set "ROUTE=playit"

:args
if "%~1"=="" goto argsdone
if /i "%~1"=="--name" (set "NAME=%~2" & shift & shift & goto args)
if /i "%~1"=="--cloudflare" (set "ROUTE=cloudflare" & shift & goto args)
echo unknown option: %1   (usage: scripts\join_tcp.bat --name alice)
exit /b 2
:argsdone
if "%NAME%"=="" (
    echo usage: scripts\join_tcp.bat --name alice
    exit /b 2
)

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo no .venv here: do the setup in docs\JOIN.md first
    exit /b 1
)

set "PLAYIT_TCP="
set "CLOUDFLARE_TCP="
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("deploy\public_addresses.env") do set "%%A=%%B"

if "%ROUTE%"=="playit" if "%PLAYIT_TCP%"=="" set "ROUTE=cloudflare"
if "%ROUTE%"=="cloudflare" goto cloudflare

for /f "tokens=1,2 delims=:" %%H in ("%PLAYIT_TCP%") do (set "HOST=%%H" & set "PORT=%%I")
echo TCP server: %PLAYIT_TCP%
"%PY%" -m client_ui.ui --proto tcp --host %HOST% --port %PORT% --name "%NAME%" --room %ROOM%
exit /b %ERRORLEVEL%

:cloudflare
if "%CLOUDFLARE_TCP%"=="" (
    echo no TCP address in deploy\public_addresses.env yet: git pull, or ask the host
    exit /b 1
)
echo TCP server via Cloudflare: %CLOUDFLARE_TCP%
call scripts\tunnel_client.bat %CLOUDFLARE_TCP% --name "%NAME%" --room %ROOM%
exit /b %ERRORLEVEL%
