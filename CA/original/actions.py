from openai import OpenAI
from dotenv import load_dotenv
from typing import Any, Text, Dict, List, Tuple
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

import os, csv, random, json
import sys
from time import perf_counter
from datetime import datetime, timezone
from Neo4jClient import Neo4jClient
from pathlib import Path

# ===== std libs for TTS/helpers =====
import time, threading, hashlib, traceback, subprocess
import pyttsx3

# ===== Logging (visible in `rasa run actions`) =====
import logging
logging.basicConfig(
    level=logging.INFO,  # flip to DEBUG for more detail
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger("actions")
# Quiet down Neo4j deprecation noise
logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# ===== Debug Logger =====
DEBUG_LOG_FILE = "C:\\Users\\Vrmuseum\\Desktop\\Research\\debug_logs\\rasa_debug.log"
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

# ===== OpenAI / Graph init =====
load_dotenv()
API_KEY = os.getenv('api_key')
client = OpenAI(api_key=API_KEY)
GRAPH = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="12345678")
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

    mode = str(slot_mode or os.getenv("POLICY_MODE", "baseline")).strip().lower()
    if mode not in POLICY_MODE_ALLOWED:
        logger.warning("Invalid POLICY_MODE=%s, fallback to baseline", mode)
        return "baseline"
    return mode


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
log_debug("RASA", "系统初始化", "RASA服务已启动，Neo4j连接已建立")


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

def speak(text: str, timeout_sec: float = 10.0):
    """Speak once using pyttsx3; only fallback if pyttsx3 crashes, not on timeout."""
    if not text or not text.strip():
        logger.info("[TTS] skipped empty text")
        return

    snippet = (text[:120] + "…") if len(text) > 120 else text
    logger.info("[TTS] START len=%d text='%s'", len(text), snippet)

    err_holder = {"exc": None}

    def _worker():
        try:
            _pyttsx3_speak_once(text)
        except Exception as e:
            err_holder["exc"] = e

    t = threading.Thread(target=_worker, name="TTSOneShot", daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        logger.warning("[TTS] pyttsx3 still speaking after %.1fs — skipping fallback", timeout_sec)
        # don't trigger PowerShell again
    elif err_holder["exc"] is not None:
        logger.error("[TTS] pyttsx3 ERROR: %s\n%s", err_holder["exc"], traceback.format_exc())
        _powershell_say(text)
    else:
        logger.info("[TTS] DONE")



# ---- Turn + global TTS dedupe ----
def _new_turn_id() -> str:
    return f"T{int(time.time()*1000)}-{random.randint(100,999)}"

_LAST_TTS_AT = 0.0
_LAST_TTS_HASH = None
_LAST_USER_TURN_AT = 0.0

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def mark_user_turn():
    """Mark that a user turn just happened (used to suppress proactive guide TTS)."""
    global _LAST_USER_TURN_AT
    _LAST_USER_TURN_AT = time.time()

def can_proactively_tts(min_gap_sec: float = 10.0) -> bool:
    """Allow guide speech only if no user turn in the last N seconds."""
    return (time.time() - _LAST_USER_TURN_AT) >= min_gap_sec

def tts_from(source: str, text: str, window_sec: float = 12.0, turn_id: str = "?"):
    """
    Speak once, globally debounced across ALL actions and sources.
    - source: 'providing_response' | 'interactive_guide'
    - window_sec: skip if we already spoke the exact same text recently
    """
    global _LAST_TTS_AT, _LAST_TTS_HASH
    if not text or not text.strip():
        logger.info("[TTS][%s][%s] skipped empty", source, turn_id)
        return

    now = time.time()
    h = _hash_text(text)

    # If same text within window => skip
    if _LAST_TTS_HASH == h and (now - _LAST_TTS_AT) < window_sec:
        logger.info("[TTS][%s][%s] SKIP duplicate within %.1fs", source, turn_id, window_sec)
        return

    _LAST_TTS_HASH, _LAST_TTS_AT = h, now
    logger.info("[TTS][%s][%s] SPEAK len=%d", source, turn_id, len(text))
    speak(text)


# =============================================================================
#                             Utility: CSV logging
# =============================================================================

def log_conversation(csv_filename, actor, response, aoiname, objectname):
    # Deprecated: use unified JSONL turn log instead.
    return


UNIFIED_TURN_LOG_DIR = Path(r"C:\Users\Vrmuseum\Desktop\Research\data\sessions")
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


def _get_ca_session_dir(session_id: Any, turn_start_ts: Any) -> Path:
    key = str(session_id)
    if key in _CA_SESSION_DIRS:
        return _CA_SESSION_DIRS[key]
    utc_tag = _safe_utc_tag(turn_start_ts)
    session_dir = UNIFIED_TURN_LOG_DIR / f"ca_{key}_{utc_tag}"
    session_dir.mkdir(parents=True, exist_ok=True)
    _CA_SESSION_DIRS[key] = session_dir
    return session_dir


def _coerce_rasa_timestamp(ts_value: Any) -> Any:
    if ts_value is None:
        return None
    try:
        ts = float(ts_value)
        return datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
    except Exception:
        return str(ts_value)


def _estimate_turn_number(tracker: Tracker) -> int:
    try:
        events = tracker.events or []
        user_turns = sum(1 for e in events if isinstance(e, dict) and e.get("event") == "user")
        return max(1, int(user_turns))
    except Exception:
        return 1


def log_unified_turn(
    session_id: Any,
    turn_id: str,
    turn_number: int,
    turn_start_ts: Any,
    user_asr_end_ts: Any,
    agent_send_ts: Any,
    agent_tts_start_ts: Any,
    agent_tts_end_ts: Any,
    user_text: str,
    agent_text: str,
    referenced_object: Any,
    referenced_aoi: Any,
    action_label: Any,
    source: str = "CA",
):
    payload = {
        "session_id": str(session_id),
        "turn_id": turn_id,
        "turn_number": turn_number,
        "turn_start_ts": turn_start_ts,
        "user_asr_end_ts": user_asr_end_ts,
        "agent_send_ts": agent_send_ts,
        "agent_tts_start_ts": agent_tts_start_ts,
        "agent_tts_end_ts": agent_tts_end_ts,
        "user_text": user_text,
        "agent_text": agent_text,
        "referenced_object": referenced_object,
        "referenced_aoi": referenced_aoi,
        "action_label": action_label,
        "source": source,
        "timestamp": _iso_now_ms(),
        "record_type": "turn",
    }
    session_dir = _get_ca_session_dir(session_id, turn_start_ts)
    path = session_dir / "turns.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        meta = {
            "source": "ca",
            "session_id": str(session_id),
            "started_at_utc": _iso_now_ms(),
            "participant_id": str(session_id),
            "actor_id": str(session_id),
            "schema_version": "sessions_v1",
        }
        with meta_path.open("w", encoding="utf-8") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)


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
        user_input = tracker.latest_message.get('text', '')
        actor_id = user_input
        logger.info("[GET_ACTOR] input=%s", actor_id)
        log_debug("RASA", "ActionGetActorID开始", f"user_input={actor_id}")

        neo4j_start = perf_counter()
        result = GRAPH.creating_an_agent(actor_id, datetime.now().strftime('%Y%m%d%H%M%S'))
        neo4j_ms = (perf_counter() - neo4j_start) * 1000.0
        agent_id = result[0]['agentID']
        response_text = f"Actor ID: {actor_id}, Agent ID: {agent_id}"

        logger.info("[GET_ACTOR] Actor ID: %s, Agent ID: %s", actor_id, agent_id)
        log_debug("RASA", "ActionGetActorID图数据库完成", f"actor_id={actor_id}, agent_id={agent_id}, neo4j_ms={neo4j_ms:.2f}")
        dispatcher.utter_message(text=response_text)
        total_ms = (perf_counter() - action_start) * 1000.0
        log_debug("RASA", "ActionGetActorID完成", f"actor_id={actor_id}, agent_id={agent_id}, response_text={response_text}, total_ms={total_ms:.2f}")

        # mark the user turn so proactive agent won't overlap immediately
        mark_user_turn()

        return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]


class ActionProvidingResponse(Action):
    def name(self) -> Text:
        return "action_providing_response"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        turn_id = _new_turn_id()
        turn_number = _estimate_turn_number(tracker)
        turn_start_ts = _iso_now_ms()
        user_asr_end_ts = _coerce_rasa_timestamp((tracker.latest_message or {}).get("timestamp"))
        msg_text = (tracker.latest_message or {}).get("text", "")
        logger.info("[ENTER][%s] ActionProvidingResponse text='%s'", turn_id, msg_text)
        log_debug("RASA", "ActionProvidingResponse开始", f"turn_id={turn_id}, msg_text={msg_text}")

        agent_id = GRAPH.get_agent_id()[0]['id']
        actor_id = GRAPH.get_user_id()[0]['id']
        logger.info("[CTX][%s] actor_id=%s agent_id=%s", turn_id, actor_id, agent_id)

        mark_user_turn()
        policy_mode = _resolve_policy_mode(tracker)
        logger.info("[POLICY][%s] mode=%s", turn_id, policy_mode)

        # ===============================================================
        # === OLD LOGIC RESTORED: DIRECT NEO4J GAZE CHECK (LEGACY WAY) ==
        # ===============================================================
        obj_data = None
        try:
            obj_data = GRAPH.get_last_obj_id(actor_id)
            logger.info("[DEBUG][%s] Neo4j get_last_obj_id() -> %s", turn_id, obj_data)
        except Exception as e:
            logger.error("[DEBUG][%s] Error calling get_last_obj_id: %s", turn_id, e)

        obj_now = None
        if obj_data and (obj_data[0].get('b.objectName') or obj_data[0].get('objectName')):
            obj_now = obj_data[0].get('b.objectName') or obj_data[0].get('objectName')

        logger.info("[GATE][%s] current painting (legacy logic) = %s", turn_id, obj_now)

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
                self._log_conversation(actor_id, agent_id, msg_text)
                try:
                    aoi = GRAPH.get_last_aoi_id(actor_id)
                    aoi_name = aoi[0]['b.name'] if aoi else "None"
                    logger.debug("[DEBUG][%s] AOI resolved to %s", turn_id, aoi_name)
                except Exception as e:
                    logger.error("[DEBUG][%s] Error fetching AOI: %s", turn_id, e)
                    aoi_name = "None"

                log_conversation(
                    f'logs/conversation_{actor_id}.csv',
                    f'user_{actor_id}', msg_text, aoi_name, obj_now
                )

                random_response = random.choice(responses)
                agent_send_ts = _iso_now_ms()
                dispatcher.utter_message(random_response)
                logger.info("[SAY][%s] providing_response(REPEAT) -> '%s'", turn_id, random_response)
                agent_tts_start_ts = _iso_now_ms()
                tts_from("providing_response", random_response, turn_id=turn_id)
                agent_tts_end_ts = _iso_now_ms()

                self._log_conversation(agent_id, actor_id, random_response)
                log_conversation(
                    f'logs/conversation_{actor_id}.csv',
                    f'agent_{agent_id}', random_response, aoi_name, obj_now
                )
                log_unified_turn(
                    session_id=actor_id,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    turn_start_ts=turn_start_ts,
                    user_asr_end_ts=user_asr_end_ts,
                    agent_send_ts=agent_send_ts,
                    agent_tts_start_ts=agent_tts_start_ts,
                    agent_tts_end_ts=agent_tts_end_ts,
                    user_text=msg_text,
                    agent_text=random_response,
                    referenced_object=obj_now,
                    referenced_aoi=aoi_name,
                    action_label=None,
                    source="CA",
                )

            else:
                # Normal user question
                self._log_conversation(actor_id, agent_id, msg_text)
                try:
                    aoi = GRAPH.get_last_aoi_id(actor_id)
                    aoi_name = aoi[0]['b.name'] if aoi else "None"
                    logger.debug("[DEBUG][%s] AOI resolved to %s", turn_id, aoi_name)
                except Exception as e:
                    logger.error("[DEBUG][%s] Error fetching AOI: %s", turn_id, e)
                    aoi_name = "None"

                log_conversation(
                    f'logs/conversation_{actor_id}.csv',
                    f'user_{actor_id}', msg_text, aoi_name, obj_now
                )

                if policy_mode == "rl":
                    try:
                        response = self._get_rl_response(actor_id, agent_id, msg_text, obj_now, turn_id)
                    except Exception as e:
                        logger.error("[RL][%s] runtime failed: %s", turn_id, e, exc_info=True)
                        response = "RL mode is enabled, but response generation failed for this turn."
                else:
                    system_role = self._get_system_role(actor_id, agent_id, msg_text)
                    response = self.get_chatgpt_response(system_role, msg_text)

                agent_send_ts = _iso_now_ms()
                dispatcher.utter_message(response)
                logger.info("[SAY][%s] providing_response -> '%s'", turn_id, response)
                agent_tts_start_ts = _iso_now_ms()
                tts_from("providing_response", response, turn_id=turn_id)
                agent_tts_end_ts = _iso_now_ms()

                self._log_conversation(agent_id, actor_id, response)
                log_conversation(
                    f'logs/conversation_{actor_id}.csv',
                    f'agent_{agent_id}', response, aoi_name, obj_now
                )
                log_unified_turn(
                    session_id=actor_id,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    turn_start_ts=turn_start_ts,
                    user_asr_end_ts=user_asr_end_ts,
                    agent_send_ts=agent_send_ts,
                    agent_tts_start_ts=agent_tts_start_ts,
                    agent_tts_end_ts=agent_tts_end_ts,
                    user_text=msg_text,
                    agent_text=response,
                    referenced_object=obj_now,
                    referenced_aoi=aoi_name,
                    action_label=None,
                    source="CA",
                )

            return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]

        # ===============================================================
        # ====================== FALLBACK BRANCH ========================
        # ===============================================================
        logger.warning("[FALLBACK][%s] Triggering fallback — no painting found!", turn_id)
        try:
            fallback_obj = GRAPH.get_last_obj_id(actor_id)
            fallback_aoi = GRAPH.get_last_aoi_id(actor_id)
            logger.warning("[FALLBACK-DEBUG][%s] Neo4j snapshot: obj=%s | aoi=%s",
                           turn_id, fallback_obj, fallback_aoi)
        except Exception as e:
            logger.error("[FALLBACK-DEBUG][%s] Could not fetch fallback info: %s", turn_id, e)

        if msg_text == 'Repeat Question':
            responses = [
                "Could you please repeat your question so I can assist you better?",
                "I'm not entirely sure I understand; could you repeat your question?",
                "Could you repeat your question? I might have missed something.",
                "I want to make sure I got that right; could you repeat or confirm what you said?"
            ]
            self._log_conversation(actor_id, agent_id, msg_text)
            log_conversation(
                f'logs/conversation_{actor_id}.csv',
                f'user_{actor_id}', msg_text, 'None', 'None'
            )

            random_response = random.choice(responses)
            agent_send_ts = _iso_now_ms()
            dispatcher.utter_message(random_response)
            logger.info("[SAY][%s] providing_response(REPEAT/FALLBACK) -> '%s'", turn_id, random_response)
            agent_tts_start_ts = _iso_now_ms()
            tts_from("providing_response", random_response, turn_id=turn_id)
            agent_tts_end_ts = _iso_now_ms()

            self._log_conversation(agent_id, actor_id, random_response)
            log_conversation(
                f'logs/conversation_{actor_id}.csv',
                f'agent_{agent_id}', random_response, 'None', 'None'
            )
            log_unified_turn(
                session_id=actor_id,
                turn_id=turn_id,
                turn_number=turn_number,
                turn_start_ts=turn_start_ts,
                user_asr_end_ts=user_asr_end_ts,
                agent_send_ts=agent_send_ts,
                agent_tts_start_ts=agent_tts_start_ts,
                agent_tts_end_ts=agent_tts_end_ts,
                user_text=msg_text,
                agent_text=random_response,
                referenced_object=None,
                referenced_aoi=None,
                action_label=None,
                source="CA",
            )

        else:
            # General fallback: user not looking at any painting
            self._log_conversation(actor_id, agent_id, msg_text)
            log_conversation(
                f'logs/conversation_{actor_id}.csv',
                f'user_{actor_id}', msg_text, 'None', 'None'
            )

            system_role = f"""
            ### System Role
            You are an AI assistant serving as a virtual guide for a VR exhibition featuring five unique paintings.
            The user is not currently viewing any paintings. Invite them to go to the main room and start exploring one.
            Guidelines: No links/emojis; no speculation; max two sentences.
            Exhibit Data: {GRAPH.get_graph_data()}
            """
            response = self.get_chatgpt_response(system_role, msg_text)
            agent_send_ts = _iso_now_ms()
            dispatcher.utter_message(response)
            logger.warning("[SAY][%s] providing_response(FALLBACK) -> '%s'", turn_id, response)
            agent_tts_start_ts = _iso_now_ms()
            tts_from("providing_response", response, turn_id=turn_id)
            agent_tts_end_ts = _iso_now_ms()

            self._log_conversation(agent_id, actor_id, response)
            log_conversation(
                f'logs/conversation_{actor_id}.csv',
                f'agent_{agent_id}', response, 'None', 'None'
            )
            log_unified_turn(
                session_id=actor_id,
                turn_id=turn_id,
                turn_number=turn_number,
                turn_start_ts=turn_start_ts,
                user_asr_end_ts=user_asr_end_ts,
                agent_send_ts=agent_send_ts,
                agent_tts_start_ts=agent_tts_start_ts,
                agent_tts_end_ts=agent_tts_end_ts,
                user_text=msg_text,
                agent_text=response,
                referenced_object=None,
                referenced_aoi=None,
                action_label=None,
                source="CA",
            )

        return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]



    # ---- helpers ----
    def _build_rl_dialogue_history(self, actorID: Any, agentID: Any) -> List[Tuple[str, str, int]]:
        rows = GRAPH.conversation_history(actorID, agentID) or []
        rows = list(reversed(rows))
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

    def _get_rl_response(self, actorID: Any, agentID: Any, user_input: str, obj_now: str, turn_id: str) -> str:
        runtime = _get_rl_runtime()
        dialogue_history = self._build_rl_dialogue_history(actorID, agentID)
        result = runtime.generate_turn(
            user_message=user_input,
            exhibit=obj_now,
            dialogue_history=dialogue_history,
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

    def _get_system_role(self, actorID, agentID, user_input) -> str:
        return f"""
[System Role]
You are an AI assistant serving as a virtual museum guide for a VR exhibition of five unique paintings.

[Current Context]
The main room has five paintings across two walls.
Currently, the user is viewing: ({GRAPH.get_last_obj(actorID)}).
Focus area: {GRAPH.get_last_aoi(actorID)}.
Image: {GRAPH.get_image_of_painting(actorID)}.
Prior agent response: {GRAPH.get_last_agent_response(actorID, agentID)}.
Conversation history: {GRAPH.conversation_history(actorID, agentID)}.
Exhibit Data: {GRAPH.get_graph_data()}.

[User Input]
{user_input}

[Response Constraints]
No links or emojis.
No speculation.
Avoid repetition.
Maximum two sentences.
        """

    def _log_conversation(self, first_actor, second_actor, response):
        try:
            start_time = datetime.now().strftime('%Y%m%d%H%M%S')
            cleaned_text = (response or "").replace("'", "").replace('"', "")
            GRAPH.import_conv(first_actor, second_actor, cleaned_text, start_time)
        except Exception as e:
            logger.error("Error logging conversation: %s", str(e))

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

        turn_id = _new_turn_id()
        logger.info("[ENTER][%s] interactive_guide_interaction", turn_id)

        agent_id = GRAPH.get_agent_id()[0]['id']
        actor_id = GRAPH.get_user_id()[0]['id']
        logger.info("[CTX][%s] actor_id=%s agent_id=%s", turn_id, actor_id, agent_id)

        names = ['A1','A2','A3','B1','B2','B3','B4','B5','C1','C2','C3','C4','C5','C6','D1','D2','D3','D4','D5']

        if GRAPH.get_last_obj_id(actor_id):
            if GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'] in names:

                if GRAPH.get_last_time_of_interaction(actor_id, agent_id):
                    diff = float(datetime.now().strftime('%Y%m%d%H%M%S')) - float(GRAPH.get_last_time_of_interaction(actor_id, agent_id)[0]['tim'])
                else:
                    diff = float(datetime.now().strftime('%Y%m%d%H%M%S')) - 0

                logger.info("[DIFF][%s] guide diff=%s", turn_id, diff)

                if diff > 30:
                    system_role = self.interactive_agent_prompt_with_gaze(actor_id, agent_id)
                    response = self.get_chatgpt_response(system_role)

                    self._log_conversation(agent_id, actor_id, response)
                    log_conversation(
                        f'logs/conversation_{actor_id}.csv',
                        f'agent_{agent_id}', response,
                        GRAPH.get_last_aoi_id(actor_id)[0]['b.name'],
                        GRAPH.get_last_obj_id(actor_id)[0]['b.objectName']
                    )

                    dispatcher.utter_message(response)
                    logger.info("[SAY][%s] interactive_guide -> '%s'", turn_id, response)

                    # TTS gate: only speak if no user turn very recently
                    if can_proactively_tts(10.0):
                        logger.info("[TTS-GATE][%s] OK (>=10s since user)", turn_id)
                        tts_from("interactive_guide", response, turn_id=turn_id)
                    else:
                        logger.info("[TTS-GATE][%s] SKIP (recent user turn)", turn_id)

        return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]

    def interactive_agent_prompt_with_gaze(self, actorID, agentID):
        return f"""
        ### System Role
        You are an AI assistant serving as a virtual museum guide in a VR exhibition featuring five unique paintings.
        The user is currently observing: ({GRAPH.get_last_obj(actorID)}).
        Focus area: {GRAPH.get_last_aoi(actorID)}.
        Image: {GRAPH.get_image_of_painting(actorID)}.
        Conversation history: {GRAPH.conversation_history(actorID, agentID)}.
        Provide concise (≤2 sentences) insight encouraging exploration; no links/emojis/speculation.
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
            logger.error("Error generating response (guide): %s", str(e))
            return " "

    def _log_conversation(self, first_actor, second_actor, response):
        try:
            start_time = datetime.now().strftime('%Y%m%d%H%M%S')
            cleaned_text = (response or "").replace("'", "").replace('"', "")
            GRAPH.import_conv(first_actor, second_actor, cleaned_text, start_time)
        except Exception as e:
            logger.error("Error logging conversation (guide): %s", str(e))
