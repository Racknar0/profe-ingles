@echo off
cd /d "%~dp0"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do set IP=%%a
set IP=%IP: =%
echo.
echo ========================================================
echo   APP WEB LISTA PARA CELULAR Y PC
echo   PC:      http://localhost:8080
echo   Celular: http://%IP%:8080  (mismo Wi-Fi)
echo ========================================================
echo.
python -m http.server 8080 --bind 0.0.0.0
