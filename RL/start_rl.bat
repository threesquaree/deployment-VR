@echo off
REM ============================================================
REM  RL study launcher  -  starts the STT service + the RL runtime
REM  Double-click this file, or run it from a terminal.
REM  Two windows open and must STAY open during the study.
REM     Window 1 = Whisper STT     (port 5065, speech-to-text)
REM     Window 2 = RL runtime API  (port 8000, policy + LLM + TTS)
REM  Close both windows to stop the RL agent.
REM
REM  This is the RL counterpart of CA\start_baseline.bat.
REM  Do NOT run both launchers at once - they share the STT service
REM  and Unity can only point at one agent at a time.
REM ============================================================

set "ROOT=C:\Users\s3533204\Downloads\Research\Research"

echo Starting Whisper STT (5065)...
start "Whisper STT (5065)" cmd /k "cd /d %ROOT% && stt\.venv\Scripts\python.exe stt\service.py"

REM small stagger so the two model loads don't fight over startup I/O
timeout /t 3 >nul

echo Starting RL runtime (8000)...
start "RL runtime (8000)" cmd /k "cd /d %ROOT%\RL && .venv\Scripts\python.exe -m uvicorn runtime_service.api:app --host 127.0.0.1 --port 8000"

echo.
echo Both windows launched.
echo   - Window 1 (STT) should say: "[stt] serving on http://127.0.0.1:5065"
echo         and above it:          "model loaded + verified ... on cuda" (or cpu)
echo   - Window 2 (RL)  should say: "Application startup complete."
echo         and:                   "Uvicorn running on http://127.0.0.1:8000"
echo.
echo Sanity check (optional), in any terminal:
echo     curl http://127.0.0.1:8000/health
echo     curl http://127.0.0.1:5065/health
echo Both should return status ok. /health also echoes which checkpoint loaded.
echo.
echo Then start Unity with Agent Mode = RL on the GetEyeData object.
echo RL sessions are written to %ROOT%\data\sessions\rl
echo (baseline study data lives in ...\data\sessions\baseline)
echo.
echo IMPORTANT: if the STT window is not up, speech will NOT be captured.
echo.
pause
