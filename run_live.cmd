@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

if "%~1"=="" (
  set "CFG=cfg\live.cfg"
) else (
  set "CFG=%~1"
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\run_live_cfg.py --cfg "%CFG%"
) else (
  python scripts\run_live_cfg.py --cfg "%CFG%"
)

endlocal
