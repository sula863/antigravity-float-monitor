@echo off
cd /d "%~dp0"
set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python.exe
)
"%PYTHON_EXE%" "%~dp0simulate_task.py"
pause
