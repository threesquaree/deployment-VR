from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DialogueTurn:
    speaker: str
    text: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    session_id: str
    participant_id: str
    started_at: str
    current_object_name: Optional[str] = None
    current_aoi_name: Optional[str] = None
    dialogue_history: List[DialogueTurn] = field(default_factory=list)
    last_agent_reply: Optional[str] = None
    last_interaction_at: Optional[str] = None
    turn_count: int = 0
