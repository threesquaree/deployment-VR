from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from inference.exhibit_mapping import ExhibitMapping
from inference.rl_runtime import RLMuseumRuntime
from runtime_service.logger import RuntimeLogger
from runtime_service.schemas import InteractionRecord, SessionSummary, TurnResponse
from runtime_service.session_manager import SessionManager, SessionState


class LocalTTS:
    def __init__(self, enabled: bool, rate: int = 180):
        self.enabled = enabled
        self.rate = rate
        self._engine = None
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker = None
        self._init_failed = False
        if self.enabled:
            self._worker = threading.Thread(target=self._run, name="rl-local-tts", daemon=True)
            self._worker.start()

    def speak(self, text: str) -> None:
        if not self.enabled or not text or self._init_failed:
            return
        self._queue.put(text)

    def _ensure_engine(self) -> bool:
        if self._engine is not None:
            return True
        try:
            import pyttsx3
        except Exception:
            self._init_failed = True
            self.enabled = False
            return False
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            return True
        except Exception:
            self._init_failed = True
            self.enabled = False
            self._engine = None
            return False

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if not text:
                continue
            if not self._ensure_engine():
                continue
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception:
                self._engine = None


class RuntimeService:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path).resolve()
        self.config = self._load_config(self.config_path)
        self.mapping = ExhibitMapping(self.config["mapping_path"])
        self.logger = RuntimeLogger(self.config["log_dir"])
        self.tts = LocalTTS(
            enabled=bool(self.config.get("tts_enabled", False)),
            rate=int(self.config.get("tts_rate", 180)),
        )
        self._health_runtime = self._build_runtime()
        self.session_manager = SessionManager(self._build_runtime)

    @staticmethod
    def _load_config(config_path: Path) -> Dict[str, Any]:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _build_runtime(self) -> RLMuseumRuntime:
        return RLMuseumRuntime(
            checkpoint_path=self.config["checkpoint_path"],
            knowledge_graph_path=self.config["knowledge_graph_path"],
            mapping_path=self.config["mapping_path"],
            device=self.config.get("device", "cpu"),
            model_name=self.config.get("openai_model", "gpt-4o-mini"),
        )

    def start_session(
        self,
        participant_id: Optional[str],
        actor_node_id: Optional[str],
        started_at: str,
    ) -> SessionState:
        return self.session_manager.create_session(
            participant_id=participant_id,
            actor_node_id=actor_node_id,
            started_at=started_at,
        )

    def _resolve_current_exhibit(
        self,
        session: SessionState,
        current_object_name: Optional[str],
    ) -> str:
        if current_object_name:
            normalized_object_name = self.mapping.normalize_object_name(current_object_name)
            try:
                mapped = self.mapping.to_exhibit_key(normalized_object_name)
            except ValueError:
                mapped = None
            if mapped:
                session.current_object_name = normalized_object_name
                session.current_exhibit = mapped
                return mapped
        if session.current_exhibit:
            return session.current_exhibit
        raise ValueError(
            "No valid current exhibit. Provide a mapped current_object_name or establish one earlier in the session."
        )

    def handle_turn(
        self,
        session_id: str,
        user_text: str,
        current_object_name: Optional[str],
        current_aoi_name: Optional[str],
        timestamp: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnResponse:
        metadata = metadata or {}
        session = self.session_manager.get_session(session_id)
        current_exhibit = self._resolve_current_exhibit(session, current_object_name)
        normalized_aoi = self.mapping.normalize_aoi(current_aoi_name) if current_aoi_name else None
        session.current_aoi_name = normalized_aoi
        session.last_turn_timestamp = timestamp

        result = session.runtime.generate_turn(
            user_message=user_text,
            exhibit=current_exhibit,
            dialogue_history=session.dialogue_history,
        )
        turn_number = session.runtime.turn_number
        session.dialogue_history.append(("user", user_text, turn_number - 1))
        session.dialogue_history.append(("assistant", result["response"], turn_number - 1))
        session.current_exhibit = result.get("mapped_exhibit") or current_exhibit

        snapshot = session.runtime.get_state_snapshot()
        interaction = InteractionRecord(
            timestamp=timestamp,
            session_id=session.session_id,
            user_text=user_text,
            reply_text=result["response"],
            current_object_name=session.current_object_name or current_object_name,
            current_aoi_name=normalized_aoi,
            turn_number=turn_number,
            mapped_exhibit=result.get("mapped_exhibit"),
            action=result.get("action"),
            option=result.get("option"),
            subaction=result.get("subaction"),
            target_exhibit=result.get("target_exhibit"),
            option_count_snapshot=snapshot["option_counts"],
            facts_mentioned_snapshot=snapshot["facts_mentioned"],
            coverage_snapshot=snapshot["coverage"],
            debug={
                "input_exhibit": result.get("input_exhibit"),
                "metadata": metadata,
            },
        )
        log_path = self.logger.append_interaction(session.session_id, interaction.dict())
        self.tts.speak(result["response"])

        return TurnResponse(
            session_id=session.session_id,
            timestamp=timestamp,
            reply_text=result["response"],
            action=result.get("action"),
            option=result.get("option"),
            subaction=result.get("subaction"),
            target_exhibit=result.get("target_exhibit"),
            mapped_exhibit=result.get("mapped_exhibit"),
            current_exhibit=session.current_exhibit,
            debug={
                "log_path": str(log_path),
                "coverage_snapshot": snapshot["coverage"],
            },
        )

    def end_session(self, session_id: str, ended_at: str, reason: str) -> SessionSummary:
        session = self.session_manager.pop_session(session_id)
        snapshot = session.runtime.get_state_snapshot()
        summary = SessionSummary(
            session_id=session.session_id,
            participant_id=session.participant_id,
            actor_node_id=session.actor_node_id,
            started_at=session.started_at,
            ended_at=ended_at,
            reason=reason,
            model_name=self.config["model_name"],
            total_turns=snapshot["turn_number"],
            current_exhibit=session.current_exhibit,
            log_path=str(self.logger.get_session_log_path(session_id)),
            rl_state=snapshot,
        )
        self.logger.append_session_summary(session.session_id, summary.dict())
        return summary

