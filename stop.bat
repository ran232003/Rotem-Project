@echo off
rem Stops the agent without needing the dashboard. Double-click this, or use the
rem red desktop icon, which points at the interpreter directly and so does not
rem flash a console at all.
rem
rem The result arrives as a message box rather than as text here: a .bat console
rem runs under the OEM codepage, where Hebrew would be unreadable.

rem ASCII only, for the same reason.
title Stop Draft Agent

cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m rotem_agent.cli stop --dialog %*
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m rotem_agent.cli stop --dialog %*
) else (
    python -m rotem_agent.cli stop --dialog %*
)
