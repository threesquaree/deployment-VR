from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class RuntimeLogger:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.log_dir / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def get_session_log_path(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.jsonl"

    def append_jsonl(self, session_id: str, payload: Dict[str, Any]) -> Path:
        path = self.get_session_log_path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return path

    def append_interaction(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "interaction"
        return self.append_jsonl(session_id, record)

    def append_session_summary(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "session_summary"
        return self.append_jsonl(session_id, record)
