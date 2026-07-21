@echo off
REM -- Build LMU Telemetry Pro (.exe onedir) — lanciare su WINDOWS --
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller >nul
py -m PyInstaller TelemetryPro.spec --noconfirm --clean
if errorlevel 1 (
  echo.
  echo BUILD FALLITA - leggi gli errori sopra.
  pause
  exit /b 1
)
echo.
echo OK: dist\LMU_TelemetryPro\LMU_TelemetryPro.exe
pause
