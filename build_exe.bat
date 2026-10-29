@echo off
setlocal
cd /d "%~dp0"
title Build Calculator Pro

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo.
  echo [ERROR] Python was not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during setup, then run this file again.
  goto :end
)
echo Using: %PY%
%PY% --version

if not exist calculator_pro_v3.py (
  echo [ERROR] calculator_pro_v3.py must be in the same folder as this file.
  goto :end
)

echo.
echo [1/2] Installing requirements...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo [ERROR] Installing packages failed. Check your internet connection. & goto :end )

echo.
echo [2/2] Building the program (this takes a few minutes)...
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed --name CalculatorPro --collect-all customtkinter --collect-submodules sympy --collect-data sympy --collect-data matplotlib calculator_pro_v3.py
if errorlevel 1 ( echo [ERROR] Build failed. Copy the messages above and send them for help. & goto :end )

echo.
echo ================================================
echo  DONE. Your program is here:
echo  %~dp0dist\CalculatorPro\CalculatorPro.exe
echo ================================================
start "" "%~dp0dist\CalculatorPro"

:end
echo.
pause
endlocal

