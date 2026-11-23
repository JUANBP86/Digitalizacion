@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro Python en el entorno .venv.
    echo Instale las dependencias con: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1"
if errorlevel 1 pause
