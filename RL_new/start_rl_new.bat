@echo off
REM ============================================================
REM  RL study launcher (RL_new)  -  STT service + the RL runtime
REM  Double-click this file, or run it from a terminal.
REM  Two windows open and must STAY open during the study.
REM     Window 1 = Whisper STT     (port 5065, speech-to-text)
REM     Window 2 = RL runtime API  (port 8000, policy + LLM + TTS)
REM  Close both windows to stop the RL agent.
REM
REM  This runs the CURRENT RL agent in RL_new:
REM     checkpoint = F2_flat_learn_both ep1000 (deploy_bundle: flat policy,
REM                  31-d obs, 6 actions, deterministic argmax, masks from
REM                  summary.json -- stall + clarify masks retired, the policy
REM                  learned dead-end transitions itself)
REM     LLM        = openai/gpt-5.4  (same model as the baseline arm)
REM     voice      = Piper, shared with CA\improved\actions.py
REM  The older RL\start_rl.bat launches the PREVIOUS agent
REM  (H1_MDP_Hybrid_AntiSpam_AugReward, gpt-4o-mini, pyttsx3 voice).
REM  It starts without any error, so use THIS file for the study.
REM
REM  Do NOT run this together with CA\start_baseline.bat - they share
REM  the STT service and Unity can only point at one agent at a time.
REM
REM  Python: RL_new has no venv of its own; it runs on RL\.venv
REM  (Python 3.8, torch 2.4.1+cpu). The policy path no longer loads
REM  DialogueBERT/transformers, so the RL window starts noticeably faster.
REM ============================================================

set "ROOT=C:\Users\s3533204\Downloads\Research\Research"
set "PY=%ROOT%\RL\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo ERROR: Python interpreter not found at %PY%
    echo The RL runtime cannot start. Check that RL\.venv still exists.
    pause
    exit /b 1
)

echo Starting Whisper STT (5065)...
start "Whisper STT (5065)" cmd /k "cd /d %ROOT% && stt\.venv\Scripts\python.exe stt\service.py"

REM small stagger so the two model loads don't fight over startup I/O
timeout /t 3 >nul

echo Starting RL runtime (8000) from RL_new...
start "RL runtime (8000) - RL_new" cmd /k "cd /d %ROOT%\RL_new && ..\RL\.venv\Scripts\python.exe -m uvicorn runtime_service.api:app --host 127.0.0.1 --port 8000"

echo.
echo Both windows launched.
echo   - Window 1 (STT) should say: "[stt] serving on http://127.0.0.1:5065"
echo         and above it:          "model loaded + verified ... on cuda" (or cpu)
echo   - Window 2 (RL)  should say: "Application startup complete."
echo         and:                   "Uvicorn running on http://127.0.0.1:8000"
echo         and near the top:      "Piper TTS prewarmed (voice=en_GB-alba-medium)"
echo.
echo Sanity check (optional), in any terminal:
echo     curl http://127.0.0.1:8000/health
echo     curl http://127.0.0.1:5065/health
echo Both should return status ok. /health also echoes which checkpoint loaded -
echo it must say model_name F2_flat_learn_both_ep1000.
echo.
echo Then start Unity with Agent Mode = RL on the GetEyeData object.
echo RL sessions are written to %ROOT%\data\sessions\rl
echo (baseline study data lives in ...\data\sessions\baseline)
echo.
echo IMPORTANT: if the STT window is not up, speech will NOT be captured.
echo.
pause
