@echo off
rem One-time setup: creates a virtual environment, installs dependencies, starts Popper.
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
    echo Could not create a virtual environment. Install Python 3.10+ from https://www.python.org and try again.
    pause
    exit /b 1
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo Installing dependencies failed.
    pause
    exit /b 1
)

echo Starting Popper. Look for the small card in the bottom-right corner of your screen.
start "" .venv\Scripts\pythonw.exe word_popper.py
