@echo off
rem After the 4-computer test: zip this laptop's logs + a short system report, named after the
rem laptop, so the team can check afterwards what happened on each machine.
rem
rem   scripts\collect_logs.bat A        (S, A, B or C: see docs\FOUR_PC_TEST.md)
rem
rem Output: logs\four_pc_<ROLE>_<COMPUTERNAME>_<date>.zip (logs\ is git-ignored).
rem Secrets are never included (*.env files are skipped).

setlocal
cd /d "%~dp0.."
set "ROLE=%~1"
if "%ROLE%"=="" set "ROLE=%COMPUTERNAME%"
if not exist logs mkdir logs

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Continue';" ^
  "$stamp = Get-Date -Format 'yyyyMMdd_HHmm';" ^
  "$name = 'four_pc_%ROLE%_' + $env:COMPUTERNAME + '_' + $stamp;" ^
  "$work = Join-Path $env:TEMP $name; New-Item -ItemType Directory -Force $work | Out-Null;" ^
  "Get-ChildItem logs -Recurse -Depth 1 -File -Include *.log,*.txt,*.csv | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-1) } | Copy-Item -Destination $work;" ^
  "$py = if (Test-Path .venv\Scripts\python.exe) { '.venv\Scripts\python.exe' } else { 'py' };" ^
  "$commit = & $py -c 'from netutil.version import commit; print(commit())' 2>$null;" ^
  "$info = @('role:        %ROLE%', ('hostname:    ' + $env:COMPUTERNAME), ('collected:   ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')), ('os:          ' + [Environment]::OSVersion.VersionString), ('python:      ' + (& $py --version 2>&1)), ('commit:      ' + $commit), '', '== IPv4 addresses');" ^
  "$info += Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' } | ForEach-Object { '  ' + $_.IPAddress + '  ' + $_.InterfaceAlias };" ^
  "$info += @('', '== Network profile (must be Private for the server)');" ^
  "$info += Get-NetConnectionProfile | ForEach-Object { '  ' + $_.InterfaceAlias + ': ' + $_.Name + ' -> ' + $_.NetworkCategory };" ^
  "$info += @('', '== Wi-Fi'); $info += (netsh wlan show interfaces | Select-String ' SSID|Band|Radio type') | ForEach-Object { '  ' + $_.Line.Trim() };" ^
  "$info += @('', '== VPN adapters (up)'); $info += Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'VPN|TAP|WireGuard|Tunnel' } | ForEach-Object { '  ' + $_.Name + ' (' + $_.InterfaceDescription + ')' };" ^
  "$info | Set-Content (Join-Path $work 'system_info.txt');" ^
  "$zip = Join-Path (Resolve-Path logs) ($name + '.zip'); Compress-Archive -Path $work -DestinationPath $zip -Force; Remove-Item -Recurse -Force $work;" ^
  "Write-Host ('Saved ' + $zip); Write-Host 'Send it to the team (WhatsApp, USB). It contains no passwords or keys.'"
endlocal
