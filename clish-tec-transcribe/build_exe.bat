@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python 3.10+ from python.org first ^(tick "Add to PATH"^). & pause & exit /b)
if not exist venv (
  python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name "Clish Tec Transcribe" --collect-all faster_whisper --collect-all ctranslate2 --collect-all av --collect-all obsws_python --collect-all sounddevice --collect-all _sounddevice_data clish_tec_transcribe.py
echo.
echo DONE. Your app is in:  dist\Clish Tec Transcribe\Clish Tec Transcribe.exe
pause
