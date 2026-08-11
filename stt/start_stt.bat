@echo off
REM ============================================================
REM  Local Whisper speech-to-text service  (port 5065)
REM  Replaces Windows dictation, which dropped 25-55% of turns.
REM  Keep this window OPEN during the study.
REM
REM  Wait for:  [stt] model loaded + verified in X.Xs on cuda
REM             [stt] serving on http://127.0.0.1:5065
REM
REM  "on cuda" = GPU (fast, ~150ms/turn).
REM  "on cpu"  = still fine (~1.1s/turn); GPU DLLs just weren't found.
REM ============================================================

cd /d "%~dp0.."

REM Uncomment to force CPU if the GPU ever misbehaves mid-study:
REM set STT_DEVICE=cpu

stt\.venv\Scripts\python.exe stt\service.py

echo.
echo STT service exited. Speech capture will NOT work until this is restarted.
pause
