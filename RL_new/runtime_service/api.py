from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException

from runtime_service.schemas import (
    HealthResponse,
    SessionEndRequest,
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
    TurnRequest,
    TurnResponse,
)
from runtime_service.service import RuntimeService


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


CONFIG_PATH = Path(__file__).resolve().parents[1] / "runtime_config.json"
service = RuntimeService(str(CONFIG_PATH))
app = FastAPI(title="RL Museum Runtime", version="1.0.0")
LOADED_AT = utc_now_iso()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model_name=service.config["model_name"],
        checkpoint_path=service.config["checkpoint_path"],
        knowledge_graph_path=service.config["knowledge_graph_path"],
        mapping_path=service.config["mapping_path"],
        log_dir=service.config["log_dir"],
        loaded_at=LOADED_AT,
        active_sessions=service.session_manager.active_count(),
    )


@app.post("/session/start", response_model=SessionStartResponse)
def start_session(payload: SessionStartRequest) -> SessionStartResponse:
    started_at = payload.started_at or utc_now_iso()
    session = service.start_session(
        session_id=payload.session_id,
        participant_id=payload.participant_id,
        actor_node_id=payload.actor_node_id,
        started_at=started_at,
        started_at_local=payload.started_at_local,
    )
    return SessionStartResponse(
        session_id=session.session_id,
        model_name=service.config["model_name"],
        started_at=started_at,
    )


@app.post("/turn", response_model=TurnResponse)
def turn(payload: TurnRequest) -> TurnResponse:
    try:
        return service.handle_turn(
            session_id=payload.session_id,
            user_text=payload.user_text,
            current_object_name=payload.current_object_name,
            current_aoi_name=payload.current_aoi_name,
            timestamp=payload.timestamp,
            metadata=payload.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/session/end", response_model=SessionEndResponse)
def end_session(payload: SessionEndRequest) -> SessionEndResponse:
    try:
        summary = service.end_session(
            session_id=payload.session_id,
            ended_at=payload.ended_at,
            reason=payload.reason,
        )
        return SessionEndResponse(
            session_id=summary.session_id,
            ended_at=summary.ended_at,
            total_turns=summary.total_turns,
            log_path=summary.log_path,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
