from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone


class RuntimeLogger:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._session_dirs: Dict[str, Path] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _safe_local_tag(started_at_local: str) -> str:
        if not started_at_local:
            return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        candidate = started_at_local.replace(" ", "T")
        if "." in candidate:
            candidate = candidate.split(".", 1)[0]
        if candidate.endswith("Z"):
            candidate = candidate[:-1]
        if "+" in candidate:
            candidate = candidate.split("+", 1)[0]
        if len(candidate) > 6 and candidate[-6] == "-":
            candidate = candidate[:-6]
        candidate = candidate.replace(":", "-")
        return candidate

    def register_session(
        self,
        session_id: str,
        started_at: str,
        started_at_local: str,
        source: str,
        meta: Dict[str, Any],
    ) -> Path:
        safe_sid = str(session_id)
        local_tag = self._safe_local_tag(started_at_local)
        folder_name = f"{source}_{safe_sid}_{local_tag}"
        session_dir = self.log_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        self._session_dirs[safe_sid] = session_dir

        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            payload = dict(meta)
            payload.setdefault("source", source)
            payload.setdefault("session_id", safe_sid)
            payload.setdefault("started_at_utc", started_at)
            payload.setdefault("started_at_local", started_at_local)
            payload.setdefault("schema_version", "sessions_v1")
            with meta_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        return session_dir

    def get_session_dir(self, session_id: str) -> Path:
        sid = str(session_id)
        if sid in self._session_dirs:
            return self._session_dirs[sid]
        fallback = list(self.log_dir.glob(f"rl_{sid}_*"))
        if fallback:
            self._session_dirs[sid] = fallback[0]
            return fallback[0]
        # Defensive fallback if called before register_session.
        return self.register_session(
            sid,
            datetime.now(timezone.utc).isoformat(),
            datetime.now().isoformat(),
            "rl",
            {},
        )

    def get_session_log_path(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "turns.jsonl"

    def get_session_judge_path(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "judge.jsonl"

    def get_session_generation_trace_path(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "generation_trace.jsonl"

    def append_jsonl(self, session_id: str, payload: Dict[str, Any]) -> Path:
        path = self.get_session_log_path(session_id)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return path

    def append_jsonl_to_path(self, path: Path, payload: Dict[str, Any]) -> Path:
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return path

    def update_interaction_tts(
        self,
        session_id: str,
        turn_id: str,
        agent_tts_start_ts: str = None,
        agent_tts_end_ts: str = None,
    ) -> Path:
        path = self.get_session_log_path(session_id)
        if not path.exists():
            return path

        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
            updated = False
            rewritten_lines = []
            for line in lines:
                try:
                    payload = json.loads(line)
                except Exception:
                    rewritten_lines.append(line)
                    continue

                if payload.get("record_type") == "interaction" and payload.get("turn_id") == turn_id:
                    if agent_tts_start_ts is not None:
                        payload["agent_tts_start_ts"] = agent_tts_start_ts
                    if agent_tts_end_ts is not None:
                        payload["agent_tts_end_ts"] = agent_tts_end_ts
                    updated = True
                rewritten_lines.append(json.dumps(payload, ensure_ascii=True))

            if updated:
                path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")
        return path

    def append_interaction(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "interaction"
        return self.append_jsonl(session_id, record)

    def append_session_summary(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "session_summary"
        return self.append_jsonl(session_id, record)

    def append_judge(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "judge"
        path = self.get_session_judge_path(session_id)
        return self.append_jsonl_to_path(path, record)

    def append_generation_trace(self, session_id: str, payload: Dict[str, Any]) -> Path:
        record = dict(payload)
        record["record_type"] = "generation_trace"
        path = self.get_session_generation_trace_path(session_id)
        return self.append_jsonl_to_path(path, record)
