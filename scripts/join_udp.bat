@echo off
rem Join the public Maze Arena server, UDP version (Windows). Run from the repo folder after
rem the setup in docs\JOIN.md. The server address comes from deploy\public_addresses.env.
rem
rem   scripts\join_udp.bat --name alice

setlocal
cd /d "%~dp0.."
set "ROOM=demo"
set "NAME="

:args
if "%~1"=="" goto argsdone
if /i "%~1"=="--name" (set "NAME=%~2" & shift & shift & goto args)
echo unknown option: %1   (usage: scripts\join_udp.bat --name alice)
exit /b 2
:argsdone
if "%NAME%"=="" (
    echo usage: scripts\join_udp.bat --name alice
    exit /b 2
)

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo no .venv here: do the setup in docs\JOIN.md first
    exit /b 1
)

set "PLAYIT_UDP="
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("deploy\public_addresses.env") do set "%%A=%%B"
if "%PLAYIT_UDP%"=="" (
    echo no UDP address in deploy\public_addresses.env yet: git pull, or ask the host
    exit /b 1
)

for /f "tokens=1,2 delims=:" %%H in ("%PLAYIT_UDP%") do (set "HOST=%%H" & set "PORT=%%I")
echo UDP server: %PLAYIT_UDP%
"%PY%" -m client_ui.ui --proto udp --host %HOST% --port %PORT% --name "%NAME%" --room %ROOM%
exit /b %ERRORLEVEL%
