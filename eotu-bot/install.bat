@echo off
rem Installs the Empires of the Undergrowth bot on Windows. Double-click it, or run it in a terminal.
setlocal
cd /d "%~dp0"
set "DATA=%LOCALAPPDATA%\eotu-bot"
set "VENV=%DATA%\venv"
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 is not installed. Installing it with winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
)
if not defined PY (
  echo Could not find or install Python. Install Python 3.12 from python.org, then run this again.
  pause
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
  echo Making a private Python environment in %VENV%
  %PY% -m venv "%VENV%" || ( echo Making the environment failed. & pause & exit /b 1 )
)
echo Installing numpy, mss and Pillow...
"%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt || ( echo Installing failed. & pause & exit /b 1 )
echo.
echo Done. In this folder run:
echo   eotubot check            (with the game running, Borderless or Windowed)
echo   eotubot teach            (show it your screen, once)
echo   eotubot run host         (this PC hosts)   or   eotubot run join HOST_IP
echo When the bot hosts, allow Python through Windows Firewall on private networks if asked.
pause
