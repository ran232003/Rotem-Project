@echo off
rem Opens the dashboard in the browser. Double-click this, or make a shortcut to
rem it on the desktop.
rem
rem The console window it leaves behind is the dashboard itself. Closing it
rem closes the dashboard; it does not stop the agent.

rem ASCII only: a .bat runs under the OEM codepage, where Hebrew would mangle.
title Draft Agent Dashboard

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m rotem_agent.cli dashboard %*
) else (
    python -m rotem_agent.cli dashboard %*
)

if errorlevel 1 (
    echo.
    echo The dashboard could not start. The message above says why.
    pause
)
