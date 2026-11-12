@echo off
rem One command for the Windows build. Run from anywhere, or double-click.
rem   build.cmd          create .venv if missing, install dependencies, build, then --check the new exe
rem   build.cmd --close  same, but first close a Late Night Pal running from dist (it locks the files)
rem Result: dist\Late Night Pal\Late Night Pal.exe and dist\LateNightPal-win64.zip
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [1/3] Creating .venv ...
    py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv || goto :failed
)
echo [1/3] Installing dependencies ...
"%PY%" -m pip install --disable-pip-version-check -q -e ".[build]" || goto :failed

echo [2/3] Building (about 2 minutes) ...
"%PY%" packaging\build_release.py %* || goto :failed

echo [3/3] Done. Double-click "%~dp0dist\Late Night Pal\Late Night Pal.exe"
set "RC=0"
goto :end

:failed
echo BUILD FAILED - see the messages above.
set "RC=1"

:end
rem Keep the window open when started by double-click (this cmd's parent is Explorer).
powershell -NoProfile -Command "$cmd = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)).ParentProcessId; $by = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $cmd)).ParentProcessId; if ((Get-Process -Id $by -ErrorAction SilentlyContinue).ProcessName -eq 'explorer') { exit 1 }"
if errorlevel 1 pause
exit /b %RC%
