from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from uuid import uuid4

from inference.rl_runtime import RLMuseumRuntime


@dataclass
class SessionState:
    session_id: str
    participant_id: Optional[str]
    actor_node_id: Optional[str]
    started_at: str
    runtime: RLMuseumRuntime
    dialogue_history: List[Tuple[str, str, int]] = field(default_factory=list)
    current_exhibit: Optional[str] = None
    current_object_name: Optional[str] = None
    current_aoi_name: Optional[str] = None
    last_turn_timestamp: Optional[str] = None


class SessionManager:
    def __init__(self, runtime_factory):
        self._runtime_factory = runtime_factory
        self._sessions = {}

    def create_session(
        self,
        participant_id: Optional[str],
        actor_node_id: Optional[str],
        started_at: str,
    ) -> SessionState:
        session_id = uuid4().hex
        state = SessionState(
            session_id=session_id,
            participant_id=participant_id,
            actor_node_id=actor_node_id,
            started_at=started_at,
            runtime=self._runtime_factory(),
        )
        self._sessions[session_id] = state
        return state

    def get_session(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session_id '{session_id}'")
        return self._sessions[session_id]

    def pop_session(self, session_id: str) -> SessionState:
        state = self.get_session(session_id)
        del self._sessions[session_id]
        return state

    def active_count(self) -> int:
        return len(self._sessions)
