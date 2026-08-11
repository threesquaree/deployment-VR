from openai import OpenAI
from dotenv import load_dotenv
from typing import Any, Optional, Text, Dict, List, Tuple
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

import os, csv, random, json
import sys
from time import perf_counter
from datetime import datetime, timezone
from pathlib import Path
from baseline_silent_prompt import build_fallback_silent_trigger_prompt, build_silent_trigger_prompt
from local_runtime.knowledge_base import KnowledgeBase
from local_runtime.session_store import SessionStore
from local_runtime.conversation_logger import ConversationLogger

# ===== std libs for TTS/helpers =====
import time, threading, hashlib, traceback, subprocess
import pyttsx3

# ===== Piper TTS (natural voice, shared with the RL agent) =====
# The shared helper + tts_config.json live in Research\Research\tts so BOTH
# study conditions speak with an identical voice (frozen for the study).
# pyttsx3 remains as automatic fallback if Piper is unavailable.
_PIPER_TTS_DIR = str(Path(__file__).resolve().parents[2] / "tts")
try:
    if _PIPER_TTS_DIR not in sys.path:
        sys.path.insert(0, _PIPER_TTS_DIR)
    import piper_tts as _piper_tts
    _piper_tts.prewarm()  # avoid first-utterance cold start tripping the fallback
except Exception:
    _piper_tts = None

# ===== Logging (visible in `rasa run actions`) =====
import logging
logging.basicConfig(
    level=logging.INFO,  # flip to DEBUG for more detail
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger("actions")

# ===== Debug Logger =====
DEBUG_LOG_FILE = "C:\\Users\\s3533204\\Downloads\\Research\\Research\\debug_logs\\rasa_debug.log"
Path(DEBUG_LOG_FILE).parent.mkdir(exist_ok=True)

def log_debug(component: str, event: str, data: str = ""):
    """记录debug日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] [{component}] {event} | {data}"
    try:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        logger.error(f"Failed to write debug log: {e}")
    logger.info(f"[DEBUG] {log_entry}")

# ===== OpenAI / runtime init =====
load_dotenv(override=True)
API_KEY = os.getenv('api_key')
# If a 'base_url' env var is set (e.g. https://openrouter.ai/api/v1) route the
# LLM through that OpenAI-compatible endpoint; otherwise use OpenAI directly.
# Mirrors the RL runtime's openai_generator so both study conditions can share
# the same provider (currently OpenRouter, openai/gpt-5.4).
_BASE_URL = os.getenv('base_url') or os.getenv('OPENAI_BASE_URL')
if _BASE_URL:
    client = OpenAI(api_key=API_KEY, base_url=_BASE_URL)
else:
    client = OpenAI(api_key=API_KEY)
KNOWLEDGE_BASE = KnowledgeBase()
SESSION_STORE = SessionStore()
CONVERSATION_LOGGER = ConversationLogger()
POLICY_MODE_ALLOWED = {"baseline", "rl"}
RL_PROJECT_ROOT = Path(os.getenv("RL_PROJECT_ROOT", r"C:\Users\Vrmuseum\Desktop\Research\RL"))
RL_CHECKPOINT_PATH = RL_PROJECT_ROOT / "H3_MDP_StateMachine.pt"
RL_KG_PATH = Path(
    os.getenv("RL_KG_PATH", str(RL_PROJECT_ROOT / "KG" / "museum_knowledge_graph.json"))
)
RL_LLM_MODEL = os.getenv("RL_LLM_MODEL", "gpt-5.4")
_RL_RUNTIME = None


def _resolve_policy_mode(tracker: Tracker = None) -> str:
    slot_mode = None
    if tracker is not None:
        try:
            slot_mode = tracker.get_slot("policy_mode")
        except Exception:
            slot_mode = None

    mode = str(slot_mode or os.getenv("POLICY_MODE", "rl")).strip().lower()
    if mode not in POLICY_MODE_ALLOWED:
        logger.warning("Invalid POLICY_MODE=%s, fallback to baseline", mode)
        return "baseline"
    return mode


def _agent_mode_label(policy_mode: str) -> str:
    return "Improved" if policy_mode == "rl" else "Baseline"


def _get_rl_runtime():
    global _RL_RUNTIME
    if _RL_RUNTIME is not None:
        return _RL_RUNTIME

    if not RL_PROJECT_ROOT.exists():
        raise FileNotFoundError(f"RL project root not found: {RL_PROJECT_ROOT}")
    if not RL_CHECKPOINT_PATH.exists():
        raise FileNotFoundError(f"RL checkpoint not found: {RL_CHECKPOINT_PATH}")
    if not RL_KG_PATH.exists():
        raise FileNotFoundError(f"RL knowledge graph not found: {RL_KG_PATH}")

    if str(RL_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(RL_PROJECT_ROOT))

    from inference.rl_runtime import RLMuseumRuntime

    _RL_RUNTIME = RLMuseumRuntime(
        checkpoint_path=str(RL_CHECKPOINT_PATH),
        knowledge_graph_path=str(RL_KG_PATH),
        device="cpu",
        model_name=RL_LLM_MODEL,
    )
    logger.info(
        "[RL] Runtime initialized checkpoint=%s kg=%s model=%s",
        RL_CHECKPOINT_PATH,
        RL_KG_PATH,
        RL_LLM_MODEL,
    )
    return _RL_RUNTIME


def _kb_graph_snapshot() -> Dict[str, Any]:
    return KNOWLEDGE_BASE.get_graph_data()
log_debug("RASA", "系统初始化", "RASA服务已启动，本地 runtime 已建立")


# =============================================================================
#                              TTS + TRACE HELPERS
# =============================================================================

def _pyttsx3_speak_once(text: str, rate: int = 150, volume: float = 0.9) -> None:
    """Create a fresh engine, speak once, then dispose (Windows SAPI5)."""
    eng = pyttsx3.init(driverName='sapi5')
    eng.setProperty('rate', rate)
    eng.setProperty('volume', volume)
    eng.say(text)
    eng.runAndWait()
    try:
        eng.stop()
    except Exception:
        pass
    del eng

def _powershell_say(text: str, rate: int = 0, volume: int = 90):
    """
    Fallback to System.Speech via PowerShell.
    Text is piped via STDIN to avoid quoting issues.
    """
    ps = (
        "[void][Reflection.Assembly]::LoadWithPartialName('System.Speech');"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {rate};"
        f"$s.Volume = {volume};"
        "$in = [Console]::In.ReadToEnd();"
        "$s.Speak($in);"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            input=text.encode("utf-8"),
            timeout=20
        )
    except Exception as e:
        logger.error("[TTS][PS] ERROR: %s\n%s", e, traceback.format_exc())

# NOTE: the legacy (shadowed) speak()/tts_from() definitions that used to live
# here were removed — only the timestamp-returning versions further below are
# live. Python's last-definition-wins had already made the old pair dead code.

# ---- Turn + global TTS dedupe ----
def _new_turn_id() -> str:
    return f"T{int(time.time()*1000)}-{random.randint(100,999)}"

_LAST_TTS_AT = 0.0
_LAST_TTS_HASH = None
_LAST_USER_TURN_AT = 0.0
_CA_TURN_LOG_LOCK = threading.Lock()

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def mark_user_turn():
    """Mark that a user turn just happened (used to suppress proactive guide TTS)."""
    global _LAST_USER_TURN_AT
    _LAST_USER_TURN_AT = time.time()

def can_proactively_tts(min_gap_sec: float = 10.0) -> bool:
    """Allow guide speech only if no user turn in the last N seconds."""
    return (time.time() - _LAST_USER_TURN_AT) >= min_gap_sec

def _empty_tts_result(reason: str = "") -> Dict[str, Any]:
    return {
        "started_at": None,
        "ended_at": None,
        "completed": False,
        "skipped": bool(reason),
        "skip_reason": reason or None,
        "method": None,
        "timed_out": False,
    }


def speak(text: str, timeout_sec: float = 10.0, on_complete=None) -> Dict[str, Any]:
    """Speak once and return the observed playback timestamps when available."""
    if not text or not text.strip():
        logger.info("[TTS] skipped empty text")
        return _empty_tts_result("empty_text")

    snippet = (text[:120] + "...") if len(text) > 120 else text
    logger.info("[TTS] START len=%d text='%s'", len(text), snippet)

    err_holder = {"exc": None}
    timing = {
        "started_at": None,
        "ended_at": None,
        "completed": False,
        "skipped": False,
        "skip_reason": None,
        "method": "pyttsx3",
        "timed_out": False,
    }

    def _worker():
        try:
            spoke_via_piper = False
            if _piper_tts is not None:
                try:
                    wav_path = _piper_tts.synthesize(text)
                    timing["method"] = "piper"
                    # started_at means "audio began": stamp at playback start,
                    # AFTER synthesis completed (piper adds ~0.5s synth time).
                    timing["started_at"] = _iso_now_ms()
                    try:
                        _piper_tts.play(wav_path)
                    finally:
                        try:
                            os.remove(wav_path)
                        except Exception:
                            pass
                    spoke_via_piper = True
                except Exception:
                    logger.warning("[TTS] piper failed; falling back to pyttsx3\n%s", traceback.format_exc())
                    timing["method"] = "pyttsx3"
            if not spoke_via_piper:
                timing["started_at"] = _iso_now_ms()
                _pyttsx3_speak_once(text)
            timing["completed"] = True
        except Exception as e:
            err_holder["exc"] = e
        finally:
            if timing["started_at"] is not None:
                timing["ended_at"] = _iso_now_ms()
            if callable(on_complete):
                try:
                    on_complete(dict(timing))
                except Exception:
                    logger.error("[TTS] on_complete callback failed\n%s", traceback.format_exc())

    t = threading.Thread(target=_worker, name="TTSOneShot", daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        logger.warning("[TTS] pyttsx3 still speaking after %.1fs â€” skipping fallback", timeout_sec)
        timing["timed_out"] = True
    elif err_holder["exc"] is not None:
        logger.error("[TTS] pyttsx3 ERROR: %s\n%s", err_holder["exc"], traceback.format_exc())
        timing["method"] = "powershell"
        timing["started_at"] = _iso_now_ms()
        _powershell_say(text)
        timing["ended_at"] = _iso_now_ms()
        timing["completed"] = True
    else:
        logger.info("[TTS] DONE")
    return timing


def tts_from(source: str, text: str, window_sec: float = 12.0, turn_id: str = "?", on_complete=None) -> Dict[str, Any]:
    """
    Speak once, globally debounced across ALL actions and sources.
    - source: 'providing_response' | 'interactive_guide'
    - window_sec: skip if we already spoke the exact same text recently
    """
    global _LAST_TTS_AT, _LAST_TTS_HASH
    if not text or not text.strip():
        logger.info("[TTS][%s][%s] skipped empty", source, turn_id)
        return _empty_tts_result("empty_text")

    now = time.time()
    h = _hash_text(text)

    if _LAST_TTS_HASH == h and (now - _LAST_TTS_AT) < window_sec:
        logger.info("[TTS][%s][%s] SKIP duplicate within %.1fs", source, turn_id, window_sec)
        return _empty_tts_result("duplicate_text")

    _LAST_TTS_HASH, _LAST_TTS_AT = h, now
    logger.info("[TTS][%s][%s] SPEAK len=%d", source, turn_id, len(text))
    return speak(text, on_complete=on_complete)


# =============================================================================
#                             Utility: CSV logging
# =============================================================================

def log_conversation(csv_filename, actor, response, aoiname, objectname):
    # Deprecated: use unified JSONL turn log instead.
    return


UNIFIED_TURN_LOG_DIR = Path(r"C:\Users\s3533204\Downloads\Research\Research\data\sessions\baseline")
UNIFIED_TURN_LOG_DIR.mkdir(parents=True, exist_ok=True)
_CA_SESSION_DIRS: Dict[str, Path] = {}


def _iso_now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_utc_tag(raw_ts: Any) -> str:
    if raw_ts is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    candidate = str(raw_ts).strip()
    if not candidate:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    candidate = candidate.replace(" ", "T").replace(":", "-").replace("+00:00", "Z").replace(".", "-")
    return candidate


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _latest_metadata(tracker: Tracker) -> Dict[str, Any]:
    try:
        return (tracker.latest_message or {}).get("metadata") or {}
    except Exception:
        return {}


def _resolve_session_context(tracker: Tracker) -> Tuple[str, str, str]:
    metadata = _latest_metadata(tracker)
    latest_message = tracker.latest_message or {}
    participant_id = _first_nonempty(
        metadata.get("participant_id"),
        metadata.get("participantId"),
        metadata.get("actorID"),
        tracker.get_slot("actorID"),
    )
    session_id = _first_nonempty(
        metadata.get("session_id"),
        metadata.get("sessionId"),
        metadata.get("agentID"),
        tracker.get_slot("agentID"),
    )
    session_folder_name = _first_nonempty(
        metadata.get("session_folder_name"),
        metadata.get("sessionFolderName"),
    )
    if not participant_id and latest_message.get("text") and latest_message.get("intent", {}).get("name") == "sending_actor_id":
        participant_id = str(latest_message.get("text")).strip()
    return participant_id, session_id, session_folder_name


def _find_existing_ca_session_dir(session_id: str) -> Optional[Path]:
    candidates = sorted(
        UNIFIED_TURN_LOG_DIR.glob(f"ca_{session_id}_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _get_ca_session_dir(session_id: Any, turn_start_ts: Any, session_folder_name: Any = None) -> Path:
    key = str(session_id).strip() or "unknown"
    cached = _CA_SESSION_DIRS.get(key)
    if cached and cached.exists():
        return cached
    preferred = str(session_folder_name or "").strip()
    if preferred:
        preferred_dir = UNIFIED_TURN_LOG_DIR / preferred
        preferred_dir.mkdir(parents=True, exist_ok=True)
        _CA_SESSION_DIRS[key] = preferred_dir
        return preferred_dir
    existing = _find_existing_ca_session_dir(key)
    if existing is not None:
        _CA_SESSION_DIRS[key] = existing
        return existing
    utc_tag = _safe_utc_tag(turn_start_ts)
    session_dir = UNIFIED_TURN_LOG_DIR / f"ca_{key}_{utc_tag}"
    session_dir.mkdir(parents=True, exist_ok=True)
    _CA_SESSION_DIRS[key] = session_dir
    return session_dir


def _write_ca_session_meta(session_dir: Path, session_id: Any, participant_id: Any) -> None:
    meta_path = session_dir / "meta.json"
    if meta_path.exists():
        return
    meta = {
        "source": "ca",
        "session_id": str(session_id),
        "started_at_utc": _iso_now_ms(),
        "participant_id": str(participant_id or session_id),
        "actor_id": str(participant_id or session_id),
        "schema_version": "sessions_v1",
    }
    with meta_path.open("w", encoding="utf-8") as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)


def _ensure_ca_session_artifacts(
    session_id: Any,
    participant_id: Any,
    turn_start_ts: Any,
    session_folder_name: Any = None,
) -> Path:
    session_dir = _get_ca_session_dir(session_id, turn_start_ts, session_folder_name=session_folder_name)
    _write_ca_session_meta(session_dir, session_id, participant_id)
    turns_path = session_dir / "turns.jsonl"
    if not turns_path.exists():
        bootstrap = {
            "timestamp": _iso_now_ms(),
            "session_id": str(session_id),
            "participant_id": str(participant_id or session_id),
            "source": "CA",
            "record_type": "session_start",
            "turn_start_ts": turn_start_ts,
        }
        with turns_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bootstrap, ensure_ascii=False) + "\n")
    return session_dir


def _update_ca_turn_tts(
    session_id: Any,
    turn_id: str,
    agent_tts_start_ts: Any = None,
    agent_tts_end_ts: Any = None,
    session_folder_name: Any = None,
    retries: int = 20,
    retry_sleep_sec: float = 0.1,
) -> bool:
    if not session_id or not turn_id:
        return False
    session_dir = _get_ca_session_dir(session_id, _iso_now_ms(), session_folder_name=session_folder_name)
    turns_path = session_dir / "turns.jsonl"
    if not turns_path.exists():
        return False

    for attempt in range(retries):
        updated = False
        changed = False
        with _CA_TURN_LOG_LOCK:
            lines = []
            try:
                with turns_path.open("r", encoding="utf-8") as handle:
                    for raw in handle:
                        line = raw.rstrip("\n")
                        if not line:
                            continue
                        record = json.loads(line)
                        if record.get("record_type") == "interaction" and record.get("turn_id") == turn_id:
                            if agent_tts_start_ts and not record.get("agent_tts_start_ts"):
                                record["agent_tts_start_ts"] = agent_tts_start_ts
                                changed = True
                            if agent_tts_end_ts and record.get("agent_tts_end_ts") != agent_tts_end_ts:
                                record["agent_tts_end_ts"] = agent_tts_end_ts
                                changed = True
                            updated = True
                        lines.append(json.dumps(record, ensure_ascii=False))
                if updated and changed:
                    with turns_path.open("w", encoding="utf-8") as handle:
                        handle.write("\n".join(lines) + ("\n" if lines else ""))
                    return True
                if updated:
                    return True
            except Exception:
                logger.error("[TURN-LOG] Failed updating CA turn TTS\n%s", traceback.format_exc())
                return False
        if attempt < (retries - 1):
            time.sleep(retry_sleep_sec)
    return False


def _coerce_rasa_timestamp(ts_value: Any) -> Any:
    if ts_value is None:
        return None
    try:
        ts = float(ts_value)
        return datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
    except Exception:
        return str(ts_value)


def _resolve_user_asr_end_ts(tracker: Tracker) -> Any:
    metadata = _latest_metadata(tracker)
    return _coerce_rasa_timestamp(
        _first_nonempty(
            metadata.get("user_asr_end_ts"),
            metadata.get("userAsrEndTs"),
            (tracker.latest_message or {}).get("timestamp"),
        )
    )


def _next_ca_turn_identity(session_id: Any, turn_start_ts: Any, session_folder_name: Any = None) -> Tuple[str, int]:
    key = str(session_id or "").strip()
    if not key:
        return _new_turn_id(), 1

    session_dir = _ensure_ca_session_artifacts(
        session_id=key,
        participant_id=key,
        turn_start_ts=turn_start_ts,
        session_folder_name=session_folder_name,
    )
    turns_path = session_dir / "turns.jsonl"

    with _CA_TURN_LOG_LOCK:
        interaction_count = 0
        if turns_path.exists():
            with turns_path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if record.get("record_type") == "interaction":
                        interaction_count += 1
        turn_number = interaction_count + 1
        return f"{key}-T{turn_number}", turn_number


def log_unified_turn(
    session_id: Any,
    participant_id: Any,
    turn_id: str,
    turn_number: int,
    agent_mode: str,
    turn_start_ts: Any,
    user_asr_end_ts: Any,
    agent_send_ts: Any,
    agent_tts_start_ts: Any,
    agent_tts_end_ts: Any,
    user_text: str,
    agent_text: str,
    current_object_name: Any,
    current_aoi_name: Any,
    referenced_object: Any,
    referenced_aoi: Any,
    trigger_source: str,
    action: str,
    session_folder_name: Any = None,
    source: str = "CA",
):
    payload = {
        "timestamp": _iso_now_ms(),
        "session_id": str(session_id),
        "turn_id": turn_id,
        "turn_number": turn_number,
        "agent_mode": agent_mode,
        "source": source,
        "record_type": "interaction",
        "turn_start_ts": turn_start_ts,
        "user_asr_end_ts": user_asr_end_ts,
        "agent_send_ts": agent_send_ts,
        "agent_tts_start_ts": agent_tts_start_ts,
        "agent_tts_end_ts": agent_tts_end_ts,
        "user_text": user_text,
        "reply_text": agent_text,
        "current_object_name": current_object_name,
        "current_aoi_name": current_aoi_name,
        "referenced_object": referenced_object,
        "referenced_aoi": referenced_aoi,
        "trigger_source": trigger_source,
        "action": action,
    }
    session_dir = _ensure_ca_session_artifacts(
        session_id=session_id,
        participant_id=participant_id,
        turn_start_ts=turn_start_ts,
        session_folder_name=session_folder_name,
    )
    path = session_dir / "turns.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _log_conversation_turn(session_id: Any, source_actor: Any, target_actor: Any, text: Any) -> None:
    key = str(session_id or "").strip()
    session_dir = _get_ca_session_dir(key, _iso_now_ms()) if key and key != "unknown" else None
    CONVERSATION_LOGGER.log_turn(
        session_id=key or "unknown",
        source_actor=source_actor,
        target_actor=target_actor,
        text=str(text or ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_dir=session_dir,
    )


def _make_ca_tts_update_callback(session_id: Any, turn_id: str, session_folder_name: Any = None):
    def _callback(timing: Dict[str, Any]) -> None:
        _update_ca_turn_tts(
            session_id=session_id,
            turn_id=turn_id,
            agent_tts_start_ts=timing.get("started_at"),
            agent_tts_end_ts=timing.get("ended_at"),
            session_folder_name=session_folder_name,
        )
    return _callback


# =============================================================================
#                                 Actions
# =============================================================================

class ActionGetActorID(Action):
    def name(self) -> Text:
        return "action_get_actor_id"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        action_start = perf_counter()
        metadata = _latest_metadata(tracker)
        user_input = tracker.latest_message.get('text', '')
        participant_id = _first_nonempty(
            metadata.get("participant_id"),
            metadata.get("participantId"),
            user_input,
        )
        logger.info("[GET_ACTOR] input=%s", participant_id)
        log_debug("RASA", "ActionGetActorID start", f"user_input={participant_id}")

        session_start = perf_counter()
        session_started_at = _iso_now_ms()
        requested_session_id = _first_nonempty(
            metadata.get("session_id"),
            metadata.get("sessionId"),
        )
        session_folder_name = _first_nonempty(
            metadata.get("session_folder_name"),
            metadata.get("sessionFolderName"),
        )
        if requested_session_id:
            session_id = requested_session_id
            SESSION_STORE.ensure_session(
                session_id=session_id,
                participant_id=participant_id,
                started_at=session_started_at,
            )
        else:
            session_id = SESSION_STORE.start_session(
                participant_id=participant_id,
                started_at=session_started_at,
            )
        _ensure_ca_session_artifacts(
            session_id=session_id,
            participant_id=participant_id,
            turn_start_ts=session_started_at,
            session_folder_name=session_folder_name,
        )
        session_ms = (perf_counter() - session_start) * 1000.0
        response_text = f"Participant ID: {participant_id}, Session ID: {session_id}"

        logger.info("[GET_ACTOR] Participant ID: %s, Session ID: %s", participant_id, session_id)
        log_debug("RASA", "ActionGetActorID session created", f"participant_id={participant_id}, session_id={session_id}, session_ms={session_ms:.2f}")
        dispatcher.utter_message(text=response_text)
        total_ms = (perf_counter() - action_start) * 1000.0
        log_debug("RASA", "ActionGetActorID completed", f"participant_id={participant_id}, session_id={session_id}, response_text={response_text}, total_ms={total_ms:.2f}")

        # mark the user turn so proactive agent won't overlap immediately
        mark_user_turn()

        return [SlotSet("actorID", participant_id), SlotSet("agentID", session_id)]


class ActionProvidingResponse(Action):
    def name(self) -> Text:
        return "action_providing_response"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        turn_start_ts = _iso_now_ms()
        user_asr_end_ts = _resolve_user_asr_end_ts(tracker)
        msg_text = (tracker.latest_message or {}).get("text", "")

        participant_id, session_id, session_folder_name = _resolve_session_context(tracker)
        if session_id:
            SESSION_STORE.ensure_session(
                session_id=session_id,
                participant_id=participant_id or session_id,
                started_at=turn_start_ts,
            )
        turn_id, turn_number = _next_ca_turn_identity(
            session_id=session_id or participant_id,
            turn_start_ts=turn_start_ts,
            session_folder_name=session_folder_name,
        )
        logger.info("[ENTER][%s] ActionProvidingResponse text='%s'", turn_id, msg_text)
        log_debug("RASA", "ActionProvidingResponse开始", f"turn_id={turn_id}, msg_text={msg_text}")
        session = SESSION_STORE.get_session(session_id) if session_id else None
        logger.info(
            "[CTX][%s] participant_id=%s session_id=%s session_folder=%s has_session=%s",
            turn_id,
            participant_id,
            session_id,
            session_folder_name,
            bool(session),
        )

        mark_user_turn()
        policy_mode = _resolve_policy_mode(tracker)
        logger.info("[POLICY][%s] mode=%s", turn_id, policy_mode)

        obj_now = self._resolve_current_object(tracker, session_id)
        aoi_name = self._resolve_current_aoi(tracker, session_id)
        if session_id and msg_text:
            SESSION_STORE.append_history(session_id, "user", msg_text, turn_start_ts)

        logger.info("[GATE][%s] current painting (session logic) = %s aoi=%s", turn_id, obj_now, aoi_name)

        # ===============================================================
        # ======================= ON-PAINTING BRANCH =====================
        # ===============================================================
        if obj_now:
            logger.info("[DEBUG][%s] ENTERING ON-PAINTING BRANCH for %s", turn_id, obj_now)

            if msg_text == 'Repeat Question':
                responses = [
                    "Could you please repeat your question so I can assist you better?",
                    "I'm not entirely sure I understand; could you repeat your question?",
                    "Could you repeat your question? I might have missed something.",
                    "I want to make sure I got that right; could you repeat or confirm what you said?"
                ]
                self._log_conversation(participant_id, session_id, msg_text)

                log_conversation(
                    f'logs/conversation_{participant_id}.csv',
                    f'user_{participant_id}', msg_text, aoi_name or "None", obj_now
                )

                random_response = random.choice(responses)
                agent_send_ts = _iso_now_ms()
                dispatcher.utter_message(random_response)
                logger.info("[SAY][%s] providing_response(REPEAT) -> '%s'", turn_id, random_response)
                tts_result = tts_from(
                    "providing_response",
                    random_response,
                    turn_id=turn_id,
                    on_complete=_make_ca_tts_update_callback(session_id or participant_id, turn_id, session_folder_name),
                )
                agent_tts_start_ts = tts_result.get("started_at")
                agent_tts_end_ts = tts_result.get("ended_at")
                if session_id:
                    SESSION_STORE.append_history(session_id, "agent", random_response, agent_send_ts)

                self._log_conversation(session_id, participant_id, random_response)
                log_conversation(
                    f'logs/conversation_{participant_id}.csv',
                    f'agent_{session_id}', random_response, aoi_name or "None", obj_now
                )
                log_unified_turn(
                    session_id=session_id or participant_id,
                    participant_id=participant_id,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    agent_mode=_agent_mode_label(policy_mode),
                    turn_start_ts=turn_start_ts,
                    user_asr_end_ts=user_asr_end_ts,
                    agent_send_ts=agent_send_ts,
                    agent_tts_start_ts=agent_tts_start_ts,
                    agent_tts_end_ts=agent_tts_end_ts,
                    user_text=msg_text,
                    agent_text=random_response,
                    current_object_name=obj_now,
                    current_aoi_name=aoi_name,
                    referenced_object=obj_now,
                    referenced_aoi=aoi_name,
                    trigger_source="user_input",
                    action="repeat",
                    session_folder_name=session_folder_name,
                    source="CA",
                )

            else:
                # Normal user question
                self._log_conversation(participant_id, session_id, msg_text)

                log_conversation(
                    f'logs/conversation_{participant_id}.csv',
                    f'user_{participant_id}', msg_text, aoi_name or "None", obj_now
                )

                if policy_mode == "rl":
                    try:
                        response = self._get_rl_response(session_id, msg_text, obj_now, turn_id, aoi_name)
                    except Exception as e:
                        logger.error("[RL][%s] runtime failed: %s", turn_id, e, exc_info=True)
                        response = "RL mode is enabled, but response generation failed for this turn."
                else:
                    system_role = self._get_system_role(session_id, msg_text, obj_now, aoi_name)
                    response = self.get_chatgpt_response(system_role, msg_text)

                agent_send_ts = _iso_now_ms()
                dispatcher.utter_message(response)
                logger.info("[SAY][%s] providing_response -> '%s'", turn_id, response)
                tts_result = tts_from(
                    "providing_response",
                    response,
                    turn_id=turn_id,
                    on_complete=_make_ca_tts_update_callback(session_id or participant_id, turn_id, session_folder_name),
                )
                agent_tts_start_ts = tts_result.get("started_at")
                agent_tts_end_ts = tts_result.get("ended_at")
                if session_id:
                    SESSION_STORE.append_history(session_id, "agent", response, agent_send_ts)

                self._remember_agent_reply(session_id, response)
                self._log_conversation(session_id, participant_id, response)
                log_conversation(
                    f'logs/conversation_{participant_id}.csv',
                    f'agent_{session_id}', response, aoi_name or "None", obj_now
                )
                log_unified_turn(
                    session_id=session_id or participant_id,
                    participant_id=participant_id,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    agent_mode=_agent_mode_label(policy_mode),
                    turn_start_ts=turn_start_ts,
                    user_asr_end_ts=user_asr_end_ts,
                    agent_send_ts=agent_send_ts,
                    agent_tts_start_ts=agent_tts_start_ts,
                    agent_tts_end_ts=agent_tts_end_ts,
                    user_text=msg_text,
                    agent_text=response,
                    current_object_name=obj_now,
                    current_aoi_name=aoi_name,
                    referenced_object=obj_now,
                    referenced_aoi=aoi_name,
                    trigger_source="user_input",
                    action="normal",
                    session_folder_name=session_folder_name,
                    source="CA",
                )

            return [SlotSet("actorID", participant_id), SlotSet("agentID", session_id)]

        # ===============================================================
        # ====================== FALLBACK BRANCH ========================
        # ===============================================================
        logger.warning("[FALLBACK][%s] Triggering fallback — no painting found!", turn_id)
        logger.warning("[FALLBACK-DEBUG][%s] Session snapshot: obj=%s | aoi=%s",
                       turn_id, obj_now, aoi_name)

        if msg_text == 'Repeat Question':
            responses = [
                "Could you please repeat your question so I can assist you better?",
                "I'm not entirely sure I understand; could you repeat your question?",
                "Could you repeat your question? I might have missed something.",
                "I want to make sure I got that right; could you repeat or confirm what you said?"
            ]
            self._log_conversation(participant_id, session_id, msg_text)
            log_conversation(
                f'logs/conversation_{participant_id}.csv',
                f'user_{participant_id}', msg_text, 'None', 'None'
            )

            random_response = random.choice(responses)
            agent_send_ts = _iso_now_ms()
            dispatcher.utter_message(random_response)
            logger.info("[SAY][%s] providing_response(REPEAT/FALLBACK) -> '%s'", turn_id, random_response)
            tts_result = tts_from(
                "providing_response",
                random_response,
                turn_id=turn_id,
                on_complete=_make_ca_tts_update_callback(session_id or participant_id, turn_id, session_folder_name),
            )
            agent_tts_start_ts = tts_result.get("started_at")
            agent_tts_end_ts = tts_result.get("ended_at")
            if session_id:
                SESSION_STORE.append_history(session_id, "agent", random_response, agent_send_ts)

            self._remember_agent_reply(session_id, random_response)
            self._log_conversation(session_id, participant_id, random_response)
            log_conversation(
                f'logs/conversation_{participant_id}.csv',
                f'agent_{session_id}', random_response, 'None', 'None'
            )
            log_unified_turn(
                session_id=session_id or participant_id,
                participant_id=participant_id,
                turn_id=turn_id,
                turn_number=turn_number,
                agent_mode=_agent_mode_label(policy_mode),
                turn_start_ts=turn_start_ts,
                user_asr_end_ts=user_asr_end_ts,
                agent_send_ts=agent_send_ts,
                agent_tts_start_ts=agent_tts_start_ts,
                agent_tts_end_ts=agent_tts_end_ts,
                user_text=msg_text,
                agent_text=random_response,
                current_object_name=None,
                current_aoi_name=None,
                referenced_object=None,
                referenced_aoi=None,
                trigger_source="user_input",
                action="repeat",
                session_folder_name=session_folder_name,
                source="CA",
            )

        else:
            # General fallback: user not looking at any painting
            self._log_conversation(participant_id, session_id, msg_text)
            log_conversation(
                f'logs/conversation_{participant_id}.csv',
                f'user_{participant_id}', msg_text, 'None', 'None'
            )

            system_role = f"""
            ### System Role
            You are an AI assistant serving as a virtual guide for a VR exhibition featuring five unique paintings.
            The user is not currently viewing any paintings. Invite them to go to the main room and start exploring one.
            Guidelines: No links/emojis; no speculation; max two sentences.
            Exhibit Data: {_kb_graph_snapshot()}
            """
            response = self.get_chatgpt_response(system_role, msg_text)
            agent_send_ts = _iso_now_ms()
            dispatcher.utter_message(response)
            logger.warning("[SAY][%s] providing_response(FALLBACK) -> '%s'", turn_id, response)
            tts_result = tts_from(
                "providing_response",
                response,
                turn_id=turn_id,
                on_complete=_make_ca_tts_update_callback(session_id or participant_id, turn_id, session_folder_name),
            )
            agent_tts_start_ts = tts_result.get("started_at")
            agent_tts_end_ts = tts_result.get("ended_at")
            if session_id:
                SESSION_STORE.append_history(session_id, "agent", response, agent_send_ts)

            self._remember_agent_reply(session_id, response)
            self._log_conversation(session_id, participant_id, response)
            log_conversation(
                f'logs/conversation_{participant_id}.csv',
                f'agent_{session_id}', response, 'None', 'None'
            )
            log_unified_turn(
                session_id=session_id or participant_id,
                participant_id=participant_id,
                turn_id=turn_id,
                turn_number=turn_number,
                agent_mode=_agent_mode_label(policy_mode),
                turn_start_ts=turn_start_ts,
                user_asr_end_ts=user_asr_end_ts,
                agent_send_ts=agent_send_ts,
                agent_tts_start_ts=agent_tts_start_ts,
                agent_tts_end_ts=agent_tts_end_ts,
                user_text=msg_text,
                agent_text=response,
                current_object_name=None,
                current_aoi_name=None,
                referenced_object=None,
                referenced_aoi=None,
                trigger_source="user_input",
                action="fallback",
                session_folder_name=session_folder_name,
                source="CA",
            )

        return [SlotSet("actorID", participant_id), SlotSet("agentID", session_id)]



    # ---- helpers ----
    def _build_rl_dialogue_history(self, session_id: Any) -> List[Tuple[str, str, int]]:
        rows = self._session_history_rows(session_id)
        history: List[Tuple[str, str, int]] = []
        user_turn = 0

        for row in rows:
            speaker = str(row.get("Speaker", "")).strip().lower()
            text = str(row.get("Text", "")).strip()
            if not text:
                continue

            if speaker == "user":
                user_turn += 1
                role = "user"
            elif speaker == "agent":
                role = "agent"
            else:
                continue

            history.append((role, text, user_turn))
        return history

    def _get_rl_response(self, session_id: Any, user_input: str, obj_now: str, turn_id: str, aoi_name: Any = None) -> str:
        runtime = _get_rl_runtime()
        dialogue_history = self._build_rl_dialogue_history(session_id)
        result = runtime.generate_turn(
            user_message=user_input,
            exhibit=obj_now,
            dialogue_history=dialogue_history,
            current_aoi=aoi_name,
            conversation_history_rows=self._session_history_rows(session_id),
        )
        response = (result.get("response") or "").strip()
        if not response:
            raise RuntimeError("RL runtime returned empty response")

        logger.info(
            "[RL][%s] action=%s option=%s subaction=%s exhibit=%s mapped=%s",
            turn_id,
            result.get("action"),
            result.get("option"),
            result.get("subaction"),
            result.get("input_exhibit"),
            result.get("mapped_exhibit"),
        )
        return response

    def _get_system_role(self, session_id, user_input, object_name=None, aoi_name=None) -> str:
        object_context = KNOWLEDGE_BASE.get_object_context(object_name)
        aoi_context = KNOWLEDGE_BASE.get_aoi_context(aoi_name)
        image = KNOWLEDGE_BASE.get_object_image(object_name)
        last_reply = SESSION_STORE.get_last_agent_reply(session_id) if session_id else None
        history_rows = self._session_history_rows(session_id)
        return f"""
[System Role]
You are an AI assistant serving as a virtual museum guide for a VR exhibition of five unique paintings.

[Current Context]
The main room has five paintings across two walls.
Currently, the user is viewing: ({object_context}).
Focus area: {aoi_context}.
Image: {image}.
Prior agent response: {last_reply}.
Conversation history: {history_rows}.

[User Input]
{user_input}

[Response Constraints]
No links or emojis.
No speculation.
Avoid repetition.
Maximum two sentences.
        """

    def _resolve_current_object(self, tracker: Tracker, session_id: str) -> Any:
        metadata = (tracker.latest_message or {}).get("metadata") or {}
        tracker_object = (
            metadata.get("currentObjectName")
            or metadata.get("current_object")
            or metadata.get("objectName")
            or tracker.get_slot("objName")
        )
        normalized = KNOWLEDGE_BASE.normalize_object_name(tracker_object)
        if normalized:
            SESSION_STORE.set_current_object(session_id, normalized)
            return normalized
        if session_id:
            return SESSION_STORE.get_current_object(session_id)
        return None

    def _resolve_current_aoi(self, tracker: Tracker, session_id: str) -> Any:
        metadata = (tracker.latest_message or {}).get("metadata") or {}
        tracker_aoi = (
            metadata.get("currentAoiName")
            or metadata.get("current_aoi")
            or metadata.get("aoiName")
            or tracker.get_slot("aoiName")
        )
        normalized = KNOWLEDGE_BASE.normalize_aoi_name(tracker_aoi)
        if normalized:
            SESSION_STORE.set_current_aoi(session_id, normalized)
            return normalized
        if session_id:
            # Stale-AOI guard: Unity sends an empty AOI when the visitor is on a
            # painting but not fixating a specific region. Only reuse the remembered
            # AOI if it still belongs to the CURRENT exhibit -- otherwise it leaks
            # across paintings (e.g. calling Diego Bemba "Pedro Sunda").
            stored = SESSION_STORE.get_current_aoi(session_id)
            if stored:
                current_exhibit = KNOWLEDGE_BASE.to_exhibit_key(
                    SESSION_STORE.get_current_object(session_id)
                )
                valid_aois = KNOWLEDGE_BASE.exhibit_aoi_mapping.get(current_exhibit, [])
                if stored not in valid_aois:
                    SESSION_STORE.set_current_aoi(session_id, None)
                    return None
            return stored
        return None

    def _session_history_rows(self, session_id: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not session_id:
            return rows
        for turn in SESSION_STORE.get_history(str(session_id)):
            speaker = "User" if turn.speaker.lower() == "user" else "Agent"
            rows.append(
                {
                    "Time": turn.timestamp,
                    "Speaker": speaker,
                    "Text": turn.text,
                }
            )
        return rows

    def _remember_agent_reply(self, session_id: Any, response: str) -> None:
        if not session_id:
            return
        SESSION_STORE.set_last_agent_reply(str(session_id), response)

    def _log_conversation(self, first_actor, second_actor, response):
        try:
            _log_conversation_turn(first_actor or second_actor, first_actor, second_actor, response)
        except Exception as e:
            logger.error("Error logging conversation: %s", str(e))

    def _interactive_agent_prompt_with_session(self, session_id):
        object_name = self._current_object_name(session_id)
        aoi_name = self._current_aoi_name(session_id)
        object_context = KNOWLEDGE_BASE.get_object_context(object_name)
        aoi_context = KNOWLEDGE_BASE.get_aoi_context(aoi_name)
        image = KNOWLEDGE_BASE.get_object_image(object_name)
        history_rows = self._session_history_rows(session_id)
        return f"""
        ### System Role
        You are an AI assistant serving as a virtual museum guide in a VR exhibition featuring five unique paintings.
        The user is currently observing: ({object_context}).
        Focus area: {aoi_context}.
        Image: {image}.
        Conversation history: {history_rows}.
        Provide concise (<=2 sentences) insight encouraging exploration; no links/emojis/speculation.
        """

    def get_chatgpt_response(self, system_role, user_text=None):
        try:
            messages = [{"role": "system", "content": system_role}]
            if user_text:
                messages.append({"role": "user", "content": user_text})

            completion = client.chat.completions.create(
                model=RL_LLM_MODEL,
                messages=messages,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error("Error generating response: %s", str(e))
            return "An error occurred while generating the response."


class interactive_guide_interaction(Action):
    def name(self) -> Text:
        return "action_interactive_guide_interaction"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        turn_start_ts = _iso_now_ms()

        participant_id, session_id, session_folder_name = _resolve_session_context(tracker)
        if session_id:
            SESSION_STORE.ensure_session(
                session_id=session_id,
                participant_id=participant_id or session_id,
                started_at=turn_start_ts,
            )
        turn_id, turn_number = _next_ca_turn_identity(
            session_id=session_id or participant_id,
            turn_start_ts=turn_start_ts,
            session_folder_name=session_folder_name,
        )
        logger.info("[ENTER][%s] interactive_guide_interaction", turn_id)
        logger.info(
            "[CTX][%s] participant_id=%s session_id=%s session_folder=%s",
            turn_id,
            participant_id,
            session_id,
            session_folder_name,
        )

        names = ['A1','A2','A3','B1','B2','B3','B4','B5','C1','C2','C3','C4','C5','C6','D1','D2','D3','D4','D5']

        previous_object = self._current_object_name(session_id)
        current_object = self._resolve_current_object(tracker, session_id)
        current_aoi = self._resolve_current_aoi(tracker, session_id)
        logger.info("[GUIDE][%s] current_object=%s current_aoi=%s", turn_id, current_object, current_aoi)
        referenced_object = current_object if current_object in names else (previous_object if previous_object in names else None)
        diff = self._seconds_since_last_interaction(session_id)

        logger.info("[DIFF][%s] guide diff=%s", turn_id, diff)

        if diff > 40:
            system_role = self.interactive_agent_prompt_with_gaze(
                participant_id,
                session_id,
                current_object=current_object,
                fallback_object=previous_object,
            )
            response = self.get_chatgpt_response(system_role)

            self._remember_agent_reply(session_id, response)
            if session_id:
                SESSION_STORE.append_history(session_id, "agent", response, _iso_now_ms())
            self._log_conversation(session_id, participant_id, response)
            log_conversation(
                f'logs/conversation_{participant_id}.csv',
                f'agent_{session_id}', response,
                current_aoi or "None",
                referenced_object or "NONE"
            )
            agent_send_ts = _iso_now_ms()
            dispatcher.utter_message(response)
            logger.info("[SAY][%s] interactive_guide -> '%s'", turn_id, response)

            # TTS gate: only speak if no user turn very recently
            agent_tts_start_ts = None
            agent_tts_end_ts = None
            if can_proactively_tts(10.0):
                logger.info("[TTS-GATE][%s] OK (>=10s since user)", turn_id)
                tts_result = tts_from(
                    "interactive_guide",
                    response,
                    turn_id=turn_id,
                    on_complete=_make_ca_tts_update_callback(session_id or participant_id, turn_id, session_folder_name),
                )
                agent_tts_start_ts = tts_result.get("started_at")
                agent_tts_end_ts = tts_result.get("ended_at")
            else:
                logger.info("[TTS-GATE][%s] SKIP (recent user turn)", turn_id)

            policy_mode = _resolve_policy_mode(tracker)
            log_unified_turn(
                session_id=session_id or participant_id,
                participant_id=participant_id,
                turn_id=turn_id,
                turn_number=turn_number,
                agent_mode=_agent_mode_label(policy_mode),
                turn_start_ts=turn_start_ts,
                user_asr_end_ts=None,
                agent_send_ts=agent_send_ts,
                agent_tts_start_ts=agent_tts_start_ts,
                agent_tts_end_ts=agent_tts_end_ts,
                user_text="",
                agent_text=response,
                current_object_name=current_object,
                current_aoi_name=current_aoi,
                referenced_object=referenced_object,
                referenced_aoi=current_aoi,
                trigger_source="proactive_prompt",
                action="proactive",
                session_folder_name=session_folder_name,
                source="CA",
            )

        return [SlotSet("actorID", participant_id), SlotSet("agentID", session_id)]

    def interactive_agent_prompt_with_gaze(self, actorID, agentID, current_object=None, fallback_object=None):
        session_id = str(agentID or "")
        object_name = current_object if current_object else self._current_object_name(session_id)
        aoi_name = self._current_aoi_name(session_id)
        history_rows = self._session_history_rows(session_id)
        last_reply = SESSION_STORE.get_last_agent_reply(session_id) if session_id else None
        if object_name and object_name not in {"NONE", ""}:
            object_context = KNOWLEDGE_BASE.get_object_context(object_name)
            aoi_context = KNOWLEDGE_BASE.get_aoi_context(aoi_name)
            image = KNOWLEDGE_BASE.get_object_image(object_name)
            return build_silent_trigger_prompt(
                object_context=object_context,
                aoi_context=aoi_context,
                image=image,
                history_rows=history_rows,
                last_reply=last_reply,
            )

        fallback_object = fallback_object if fallback_object and fallback_object != "NONE" else None
        fallback_context = KNOWLEDGE_BASE.get_object_context(fallback_object) if fallback_object else None
        strategy = self._select_fallback_silence_strategy(last_reply, fallback_context)
        return build_fallback_silent_trigger_prompt(
            history_rows=history_rows,
            last_reply=last_reply,
            last_object_context=fallback_context,
            strategy=strategy,
        )

    def _select_fallback_silence_strategy(self, last_reply, fallback_context):
        reply = (last_reply or "").strip()
        if "?" in reply:
            return "reanchor_previous_object" if fallback_context else "ask_clarification"
        if fallback_context:
            return "ask_opinion"
        return "ask_clarification"

    def get_chatgpt_response(self, system_role, user_text=None):
        try:
            messages = [{"role": "system", "content": system_role}]
            if user_text:
                messages.append({"role": "user", "content": user_text})
            completion = client.chat.completions.create(
                model=RL_LLM_MODEL,
                messages=messages,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error("Error generating response (guide): %s", str(e))
            return " "

    def _log_conversation(self, first_actor, second_actor, response):
        try:
            _log_conversation_turn(first_actor or second_actor, first_actor, second_actor, response)
        except Exception as e:
            logger.error("Error logging conversation (guide): %s", str(e))

    def _current_object_name(self, session_id):
        if not session_id:
            return None
        return SESSION_STORE.get_current_object(str(session_id))

    def _current_aoi_name(self, session_id):
        if not session_id:
            return None
        return SESSION_STORE.get_current_aoi(str(session_id))

    def _resolve_current_object(self, tracker: Tracker, session_id: str) -> Any:
        metadata = (tracker.latest_message or {}).get("metadata") or {}
        tracker_object = (
            metadata.get("currentObjectName")
            or metadata.get("current_object")
            or metadata.get("objectName")
            or tracker.get_slot("objName")
        )
        normalized = KNOWLEDGE_BASE.normalize_object_name(tracker_object)
        if normalized:
            SESSION_STORE.set_current_object(session_id, normalized)
            return normalized
        if session_id:
            return SESSION_STORE.get_current_object(session_id)
        return None

    def _resolve_current_aoi(self, tracker: Tracker, session_id: str) -> Any:
        metadata = (tracker.latest_message or {}).get("metadata") or {}
        tracker_aoi = (
            metadata.get("currentAoiName")
            or metadata.get("current_aoi")
            or metadata.get("aoiName")
            or tracker.get_slot("aoiName")
        )
        normalized = KNOWLEDGE_BASE.normalize_aoi_name(tracker_aoi)
        if normalized:
            SESSION_STORE.set_current_aoi(session_id, normalized)
            return normalized
        if session_id:
            # Stale-AOI guard: Unity sends an empty AOI when the visitor is on a
            # painting but not fixating a specific region. Only reuse the remembered
            # AOI if it still belongs to the CURRENT exhibit -- otherwise it leaks
            # across paintings (e.g. calling Diego Bemba "Pedro Sunda").
            stored = SESSION_STORE.get_current_aoi(session_id)
            if stored:
                current_exhibit = KNOWLEDGE_BASE.to_exhibit_key(
                    SESSION_STORE.get_current_object(session_id)
                )
                valid_aois = KNOWLEDGE_BASE.exhibit_aoi_mapping.get(current_exhibit, [])
                if stored not in valid_aois:
                    SESSION_STORE.set_current_aoi(session_id, None)
                    return None
            return stored
        return None

    def _seconds_since_last_interaction(self, session_id):
        if not session_id:
            return float("inf")
        last_at = SESSION_STORE.get_last_interaction_at(str(session_id))
        if not last_at:
            return float("inf")
        try:
            parsed = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
        except Exception:
            logger.exception("Failed to parse last interaction timestamp: %s", last_at)
            return float("inf")

    def _session_history_rows(self, session_id):
        if not session_id:
            return []
        rows = []
        for entry in SESSION_STORE.get_history(str(session_id)):
            speaker = getattr(entry, "speaker", "unknown")
            text = getattr(entry, "text", "")
            rows.append(f"{speaker}: {text}")
        return rows

    def _remember_agent_reply(self, session_id, response):
        if not session_id:
            return
        SESSION_STORE.set_last_agent_reply(str(session_id), response)
        SESSION_STORE.set_last_interaction_at(str(session_id), _iso_now_ms())
