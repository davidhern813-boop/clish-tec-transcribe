@echo off
title Clish Tec Transcribe
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python 3.10+ from python.org first ^(tick "Add to PATH"^). & pause & exit /b)
if not exist venv (
  echo First-time setup, please wait...
  python -m venv venv
  call venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate
)
python clish_tec_transcribe.py
