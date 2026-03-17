# RL Branch Log

## 2026-03-11 - Initial Plan and Branch Setup

Author: Codex

Summary:
- Added an RL-only runtime branch design that keeps the baseline conversational agent intact.
- Chosen runtime shape: Unity -> FastAPI runtime -> `RLMuseumRuntime` -> OpenAI -> optional Python local TTS.
- Chosen log shape: one JSONL interaction per turn, one session summary at session end, offline Neo4j export later.

Confirmed decisions:
- Baseline conversational agent stays unchanged.
- RL route does not require Rasa online.
- RL route does not require Neo4j online.
- `runtime_config.json` is the single active model config.
- Changing exported RL agents means updating config and restarting runtime.
- Unity owns stable gaze and dwell logic.
- RL runtime does not auto-fallback to baseline on failure.
- RL runtime uses its own `.env` and Python environment.

Planned files:
- `runtime_config.json`
- `runtime_service/`
- `tools/export_logs_to_neo4j.py`
- `VR_RCEA/VR/Assets/MyScripts/RLCommunication.cs`

Validation target:
- `uvicorn runtime_service.api:app --host 127.0.0.1 --port 8000`
- Unity RL mode talking to local runtime without touching the baseline path

Notes for maintainers:
- Keep appending to this file. Do not rewrite prior entries.
- Record the date, author, change summary, impact scope, and validation result for every future change.

## 2026-03-11 - Runtime Service and Unity RL Route Implemented

Author: Codex

Summary:
- Added `runtime_config.json`, `requirements-runtime.txt`, `.env.example`, and `runtime_service/` for the RL branch.
- Added `RLCommunication.cs` and `AgentMode.cs`.
- Patched `GetEyeData.cs` to route baseline vs RL without modifying `RasaCommunication.cs`.
- Added JSONL logging, session summary logging, and a basic offline Neo4j export script.

Impact scope:
- New RL runtime branch only.
- Baseline route remains present and still uses `RasaCommunication` when `AgentMode.Baseline` is selected.

Validation:
- Python syntax check passed for new RL Python files via `python -m py_compile`.
- Runtime import currently blocked in the local environment because `fastapi` is not installed yet.

Follow-up:
- Create `RL/.env` from `.env.example`.
- Install `RL/requirements-runtime.txt` into the RL virtual environment.
- In Unity, assign `AgentMode`, `RLCommunication`, and `outputText` in the inspector before testing RL mode.

## 2026-03-11 - RL Environment Installed

Author: Codex

Summary:
- Created `RL/.venv`.
- Installed runtime web dependencies: FastAPI, Uvicorn, OpenAI, python-dotenv, pyttsx3, neo4j.
- Installed model/runtime dependencies: torch, numpy, transformers.

Validation:
- `from runtime_service.api import app` now succeeds in `RL/.venv`.
- `import torch, fastapi, transformers` succeeds in `RL/.venv`.
- Transformers attempted to reach Hugging Face for `bert-base-uncased`; network access is blocked in this environment, but the current code falls back and does not stop runtime import.

Remaining setup:
- Create `RL/.env` with the OpenAI API key.
- If you want fully local BERT assets, pre-cache `bert-base-uncased`; otherwise the recognizer will use its fallback path when download access is unavailable.

## 2026-03-11 - RL .env Created

Author: Codex

Summary:
- Created `RL/.env` using the existing OpenAI key format already used by the baseline CA branch.
- RL runtime no longer needs to rely on `CA/original/.env` at run time.

Validation:
- `RL/.env` now exists and matches the expected `api_key=...` format used by `RL/prompt/openai_generator.py`.

## 2026-03-11 - Scene Naming Update

Author: Codex

Summary:
- Renamed the scene object `RasaManager` to `AgentManager` in `teleport_area_version.unity` to reflect dual baseline/RL use.

Validation:
- The object name in `teleport_area_version.unity` now uses `AgentManager`.
## 2026-03-11 - RL Runtime Decoupled from Neo4j Start Path

Author: Codex

Summary:
- Live debugging showed RL sessions were never starting because GetEyeData.StartDataCollection(...) still created Neo4j actor/measure nodes before calling rl.StartSession(...).
- Updated GetEyeData.cs so AgentMode.RL starts the RL session directly and does not require Neo4j actor/measure creation.
- Updated RL mode to skip ProcessDatabaseQueries(...) entirely so runtime gaze processing no longer depends on Neo4j being online.

Impact scope:
- RL route only.
- Baseline route keeps the existing Neo4j-backed start and gaze write behavior.

Validation:
- Runtime diagnosis before the change showed active_sessions: 0, skip=no_active_session, and Unity Neo4j connection failures.
- After this change, RL mode should be able to start a session and record locally even when Neo4j is offline.

## 2026-03-12 - RL Turn Object Selection Fallback Added

Author: Codex

Summary:
- Updated RL turn routing in GetEyeData.cs to prefer the stable dwell-based object/AOI, but fall back to the latest raw gaze hit when no stable focus has been established yet.
- Applied the same fallback to periodic RL prompting so RL mode behaves closer to the baseline scene flow.

Impact scope:
- RL route only.
- Baseline route continues using its original immediate gaze-to-Neo4j behavior.

Validation:
- This change addresses runtime 400 responses caused by missing current_exhibit when the visitor speaks before dwelling on a mapped exhibit for the full stability threshold.

## 2026-03-12 - RL Turn Payload Logging Added

Author: Codex

Summary:
- Added explicit Unity-side debug logging in RLCommunication.cs for the final turn payload fields sent to the runtime.
- The debug log now records user_text, current_object_name, and current_aoi_name at dispatch time.

Impact scope:
- RL route only.
- No baseline behavior changes.

Validation:
- This change is intended to make a single Unity test run sufficient to diagnose whether exhibit selection is failing before or after the HTTP request reaches the runtime.

## 2026-03-12 - Runtime Object Name Normalization Added

Author: Codex

Summary:
- Live Unity logs showed RL turns were being sent with object names like B1_Painting, while the RL mapping only recognized canonical object IDs like B1.
- Updated the runtime mapping layer to normalize Unity object names before exhibit lookup.
- The runtime now accepts canonical IDs, names with _AoI_ suffixes, and names whose leading token is a supported object ID.

Impact scope:
- RL runtime only.
- Unity no longer needs to pre-normalize B1_Painting-style names for exhibit mapping to succeed.

Validation:
- This change targets the observed 400 responses where Unity sent current_object=B1_Painting and the runtime rejected the turn with no valid current exhibit.

## 2026-03-12 - Runtime .env Override Enabled

Author: Codex

Summary:
- Updated RL OpenAI environment loading to use `override=True` when reading `RL/.env`.
- This prevents an empty or stale `api_key` in the parent shell environment from masking the valid key stored in `RL/.env`.

Impact scope:
- RL runtime only.
- No Unity-side changes.

Validation:
- This change targets the observed case where the runtime was launched from `RL/` with a valid `.env` present but still returned `Missing OpenAI API key in env var 'api_key'`.

## 2026-03-13 - Current Exhibit Resolution Scheme v1 Implemented

Author: Codex

Summary:
- Updated Unity-side RL current exhibit selection to follow a strict v1 rule: `stable valid exhibit > recent raw valid exhibit > None`.
- Restricted RL-bound visual grounding to the currently supported exhibit set only: `B1`, `B2`, `B3`, `C5`, `C6`.
- Added normalization on the Unity side so scene object names such as `B1_Painting` or `C6_AoI_Ring` collapse to canonical RL object IDs before being used as current exhibit candidates.
- Added a short raw fallback window (`rawFocusFallbackWindowSeconds = 1.0`) so the latest valid raw gaze hit can support a turn when stable dwell has not yet been reached, without persisting indefinitely.

Impact scope:
- RL route only.
- Baseline route remains unchanged.

Implementation details:
- `stableCurrentObjectName` is now only populated for supported RL objects.
- The latest valid raw RL object/AOI is tracked separately from generic `lastFocusedObject`.
- `GetPreferredCurrentObjectName()` now returns only:
  1. stable supported RL exhibit
  2. recent raw supported RL exhibit within the fallback window
  3. empty string, which maps downstream to `None`
- Unsupported objects no longer enter the RL current exhibit path.

Why this change was made:
- The previous fallback behavior was too permissive because it could reuse any recent raw gaze object, including unsupported scene objects.
- The RL state space currently only supports five exhibit IDs plus `None`, so a more complex carry-over design would have added runtime complexity without increasing the information actually sent to the policy.

Validation target:
- In RL mode, Unity should now send only canonical supported exhibit IDs or an empty current object.
- This should reduce invalid exhibit grounding while keeping early-turn speech usable before stable dwell completes.

Residual limitation:
- This v1 scheme still does not include dialogue carry-over or question-type-aware routing.
- `None` remains a valid no-grounding state, but downstream no-exhibit handling still needs separate evaluation.

## 2026-03-13 - RL Branch End-to-End Text Generation Confirmed, TTS Enabled

Author: Codex

Summary:
- Confirmed that the Unity -> runtime -> RL -> OpenAI main path is now working end to end.
- A live RL turn for `B1` successfully produced a mapped exhibit (`Diego_Bemba`), selected `Explain/ExplainNewFact`, and generated a natural-language reply that was written to the session log.
- The lack of audible output was traced to configuration rather than generation failure: `tts_enabled` in `runtime_config.json` was still set to `false`.
- Enabled runtime-side local TTS by updating `runtime_config.json` to set `tts_enabled` to `true`.

Impact scope:
- RL runtime only.
- Baseline route remains unchanged.

Validation:
- Unity debug log recorded a successful `TurnResponse` instead of `LocalError`.
- Session log `50cd66a91df543b4b3d2e66f74969dcd.jsonl` contains a completed interaction record with `reply_text`, action metadata, and coverage update.

Operational note:
- Runtime must be restarted after this config change for local TTS playback to take effect.

## 2026-03-13 - Runtime TTS Made Asynchronous

Author: Codex

Summary:
- Live testing after enabling local TTS showed that the main RL path was working, but `/turn` responses could still time out in Unity when runtime-side TTS was enabled.
- The root cause was synchronous Python TTS execution inside the HTTP request path: the runtime generated the reply, then blocked inside `pyttsx3.runAndWait()` before returning the HTTP response.
- This caused Unity request timeouts and allowed a later periodic `prompting_user` turn to overlap with an already active pyttsx3 run loop, producing `run loop already started`.
- Updated `LocalTTS` in `runtime_service/service.py` to use a background worker thread and a queue so speech playback no longer blocks `/turn` responses.

Impact scope:
- RL runtime only.
- No Unity-side behavior changes required.

Validation:
- `python -m py_compile runtime_service/service.py` passed after the change.
- The fix specifically targets the observed sequence: successful audible playback, followed by Unity request timeout, followed by `run loop already started` on the next turn.

Operational note:
- Restart the FastAPI runtime after this code change before retesting.
