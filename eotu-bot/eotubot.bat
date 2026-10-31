@echo off
rem Runs the bot: eotubot check ^| teach ^| watch ^| try MACRO ^| run host ^| run join IP ^| report
setlocal
set "PY=%LOCALAPPDATA%\eotu-bot\venv\Scripts\python.exe"
if not exist "%PY%" ( echo Run install.bat first. & exit /b 1 )
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%PY%" -m eotubot %*
