@echo off
rem Double-click to play Maze Arena on the public server (Windows).
rem First run: creates .venv and installs pygame-ce (needs Python 3.10+ and internet).
rem Every run: fetches the current server addresses from GitHub, asks TCP or UDP, starts the game.
setlocal
cd /d "%~dp0"
title Maze Arena
set "ADDR_URL=https://raw.githubusercontent.com/bayaCh05/maze-arena/main/deploy/public_addresses.env"
set "ROOM=demo"

if exist ".venv\Scripts\python.exe" goto ready
set "SYSPY="
where py >nul 2>&1 && set "SYSPY=py -3"
if not defined SYSPY (where python >nul 2>&1 && python -c "import sys" >nul 2>&1 && set "SYSPY=python")
if not defined SYSPY (
    echo Python is not installed. Install it from https://www.python.org/downloads/
    echo and TICK "Add python.exe to PATH" in the installer. Then double-click this file again.
    start "" https://www.python.org/downloads/
    pause
    exit /b 1
)
echo First run: setting up the game (about 1 minute)...
%SYSPY% -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q pygame-ce || (echo Could not install pygame-ce: check your internet & pause & exit /b 1)

:ready
rem Fresh addresses (the ZIP may be older than the server); keep the local file if offline.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 '%ADDR_URL%' -OutFile 'deploy\public_addresses.env.new'; Move-Item -Force 'deploy\public_addresses.env.new' 'deploy\public_addresses.env' } catch { }" >nul 2>&1

set "PLAYIT_TCP="
set "PLAYIT_UDP="
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("deploy\public_addresses.env") do set "%%A=%%B"

echo.
echo   MAZE ARENA
echo   1 = TCP version
echo   2 = UDP version
set "CHOICE=1"
set /p "CHOICE=Choose 1 or 2 [1]: "
set "PROTO=tcp"
set "ADDR=%PLAYIT_TCP%"
if "%CHOICE%"=="2" (set "PROTO=udp" & set "ADDR=%PLAYIT_UDP%")
echo Same Wi-Fi as the host? Type the host's IP (e.g. 192.168.1.23).
set "LAN="
set /p "LAN=Otherwise just press Enter for the internet server: "
if defined LAN set "ADDR=%LAN%:5050"
if "%ADDR%"=="" (
    echo The internet %PROTO% address is not published yet: ask the host for their IP and type it.
    pause
    exit /b 1
)
for /f "tokens=1,2 delims=:" %%H in ("%ADDR%") do (set "HOST=%%H" & set "PORT=%%I")

echo Connecting to %ADDR% (%PROTO%). Type your name in the game window.
.venv\Scripts\python.exe -m client_ui.ui --proto %PROTO% --host %HOST% --port %PORT% --room %ROOM%
if errorlevel 1 (
    echo.
    echo The game stopped with an error ^(see above^). Is the host's server on? Try the other version, or a phone hotspot.
    pause
)
