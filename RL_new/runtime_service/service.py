from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from inference.exhibit_mapping import ExhibitMapping
from inference.response_type_classifier import (
    ClassificationContext,
    ResponseTypeResult,
    SOURCE_ERROR_FALLBACK,
    SOURCE_FOCUS_CHANGE,
    SOURCE_METADATA,
    SOURCE_SILENCE_FLAG,
    build_classifier,
)
from inference.silence_handler import ConversationSnapshot, SilenceHandler
from inference.bundle_loader import to_contract_label
from inference.rl_runtime import RLMuseumRuntime
from runtime_service.logger import RuntimeLogger
from runtime_service.schemas import InteractionRecord, SessionSummary, TurnResponse, utc_now_iso
from runtime_service.session_manager import SessionManager, SessionState


tts_logger = logging.getLogger("runtime_service.tts")
if not tts_logger.handlers:
    _tts_handler = logging.StreamHandler()
    _tts_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    tts_logger.addHandler(_tts_handler)
tts_logger.setLevel(logging.INFO)
tts_logger.propagate = False

silence_logger = logging.getLogger("runtime_service.silence")
if not silence_logger.handlers:
    _silence_handler = logging.StreamHandler()
    _silence_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    silence_logger.addHandler(_silence_handler)
silence_logger.setLevel(logging.INFO)
silence_logger.propagate = False

response_type_logger = logging.getLogger("runtime_service.response_type_service")
if not response_type_logger.handlers:
    _rt_handler = logging.StreamHandler()
    _rt_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    response_type_logger.addHandler(_rt_handler)
response_type_logger.setLevel(logging.INFO)
response_type_logger.propagate = False

# Shared Piper TTS helper (natural voice). The SAME helper + tts_config.json is
# used by the baseline agent (CA\improved\actions.py) so both study conditions
# speak with an identical voice. pyttsx3 remains as automatic fallback.
_TTS_HELPER_DIR = str(Path(__file__).resolve().parents[2] / "tts")
if _TTS_HELPER_DIR not in sys.path:
    sys.path.insert(0, _TTS_HELPER_DIR)
try:
    import piper_tts as _piper_tts
except Exception:  # helper folder missing/broken -> legacy voice
    _piper_tts = None


class LocalTTS:
    def __init__(self, enabled: bool, rate: int = 180, on_tts_update=None):
        self.enabled = enabled
        self.rate = rate
        self._queue: "queue.Queue[Dict[str, Optional[str]]]" = queue.Queue()
        self._worker = None
        self._init_failed = False
        self._on_tts_update = on_tts_update
        if self.enabled:
            if _piper_tts is not None:
                try:
                    _piper_tts.prewarm()
                    tts_logger.info("Piper TTS prewarmed (voice=%s)", _piper_tts.load_config()["voice"])
                except Exception:
                    tts_logger.exception("Piper TTS prewarm failed; will fall back to pyttsx3")
            self._worker = threading.Thread(target=self._run, name="rl-local-tts", daemon=True)
            self._worker.start()
            tts_logger.info("LocalTTS worker started with rate=%s", self.rate)
        else:
            tts_logger.info("LocalTTS is disabled by configuration")

    def speak(self, text: str, session_id: Optional[str] = None, turn_id: Optional[str] = None) -> None:
        if not self.enabled:
            tts_logger.warning("LocalTTS skipped utterance because TTS is disabled")
            return
        if not text:
            tts_logger.warning("LocalTTS skipped empty utterance")
            return
        if self._init_failed and _piper_tts is None:
            tts_logger.warning("LocalTTS skipped utterance because engine initialization already failed")
            return
        self._queue.put(
            {
                "text": text,
                "session_id": str(session_id) if session_id else None,
                "turn_id": str(turn_id) if turn_id else None,
            }
        )
        preview = text[:120].replace("\n", " ")
        tts_logger.info("LocalTTS queued utterance len=%s preview=%r", len(text), preview)

    def _ensure_engine(self) -> bool:
        try:
            import pyttsx3
        except Exception:
            tts_logger.exception("LocalTTS failed to import pyttsx3")
            self._init_failed = True
            self.enabled = False
        return True

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            text = item.get("text") if isinstance(item, dict) else None
            if not text:
                continue
            session_id = item.get("session_id") if isinstance(item, dict) else None
            turn_id = item.get("turn_id") if isinstance(item, dict) else None
            preview = text[:120].replace("\n", " ")

            # --- Piper (natural voice, shared with the baseline agent) ---
            if _piper_tts is not None:
                try:
                    wav_path = _piper_tts.synthesize(text)
                    # agent_tts_start_ts means "audio began": stamp at playback
                    # start, after synthesis has completed.
                    start_ts = utc_now_iso()
                    if self._on_tts_update and session_id and turn_id:
                        self._on_tts_update(session_id, turn_id, agent_tts_start_ts=start_ts)
                    tts_logger.info("LocalTTS speaking utterance via piper len=%s preview=%r", len(text), preview)
                    try:
                        _piper_tts.play(wav_path)
                    finally:
                        try:
                            os.remove(wav_path)
                        except Exception:
                            pass
                    end_ts = utc_now_iso()
                    if self._on_tts_update and session_id and turn_id:
                        self._on_tts_update(session_id, turn_id, agent_tts_end_ts=end_ts)
                    tts_logger.info("LocalTTS finished utterance (piper)")
                    continue
                except Exception:
                    tts_logger.exception("Piper TTS failed; falling back to pyttsx3")

            # --- pyttsx3 fallback (legacy SAPI voice) ---
            if not self._ensure_engine():
                continue
            engine = None
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                tts_logger.info("LocalTTS engine initialized successfully")
                start_ts = utc_now_iso()
                if self._on_tts_update and session_id and turn_id:
                    self._on_tts_update(session_id, turn_id, agent_tts_start_ts=start_ts)
                tts_logger.info("LocalTTS speaking utterance len=%s preview=%r", len(text), preview)
                engine.say(text)
                engine.runAndWait()
                end_ts = utc_now_iso()
                if self._on_tts_update and session_id and turn_id:
                    self._on_tts_update(session_id, turn_id, agent_tts_end_ts=end_ts)
                tts_logger.info("LocalTTS finished utterance")
            except Exception:
                tts_logger.exception("LocalTTS playback failed during per-utterance engine run")
            finally:
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass


class RuntimeService:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path).resolve()
        self.config = self._load_config(self.config_path)
        self.mapping = ExhibitMapping(self.config["mapping_path"])
        self.logger = RuntimeLogger(self.config["log_dir"])
        self.tts = LocalTTS(
            enabled=bool(self.config.get("tts_enabled", False)),
            rate=int(self.config.get("tts_rate", 180)),
            on_tts_update=self.logger.update_interaction_tts,
        )
        # Built on the service, not inside _build_runtime: the label is needed to
        # construct the state vector, so classification happens before
        # generate_turn is ever called. An unknown name raises here, at startup,
        # rather than silently running a study on the wrong classifier.
        self.response_type_classifier_name = str(
            self.config.get("response_type_classifier", "rules_v1")
        )
        self.response_type_classifier = build_classifier(
            self.response_type_classifier_name, self.config
        )
        self.max_consecutive_forced_recover = int(
            self.config.get("max_consecutive_forced_recover", 2)
        )
        self._health_runtime = self._build_runtime()
        # Mask flags come from the checkpoint's own summary.json (read once by the
        # runtime), never from runtime_config.json -- deploy_bundle/HANDOFF.md.
        self.force_recover_on_disengage = bool(
            self._health_runtime.mask_flags["force_recover_on_disengage"]
        )
        self.session_manager = SessionManager(self._build_runtime)

    # Keys that used to change agent behaviour but are now owned by the
    # checkpoint's summary.json (mask flags) or fixed by the E_flat_S2 contract
    # (deterministic argmax, no epsilon, no label remap). A stale value here
    # would silently mis-attribute a study arm, so refuse to start.
    _RETIRED_CONFIG_KEYS = (
        "mask_stall_on_exhausted",
        "mask_clarify_misfire",
        "force_recover_on_disengage",
        "engage_rescue_only",
        "deterministic_action_selection",
        "exploration_epsilon",
        "remap_untrained_response_types",
    )

    @classmethod
    def _load_config(cls, config_path: Path) -> Dict[str, Any]:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
        stale = [key for key in cls._RETIRED_CONFIG_KEYS if key in config]
        if stale:
            raise ValueError(
                "retired config key(s) {0}: mask flags now come from the checkpoint's "
                "summary.json and action selection is deterministic argmax "
                "(deploy_bundle/HANDOFF.md). Remove them from {1}.".format(stale, config_path)
            )
        return config

    def _build_runtime(self) -> RLMuseumRuntime:
        return RLMuseumRuntime(
            checkpoint_path=self.config["checkpoint_path"],
            knowledge_graph_path=self.config["knowledge_graph_path"],
            summary_path=self.config["summary_path"],
            mapping_path=self.config["mapping_path"],
            device=self.config.get("device", "cpu"),
            model_name=self.config.get("openai_model", "gpt-5.4"),
            judge_enabled=bool(self.config.get("judge_enabled", False)),
            judge_fail_policy=str(self.config.get("judge_fail_policy", "pass")),
            exhibit_walk_order=self.config.get("exhibit_walk_order"),
        )

    @staticmethod
    def _clean_user_facing_reply(text: str) -> str:
        cleaned = re.sub(r"\s*\[[A-Z]{2}_\d{3}\]", "", text or "")
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        return cleaned.strip()

    @staticmethod
    def _parse_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _parse_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _classify_response_type(
        self,
        metadata: Dict[str, Any],
        session: Optional[SessionState] = None,
        user_text: str = "",
    ) -> ResponseTypeResult:
        """Resolve this turn's response type, with provenance.

        Precedence is unchanged from the original implementation: an explicit
        label from the caller wins, then the silence flag, then the configured
        classifier. Only the last step differs between rules_v1 and hybrid_v1.
        """
        explicit_response_type = str(metadata.get("response_type") or "").strip()
        if explicit_response_type:
            return ResponseTypeResult(label=explicit_response_type, source=SOURCE_METADATA)

        # A focus-change turn has no visitor utterance to interpret -- the visitor
        # moved their attention without speaking. Classifying "" would burn an LLM
        # call on empty input, and "silence" is wrong (it is not a timeout and must
        # not carry the -0.8 silence weight). "statement" is what env.py falls back to
        # for an absent/unknown label, so use that.
        if str(metadata.get("trigger_source") or "").strip() == "focus_change" and not (user_text or "").strip():
            return ResponseTypeResult(label="statement", source=SOURCE_FOCUS_CHANGE)

        is_silence_event = self._parse_bool(metadata.get("is_silence_event"))
        if is_silence_event:
            # Behavioural, exactly as in training - never inferred from text.
            return ResponseTypeResult(label="silence", source=SOURCE_SILENCE_FLAG)

        if session is None:
            return ResponseTypeResult(label="statement", source=SOURCE_ERROR_FALLBACK, ok=False)

        history = [
            f"{entry[0]}: {entry[1]}"
            for entry in (session.dialogue_history or [])[-4:]
            if len(entry) >= 2
        ]
        ctx = ClassificationContext(
            user_utterance=user_text or "",
            last_agent_reply=session.last_agent_reply or "",
            # last_action is stored as "Option/Subaction"; classifiers compare
            # bare subaction names.
            last_action=(session.last_action or "").split("/")[-1],
            history=history,
            is_silence_event=False,
            off_exhibit_seconds=self._parse_float(metadata.get("off_exhibit_seconds"), 0.0),
        )
        try:
            return self.response_type_classifier.classify(ctx)
        except Exception as exc:
            # Never let classification take down a turn: "statement" is the same
            # value state_builder falls back to for an unknown label.
            response_type_logger.exception("response-type classification failed")
            return ResponseTypeResult(
                label="statement",
                source=SOURCE_ERROR_FALLBACK,
                ok=False,
                error="{0}: {1}".format(type(exc).__name__, exc),
            )

    def _resolve_visitor_disengaged(self, session: SessionState, state_label: str) -> bool:
        """Per-turn disengagement flag for mask rule 7 -- HANDOFF turn loop step 7.

        The contract is `visitor_disengaged = (label == "disengaged")`, recomputed
        every turn with no latch; while True, dialogue_masks restricts the legal
        set to ["Engage"] and the policy (still running, still argmax) recovers.

        DELIBERATE DEVIATION (user decision, 2026-08-02): a real visitor who is
        repeatedly classified as disengaged would be nagged forever, so after
        `max_consecutive_forced_recover` consecutive disengaged turns the flag is
        passed as False for one turn, letting the policy act freely. Logged so the
        deviation is visible in the study data.
        """
        disengaged = state_label == "disengaged"
        if disengaged and self.force_recover_on_disengage:
            if session.forced_recover_count >= self.max_consecutive_forced_recover:
                response_type_logger.warning(
                    "forced-recover cap hit after %d consecutive masked recoveries "
                    "(session=%s) - passing visitor_disengaged=False for this turn",
                    self.max_consecutive_forced_recover, session.session_id,
                )
                session.forced_recover_count = 0
                disengaged = False
            else:
                session.forced_recover_count += 1
        else:
            session.forced_recover_count = 0
        session.visitor_disengaged = disengaged
        return disengaged

    def _silence_allowed(self, session: SessionState, current_exhibit: Optional[str]) -> bool:
        max_per_session = int(self.config.get("max_silence_per_session", 3))
        if session.session_silence_count >= max_per_session:
            return False
        if session.silence_fired_since_last_user_turn:
            return False
        # Per-exhibit cap. This key has been in runtime_config.json all along but was
        # never read, so the limit it advertised was not being applied: a visitor who
        # lingered at one painting could spend the whole session budget there and get
        # nothing at the remaining four. The counter it needs
        # (session.exhibit_silence_count) was already being maintained in handle_turn.
        max_per_exhibit = int(self.config.get("max_silence_per_exhibit", 1))
        if max_per_exhibit > 0:
            exhibit_key = current_exhibit or session.current_exhibit or ""
            if exhibit_key and session.exhibit_silence_count.get(exhibit_key, 0) >= max_per_exhibit:
                return False
        return True

    def _build_silence_snapshot(
        self,
        session: SessionState,
        current_exhibit: Optional[str],
    ) -> ConversationSnapshot:
        exhibit_key = current_exhibit or session.current_exhibit or ""
        facts_mentioned_count = len(session.runtime.facts_mentioned.get(exhibit_key, set())) if exhibit_key else 0
        total_facts_at_exhibit = (
            len(session.runtime.knowledge_graph.get_exhibit_facts(exhibit_key)) if exhibit_key else 0
        )
        action = session.last_action or ""
        if "/" in action:
            last_agent_option, last_agent_subaction = action.split("/", 1)
        else:
            last_agent_option = ""
            last_agent_subaction = action
        return ConversationSnapshot(
            last_agent_option=last_agent_option,
            last_agent_subaction=last_agent_subaction,
            facts_mentioned_count=facts_mentioned_count,
            total_facts_at_exhibit=total_facts_at_exhibit,
        )

    def _select_silence_action(
        self,
        session: SessionState,
        current_exhibit: Optional[str],
    ) -> Dict[str, str]:
        snapshot = self._build_silence_snapshot(session, current_exhibit)
        handler = SilenceHandler(
            threshold_sec=float(self.config.get("silence_timeout_seconds", 40)),
            max_triggers=int(self.config.get("max_silence_per_session", 3)),
        )
        action = handler.select_action(snapshot, triggers_used=session.session_silence_count)
        silence_logger.info(
            "Selected silence override for session=%s trigger=%s action=%s/%s exhibit=%s",
            session.session_id,
            session.session_silence_count + 1,
            action.get("option"),
            action.get("subaction"),
            current_exhibit or session.current_exhibit,
        )
        return action

    def start_session(
        self,
        session_id: Optional[str],
        participant_id: Optional[str],
        actor_node_id: Optional[str],
        started_at: str,
        started_at_local: Optional[str],
    ) -> SessionState:
        session = self.session_manager.create_session(
            session_id=session_id,
            participant_id=participant_id,
            actor_node_id=actor_node_id,
            started_at=started_at,
        )
        self.logger.register_session(
            session_id=session.session_id,
            started_at=started_at,
            started_at_local=started_at_local or started_at,
            source="rl",
            meta={
                "participant_id": participant_id,
                "actor_id": actor_node_id,
                "model_name": self.config["model_name"],
                # Which classifier produced this session's response-type labels.
                # Every session must be attributable to one exact build; the
                # classifier is frozen for the duration of an arm.
                "response_type_classifier": self.response_type_classifier_name,
                "openai_model": self.config.get("openai_model"),
                # E_flat_S2 contract: deterministic argmax over masked logits,
                # mask flags read from the checkpoint's own summary.json. Recorded
                # per session so every arm's flag provenance is in the data.
                "deterministic_action_selection": True,
                "mask_flags": dict(self._health_runtime.mask_flags),
                "summary_path": self.config.get("summary_path"),
                "checkpoint_path": self.config.get("checkpoint_path"),
            },
        )
        return session

    def _resolve_current_exhibit(
        self,
        session: SessionState,
        current_object_name: Optional[str],
    ) -> Optional[str]:
        if current_object_name == "NONE":
            session.current_object_name = "NONE"
            session.current_exhibit = None
            return None
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
        turn_started_at = time.monotonic()
        session = self.session_manager.get_session(session_id)
        is_silence_event = self._parse_bool(metadata.get("is_silence_event"))
        trigger_source = str(metadata.get("trigger_source") or "").strip()
        if not trigger_source:
            trigger_source = "unity_silence_timer" if is_silence_event else "user_input"
        if is_silence_event and not session.has_real_user_turn:
            raise ValueError("Silence events are only allowed after at least one real user turn.")
        current_exhibit = self._resolve_current_exhibit(session, current_object_name)
        if is_silence_event and not self._silence_allowed(session, current_exhibit):
            raise ValueError("Silence event ignored because the configured silence limit was reached.")
        normalized_aoi = self.mapping.normalize_aoi(current_aoi_name) if current_aoi_name else None
        session.current_aoi_name = normalized_aoi
        session.last_turn_timestamp = timestamp
        response_type_result = self._classify_response_type(
            metadata=metadata, session=session, user_text=user_text
        )
        response_type = response_type_result.label
        # Classifier boundary (HANDOFF "Label contract"): map labels outside the
        # 8-label contract explicitly (repeat_request -> confusion), validate the
        # rest. The raw label keeps flowing to the logs; only the contract label
        # reaches the policy's observation.
        state_response_type, response_type_valid, response_type_validation_error = (
            to_contract_label(response_type)
        )
        if not response_type_valid:
            response_type_logger.error(
                "response type %r failed contract validation (session=%s): %s -- "
                "fell back to 'statement'",
                response_type, session.session_id, response_type_validation_error,
            )
        # Disengagement is recomputed from the label every turn (no latch);
        # recovery itself happens inside the masks, with the policy still running.
        visitor_disengaged = self._resolve_visitor_disengaged(session, state_response_type)
        forced_option = None
        forced_subaction = None
        action_selection_source = "rl_policy"
        if is_silence_event:
            silence_action = self._select_silence_action(session, current_exhibit)
            forced_option = silence_action.get("option")
            forced_subaction = silence_action.get("subaction")
            action_selection_source = "silence_rule_based"
        turn_number_next = session.runtime.turn_number + 1
        turn_id = str(metadata.get("turn_id") or f"{session.session_id}-T{turn_number_next}")
        turn_start_ts = metadata.get("turn_start_ts") or timestamp
        user_asr_end_ts = metadata.get("user_asr_end_ts") or timestamp
        agent_send_ts_meta = metadata.get("agent_send_ts")
        agent_tts_start_ts = metadata.get("agent_tts_start_ts")
        agent_tts_end_ts = metadata.get("agent_tts_end_ts")

        result = session.runtime.generate_turn(
            user_message=user_text,
            exhibit=current_exhibit,
            dialogue_history=session.dialogue_history,
            current_aoi=normalized_aoi,
            conversation_history_rows=session.conversation_history_rows,
            response_type=response_type,
            state_response_type=state_response_type,
            forced_option=forced_option,
            forced_subaction=forced_subaction,
            visitor_disengaged=visitor_disengaged,
            is_silence=is_silence_event,
        )
        # Mask rule 7 in action: the legal set collapsed to ["Engage"] and the
        # policy's argmax executed the recovery. Tag it so the study data still
        # distinguishes masked-recovery turns from free policy turns.
        if (
            action_selection_source == "rl_policy"
            and visitor_disengaged
            and result.get("option") == "Engage"
        ):
            action_selection_source = "rl_policy_recover_masked"
        raw_reply_text = result["response"]
        draft_response = result.get("draft_response")
        revised_response = result.get("revised_response")
        revised_once = int(result.get("revised_once", 0) or 0)
        final_response_source = str(result.get("final_response_source", "draft"))
        user_facing_reply_text = self._clean_user_facing_reply(raw_reply_text)
        turn_number = session.runtime.turn_number
        agent_send_ts = utc_now_iso()
        if is_silence_event:
            session.session_silence_count += 1
            session.silence_fired_since_last_user_turn = True
            exhibit_key = session.current_exhibit or current_exhibit or ""
            if exhibit_key:
                session.exhibit_silence_count[exhibit_key] = session.exhibit_silence_count.get(exhibit_key, 0) + 1
        elif user_text.strip():
            session.has_real_user_turn = True
            session.silence_fired_since_last_user_turn = False
        session.dialogue_history.append(("user", user_text, turn_number - 1))
        # dialogue_planner labels only "agent" as the guide side; using "assistant"
        # causes prior guide utterances to be misread as visitor turns in prompt context.
        session.dialogue_history.append(("agent", user_facing_reply_text, turn_number - 1))
        session.conversation_history_rows.append(
            {
                "Time": user_asr_end_ts or turn_start_ts or timestamp,
                "Speaker": "User",
                # The generation prompt reads these rows, so say WHY the visitor was
                # quiet: walking up to a new painting is not the same as going silent.
                "Text": (
                    user_text if user_text
                    else ("[moved to a new exhibit]" if trigger_source == "focus_change" else "[silence]")
                ),
            }
        )
        session.conversation_history_rows.append(
            {
                "Time": agent_send_ts_meta or agent_send_ts,
                "Speaker": "Agent",
                "Text": user_facing_reply_text,
            }
        )
        session.current_exhibit = result.get("mapped_exhibit") or current_exhibit
        # Persist the full "option/subaction" action so silence handling can
        # recover the previous coarse option on the next turn.
        session.last_action = result.get("action") or result.get("subaction")
        session.last_agent_reply = user_facing_reply_text

        snapshot = session.runtime.get_state_snapshot()
        interaction = InteractionRecord(
            timestamp=timestamp,
            session_id=session.session_id,
            turn_id=turn_id,
            source="RL",
            user_text=user_text,
            reply_text=user_facing_reply_text,
            action_label=result.get("action"),
            current_object_name=session.current_object_name or current_object_name,
            current_aoi_name=normalized_aoi,
            referenced_object=session.current_object_name or current_object_name,
            referenced_aoi=normalized_aoi,
            turn_number=turn_number,
            turn_start_ts=turn_start_ts,
            user_asr_end_ts=user_asr_end_ts,
            agent_send_ts=agent_send_ts_meta or agent_send_ts,
            agent_tts_start_ts=agent_tts_start_ts,
            agent_tts_end_ts=agent_tts_end_ts,
            mapped_exhibit=result.get("mapped_exhibit"),
            action=result.get("action"),
            option=result.get("option"),
            subaction=result.get("subaction"),
            trigger_source=trigger_source,
            action_selection_source=action_selection_source,
            response_type=response_type,
            target_exhibit=result.get("target_exhibit"),
            option_count_snapshot=snapshot["option_counts"],
            facts_mentioned_snapshot=snapshot["facts_mentioned"],
            coverage_snapshot=snapshot["coverage"],
            debug={
                "input_exhibit": result.get("input_exhibit"),
                "metadata": metadata,
                "raw_reply_text": raw_reply_text,
                "explain_newfact_meta": result.get("explain_newfact_meta", {}),
                "repeatfact_meta": result.get("repeatfact_meta", {}),
                "transition_meta": result.get("transition_meta", {}),
                "is_silence_event": is_silence_event,
                "session_silence_count": session.session_silence_count,
                "silence_fired_since_last_user_turn": session.silence_fired_since_last_user_turn,
                "exhibit_silence_count": dict(session.exhibit_silence_count),
                "turn_latency_ms": round((time.monotonic() - turn_started_at) * 1000.0, 1),
                "response_type_classifier_name": self.response_type_classifier_name,
                "response_type_source": response_type_result.source,
                "response_type_latency_ms": round(response_type_result.latency_ms, 1),
                "response_type_ok": response_type_result.ok,
                "response_type_error": response_type_result.error,
                "visitor_disengaged": visitor_disengaged,
                "available_options": result.get("available_options"),
                "action_resolved_from": result.get("resolved_from"),
                "recover_masked": action_selection_source == "rl_policy_recover_masked",
                "forced_recover_count": session.forced_recover_count,
                # The 31-d observation the policy saw this turn -- must change
                # every turn (HANDOFF's frozen-state failure mode is the #1
                # integration risk; this makes it auditable per session).
                "obs_31": result.get("obs_31"),
                # On silence-forced turns: what the policy would have chosen.
                "policy_action": result.get("policy_action"),
                # The old lexical label on every speech turn, so the two
                # classifiers can be compared offline at no extra cost.
                "response_type_rules_v1": response_type_result.rules_v1_label,
                # The label that entered the obs[21:29] one-hot. Differs from
                # response_type only when the boundary mapped it
                # (repeat_request -> confusion) or rejected it (-> statement).
                "state_response_type": result.get("state_response_type"),
                "response_type_validation_ok": response_type_valid,
                "response_type_validation_error": response_type_validation_error,
                "off_exhibit_seconds": self._parse_float(metadata.get("off_exhibit_seconds"), 0.0),
            },
        )
        log_path = self.logger.append_interaction(session.session_id, interaction.dict())

        judge_result = result.get("judge_result")
        judge_log_path = None
        if isinstance(judge_result, dict) and judge_result:
            judge_payload = {
                "timestamp": timestamp,
                "session_id": session.session_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
                "option": result.get("option"),
                "subaction": result.get("subaction"),
                "selected_fact_ids": result.get("selected_fact_ids", []),
                "decision": judge_result.get("decision"),
                "action_alignment": judge_result.get("action_alignment"),
                "language_consistency": judge_result.get("language_consistency"),
                "gaze_grounding": judge_result.get("gaze_grounding"),
                "realized_fact_ids": judge_result.get("realized_fact_ids", []),
                "reason": judge_result.get("reason"),
                "revision_instruction": judge_result.get("revision_instruction"),
                "judge_parse_ok": result.get("judge_parse_ok"),
                "judge_error": result.get("judge_error"),
            }
            judge_log_path = self.logger.append_judge(session.session_id, judge_payload)

        trace_payload = {
            "timestamp": timestamp,
            "session_id": session.session_id,
            "turn_id": turn_id,
            "turn_number": turn_number,
            "option": result.get("option"),
            "subaction": result.get("subaction"),
            "selected_fact_ids": result.get("selected_fact_ids", []),
            "draft_response": draft_response,
            "revised_response": revised_response,
            "final_response": raw_reply_text,
            "revised_once": revised_once,
            "final_response_source": final_response_source,
            "realized_fact_ids": (judge_result or {}).get("realized_fact_ids", []),
            "judge_parse_ok": result.get("judge_parse_ok"),
            "judge_error": result.get("judge_error"),
        }
        generation_trace_log_path = self.logger.append_generation_trace(session.session_id, trace_payload)
        self.tts.speak(user_facing_reply_text, session_id=session.session_id, turn_id=turn_id)

        return TurnResponse(
            session_id=session.session_id,
            timestamp=timestamp,
            reply_text=user_facing_reply_text,
            action=result.get("action"),
            option=result.get("option"),
            subaction=result.get("subaction"),
            target_exhibit=result.get("target_exhibit"),
            mapped_exhibit=result.get("mapped_exhibit"),
            current_exhibit=session.current_exhibit,
            debug={
                "log_path": str(log_path),
                "judge_log_path": str(judge_log_path) if judge_log_path else None,
                "generation_trace_log_path": str(generation_trace_log_path),
                "coverage_snapshot": snapshot["coverage"],
                "response_type": response_type,
                "response_type_source": response_type_result.source,
                "response_type_rules_v1": response_type_result.rules_v1_label,
                "trigger_source": trigger_source,
                "action_selection_source": action_selection_source,
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

