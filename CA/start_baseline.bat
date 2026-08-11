@echo off
REM ============================================================
REM  Baseline study launcher  -  starts the STT service + BOTH Rasa servers
REM  Double-click this file, or run it from a terminal.
REM  Three windows open and must STAY open during the study.
REM     Window 1 = Whisper STT        (port 5065, speech-to-text)
REM     Window 2 = Rasa server        (port 5005, ~2-3 min boot)
REM     Window 3 = Rasa action server (port 5055, LLM + Alba TTS)
REM  Close all three windows to stop the baseline agent.
REM ============================================================

set "RASA_LICENSE=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIwMWM2NTNhMy0zNWMyLTQxOTgtOTM5OC1kNGFlNWQzNzNlMTUiLCJpYXQiOjE3NTk4Mjg4MjIsIm5iZiI6MTc1OTgyODgyMSwic2NvcGUiOiJyYXNhOnBybyByYXNhOnBybzpjaGFtcGlvbiByYXNhOnZvaWNlIiwiZXhwIjoxODU0NTIzMjIxLCJlbWFpbCI6InAuYi52YW5kZXJrYWFkZW5Ac3R1ZGVudC51dHdlbnRlLm5sIiwiY29tcGFueSI6IlJhc2EgQ2hhbXBpb25zIn0.4y3oTMBrUvzsDR6YB-9mkiD4cszQatfCiX5o6P0d1JWMQ37U6rERnscVwg1VnjFzQkp9vY18gfBqx7lZPOy1600-FsWHZXdDBI2c5J4xiwBpgG8IIRndQPmScG6R1Gzc6Q1m1hXDPWvfu-vNB9GhpZaslREEiVpWreFzfcuaLkGejdaQ36Bt0UpwrtcGIJ8EDYMZTY6dckSUoeMSBkZdJrp0OdfgdD3krj4PbwieOG-ZwRoQeaLtBzyVEFZmZjVjZrCtFkusIxdXk35vdIPYo4HbPEenwIcJhwyDiLhVAx64a8-dzDSPE04ygZ57ezV9HZfZ8evWrY1AUYnmvllOgQ"

set "PY=C:\Users\s3533204\Downloads\Research\Research\CA\original\.venv\Scripts\python.exe"
set "PROJ=C:\Users\s3533204\Downloads\Research\Research\CA\improved"
set "MODEL=models/20260424-175151-greedy-extra.tar.gz"

echo Starting Whisper STT (5065)...
start "Whisper STT (5065)" cmd /k "cd /d C:\Users\s3533204\Downloads\Research\Research && stt\.venv\Scripts\python.exe stt\service.py"

REM small stagger so the model load doesn't fight Rasa for startup I/O
timeout /t 3 >nul

echo Starting Rasa server (5005)...
start "Rasa server (5005)" cmd /k "cd /d %PROJ% && "%PY%" -m rasa run -m %MODEL%"

REM small stagger so the two don't fight over startup I/O
timeout /t 3 >nul

echo Starting Rasa action server (5055)...
start "Rasa actions (5055)" cmd /k "cd /d %PROJ% && "%PY%" -m rasa run actions"

echo.
echo All three windows launched.
echo   - Window 1 (STT) should say: "[stt] serving on http://127.0.0.1:5065"
echo         and above it:          "model loaded + verified ... on cuda" (or cpu)
echo   - Wait for Window 2 to say:  "Rasa server is up and running."
echo   - Window 3 should say:       "Action endpoint is up and running on http://0.0.0.0:5055"
echo Then start Unity (Agent Mode = Baseline) and run your participant.
echo.
echo IMPORTANT: if the STT window is not up, speech will NOT be captured.
echo.
pause
