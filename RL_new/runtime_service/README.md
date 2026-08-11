# RL Runtime Service

This service is the RL-only online runtime for the Unity scene. It does not replace the baseline conversational agent path.

## What it does

- Loads one active exported RL agent from `../runtime_config.json`
- Starts RL sessions for participants
- Accepts Unity turn requests with `user_text`, `current_object_name`, and `current_aoi_name`
- Calls the existing `RLMuseumRuntime` black box
- Appends one JSONL interaction record per turn
- Appends one session summary record on `/session/end`
- Optionally plays local Python TTS if enabled in config

## Run

```powershell
cd C:\Users\Vrmuseum\Desktop\Research\RL
uvicorn runtime_service.api:app --host 127.0.0.1 --port 8000
```

Create `C:\Users\Vrmuseum\Desktop\Research\RL\.env` from `.env.example` before running.

## Endpoints

- `GET /health`
- `POST /session/start`
- `POST /turn`
- `POST /session/end`

## Notes

- `runtime_config.json` is read once at startup. Changing the active exported agent requires a runtime restart.
- Neo4j is not required during online RL operation.
