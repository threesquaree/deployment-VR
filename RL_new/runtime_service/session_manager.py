from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from inference.rl_runtime import RLMuseumRuntime


def derive_session_seed(session_id: str) -> int:
    """Stable per-session RNG seed.

    Action selection is stochastic (as in training), so the session needs a seed to
    stay replayable. Python's hash() is salted per process and would give a different
    seed on every server restart, so derive it from a real digest instead.
    """
    digest = hashlib.sha256(str(session_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def turn_seed(session_seed: int, turn_number: int) -> int:
    """Per-turn seed: distinct draws per turn, reproducible from (session, turn)."""
    return (int(session_seed) * 1_000_003 + int(turn_number)) % (2 ** 31 - 1)


@dataclass
class SessionState:
    session_id: str
    participant_id: Optional[str]
    actor_node_id: Optional[str]
    started_at: str
    runtime: RLMuseumRuntime
    dialogue_history: List[Tuple[str, str, int]] = field(default_factory=list)
    conversation_history_rows: List[Dict[str, Any]] = field(default_factory=list)
    current_exhibit: Optional[str] = None
    current_object_name: Optional[str] = None
    current_aoi_name: Optional[str] = None
    last_turn_timestamp: Optional[str] = None
    last_action: Optional[str] = None
    last_agent_reply: str = ""
    has_real_user_turn: bool = False
    session_silence_count: int = 0
    silence_fired_since_last_user_turn: bool = False
    exhibit_silence_count: Dict[str, int] = field(default_factory=dict)
    # Per-turn disengagement flag (E_flat_S2 contract, HANDOFF turn loop step 7):
    # visitor_disengaged = (label == "disengaged"), recomputed every turn -- no
    # latch. While True, dialogue_masks rule 7 restricts the legal set to
    # ["Engage"] and the (still running) policy recovers. Stored here for logging.
    visitor_disengaged: bool = False
    # Consecutive masked-recovery turns; the service caps this at
    # max_consecutive_forced_recover as a deployment guardrail.
    forced_recover_count: int = 0
    # Retained for log continuity; action selection is deterministic argmax under
    # the E_flat_S2 contract, so this no longer influences behaviour.
    rng_seed: int = 0


class SessionManager:
    def __init__(self, runtime_factory):
        self._runtime_factory = runtime_factory
        self._sessions = {}

    def create_session(
        self,
        session_id: Optional[str],
        participant_id: Optional[str],
        actor_node_id: Optional[str],
        started_at: str,
    ) -> SessionState:
        session_id = str(session_id or uuid4().hex)
        state = SessionState(
            session_id=session_id,
            participant_id=participant_id,
            actor_node_id=actor_node_id,
            started_at=started_at,
            runtime=self._runtime_factory(),
            rng_seed=derive_session_seed(session_id),
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
