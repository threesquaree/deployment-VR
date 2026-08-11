from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStartRequest(BaseModel):
    session_id: Optional[str] = None
    participant_id: Optional[str] = None
    actor_node_id: Optional[str] = None
    started_at: Optional[str] = None
    started_at_local: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionStartResponse(BaseModel):
    session_id: str
    model_name: str
    started_at: str


class TurnRequest(BaseModel):
    session_id: str
    user_text: str = ""
    current_object_name: Optional[str] = None
    current_aoi_name: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    session_id: str
    timestamp: str
    reply_text: str
    action: Optional[str] = None
    option: Optional[str] = None
    subaction: Optional[str] = None
    target_exhibit: Optional[str] = None
    mapped_exhibit: Optional[str] = None
    current_exhibit: Optional[str] = None
    should_end: bool = False
    error: Optional[str] = None
    debug: Dict[str, Any] = Field(default_factory=dict)


class SessionEndRequest(BaseModel):
    session_id: str
    reason: str = "manual_end"
    ended_at: str = Field(default_factory=utc_now_iso)


class SessionEndResponse(BaseModel):
    session_id: str
    ended_at: str
    total_turns: int
    log_path: str


class HealthResponse(BaseModel):
    status: str
    model_name: str
    checkpoint_path: str
    knowledge_graph_path: str
    mapping_path: str
    log_dir: str
    loaded_at: str
    active_sessions: int


class SessionSummary(BaseModel):
    session_id: str
    participant_id: Optional[str]
    actor_node_id: Optional[str]
    started_at: str
    ended_at: str
    reason: str
    model_name: str
    total_turns: int
    current_exhibit: Optional[str]
    log_path: str
    rl_state: Dict[str, Any] = Field(default_factory=dict)


class InteractionRecord(BaseModel):
    timestamp: str
    session_id: str
    turn_id: Optional[str] = None
    agent_mode: str = "RL"
    source: str = "RL"
    user_text: str
    reply_text: str
    action_label: Optional[str] = None
    current_object_name: Optional[str] = None
    current_aoi_name: Optional[str] = None
    referenced_object: Optional[str] = None
    referenced_aoi: Optional[str] = None
    turn_number: int
    turn_start_ts: Optional[str] = None
    user_asr_end_ts: Optional[str] = None
    agent_send_ts: Optional[str] = None
    agent_tts_start_ts: Optional[str] = None
    agent_tts_end_ts: Optional[str] = None
    mapped_exhibit: Optional[str] = None
    action: Optional[str] = None
    option: Optional[str] = None
    subaction: Optional[str] = None
    trigger_source: Optional[str] = None
    action_selection_source: Optional[str] = None
    response_type: Optional[str] = None
    target_exhibit: Optional[str] = None
    option_count_snapshot: Dict[str, int] = Field(default_factory=dict)
    facts_mentioned_snapshot: Dict[str, List[str]] = Field(default_factory=dict)
    coverage_snapshot: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    debug: Dict[str, Any] = Field(default_factory=dict)
