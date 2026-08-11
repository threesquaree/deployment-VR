from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


class ConversationLogger:
    def __init__(self, base_dir: Optional[Path] = None):
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
        self.log_dir = root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_session_start(
        self,
        session_id: str,
        participant_id: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_dir: Optional[Path] = None,
    ) -> Path:
        payload = {
            "event": "session_start",
            "session_id": str(session_id),
            "participant_id": str(participant_id),
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
        return self._append(session_id, payload, session_dir=session_dir)

    def log_turn(
        self,
        session_id: str,
        source_actor: Any,
        target_actor: Any,
        text: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_dir: Optional[Path] = None,
    ) -> Path:
        payload = {
            "event": "turn",
            "session_id": str(session_id),
            "source_actor": str(source_actor),
            "target_actor": str(target_actor),
            "text": text,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
        return self._append(session_id, payload, session_dir=session_dir)

    def log_session_end(
        self,
        session_id: str,
        reason: str = "manual_end",
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_dir: Optional[Path] = None,
    ) -> Path:
        payload = {
            "event": "session_end",
            "session_id": str(session_id),
            "reason": reason,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
        return self._append(session_id, payload, session_dir=session_dir)

    def _append(self, session_id: str, payload: Dict[str, Any], session_dir: Optional[Path] = None) -> Path:
        log_path = (Path(session_dir) / "conversation.jsonl") if session_dir else (self.log_dir / f"conversation_{session_id}.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return log_path
