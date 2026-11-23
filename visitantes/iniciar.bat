@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el Python del entorno en:
    echo "%PYTHON%"
    echo Instale primero las dependencias con:
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Iniciando el servidor GOTUPLAS...
echo Cierre esta ventana o presione Ctrl+C para detenerlo.
"%PYTHON%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo El servidor termino con codigo de error %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
