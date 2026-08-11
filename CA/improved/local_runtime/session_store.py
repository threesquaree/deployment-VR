from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from local_runtime.models import DialogueTurn, SessionState


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.RLock()

    def start_session(self, participant_id: str, started_at: Optional[str] = None) -> str:
        timestamp = started_at or utc_now_iso()
        session_id = f"ca-{participant_id}-{uuid4().hex[:8]}"
        state = SessionState(
            session_id=session_id,
            participant_id=str(participant_id),
            started_at=timestamp,
            last_interaction_at=timestamp,
        )
        with self._lock:
            self._sessions[session_id] = state
        return session_id

    def ensure_session(
        self,
        session_id: str,
        participant_id: str,
        started_at: Optional[str] = None,
    ) -> SessionState:
        timestamp = started_at or utc_now_iso()
        key = str(session_id)
        participant = str(participant_id or session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = SessionState(
                    session_id=key,
                    participant_id=participant,
                    started_at=timestamp,
                    last_interaction_at=timestamp,
                )
                self._sessions[key] = session
            elif participant and not session.participant_id:
                session.participant_id = participant
            return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            return self._sessions.get(session_id)

    def set_current_object(self, session_id: str, object_name: Optional[str]) -> Optional[SessionState]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.current_object_name = object_name
            return session

    def get_current_object(self, session_id: str) -> Optional[str]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return session.current_object_name

    def set_current_aoi(self, session_id: str, aoi_name: Optional[str]) -> Optional[SessionState]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.current_aoi_name = aoi_name
            return session

    def get_current_aoi(self, session_id: str) -> Optional[str]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return session.current_aoi_name

    def append_history(
        self,
        session_id: str,
        speaker: str,
        text: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> Optional[DialogueTurn]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            turn = DialogueTurn(
                speaker=speaker,
                text=text,
                timestamp=timestamp or utc_now_iso(),
                metadata=dict(metadata or {}),
            )
            session.dialogue_history.append(turn)
            session.turn_count += 1
            session.last_interaction_at = turn.timestamp
            return turn

    def get_history(self, session_id: str) -> List[DialogueTurn]:
        session = self.get_session(session_id)
        if session is None:
            return []
        return list(session.dialogue_history)

    def set_last_agent_reply(self, session_id: str, text: Optional[str]) -> Optional[SessionState]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.last_agent_reply = text
            return session

    def get_last_agent_reply(self, session_id: str) -> Optional[str]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return session.last_agent_reply

    def set_last_interaction_at(self, session_id: str, timestamp: Optional[str]) -> Optional[SessionState]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.last_interaction_at = timestamp
            return session

    def get_last_interaction_at(self, session_id: str) -> Optional[str]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return session.last_interaction_at

    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)
