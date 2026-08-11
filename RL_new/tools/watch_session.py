"""
Live view of a running museum session.

Follows the newest session directory under data/sessions/ and prints each turn as
the runtime writes it, so you can read the conversation while the participant is
still in the headset.

    python tools/watch_session.py                 # follow the newest session, live
    python tools/watch_session.py --replay        # dump the newest session and exit
    python tools/watch_session.py --replay DIR    # dump a specific session and exit

Start it BEFORE the participant does; it waits for a session to appear and switches
to a new one automatically, so it survives a Play-mode restart between participants.

Implementation note: turns are tracked by turn_id, not by byte offset. The runtime
rewrites turns.jsonl wholesale in update_interaction_tts() to patch TTS timestamps,
which would leave an offset-based tail reading from the middle of a line.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Sessions live at <repo>/data/sessions/<arm>/<session_dir>/; this file is at
# <repo>/RL_new/tools/, hence two parents up to the repo root.
DEFAULT_SESSIONS_ROOT = Path(__file__).resolve().parents[2] / "data" / "sessions"

POLL_SECONDS = 0.5
WRAP_WIDTH = 96

# Proactive turns carry no visitor utterance. Calling them out makes it obvious when
# the agent spoke on its own rather than in reply to something.
TRIGGER_LABEL = {
    "user_input": "visitor",
    "focus_change": "focus-change",
    "unity_silence_timer": "SILENCE",
}


def wrap(text: str, indent: str) -> str:
    """Wrap to WRAP_WIDTH, continuation lines aligned under the first."""
    if not text:
        return ""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > WRAP_WIDTH:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return ("\n" + indent).join(lines)


def newest_session(root: Path) -> Optional[Path]:
    """Most recently created session directory across all arms, or None."""
    if not root.is_dir():
        return None
    dirs = [d for arm in root.iterdir() if arm.is_dir() for d in arm.iterdir() if d.is_dir()]
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def read_jsonl(path: Path) -> List[dict]:
    """Tolerant read: the runtime may be mid-write, so a trailing partial line is normal."""
    if not path.is_file():
        return []
    out = []
    try:
        # utf-8-sig: meta.json and friends are written with a BOM on this machine.
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # partial final line; it will parse on the next poll
    except OSError:
        return []
    return out


def judge_by_turn(session_dir: Path) -> Dict[str, dict]:
    return {
        str(r.get("turn_id")): r
        for r in read_jsonl(session_dir / "judge.jsonl")
        if r.get("turn_id")
    }


def print_header(session_dir: Path) -> None:
    meta = {}
    meta_path = session_dir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass
    print()
    print("=" * (WRAP_WIDTH + 12))
    print(f"  SESSION  {session_dir.name}")
    print(f"  arm={meta.get('agent_mode', '?')}  participant={meta.get('participant_id', '?')}")
    print(f"  {session_dir}")
    print("=" * (WRAP_WIDTH + 12))
    print()


def print_turn(turn: dict, judged: Dict[str, dict]) -> None:
    n = turn.get("turn_number", "?")
    # started_at_local is +02:00 here, but timestamps are UTC; slice the clock portion
    # and let the operator read it as elapsed rather than wall time.
    ts = str(turn.get("timestamp", ""))[11:19]
    trigger = TRIGGER_LABEL.get(turn.get("trigger_source"), turn.get("trigger_source") or "?")
    action = turn.get("action_label") or "?"
    exhibit = turn.get("mapped_exhibit") or turn.get("current_object_name") or "-"

    user_text = (turn.get("user_text") or "").strip()
    reply = (turn.get("reply_text") or "").strip()

    print(f"[T{n:<3} {ts}] {trigger:<12} {action:<32} @{exhibit}")
    if user_text:
        print(f"   visitor > {wrap(user_text, '             ')}")
    reply_tag = "  agent  > " if user_text else "  agent  > "
    print(f" {reply_tag}{wrap(reply, '             ')}")

    j = judged.get(str(turn.get("turn_id")))
    if j and str(j.get("decision", "")).lower() != "pass":
        print(f"   judge   ! {j.get('decision')} - {j.get('reason', '')}")
    print()


def follow(root: Path, once: bool, explicit: Optional[Path]) -> int:
    session_dir = explicit
    seen: set = set()
    announced = False

    if session_dir is None and once:
        session_dir = newest_session(root)
        if session_dir is None:
            print(f"No sessions found under {root}", file=sys.stderr)
            return 1

    while True:
        if explicit is None and not once:
            latest = newest_session(root)
            if latest is not None and latest != session_dir:
                # A new session started (or this is the first one). Reset and re-announce.
                session_dir, seen, announced = latest, set(), False

        if session_dir is None:
            time.sleep(POLL_SECONDS)
            continue

        if not announced:
            print_header(session_dir)
            announced = True

        records = read_jsonl(session_dir / "turns.jsonl")
        judged = judge_by_turn(session_dir)

        for rec in records:
            if rec.get("record_type") == "session_summary":
                key = f"summary:{rec.get('session_id')}"
                if key not in seen:
                    seen.add(key)
                    print(f"--- session ended: {rec.get('total_turns')} turns, "
                          f"reason={rec.get('reason')} ---\n")
                continue
            tid = rec.get("turn_id")
            if tid and tid not in seen:
                seen.add(tid)
                print_turn(rec, judged)

        sys.stdout.flush()
        if once:
            return 0
        time.sleep(POLL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser(description="Live view of a running museum session.")
    ap.add_argument("--replay", nargs="?", const="", metavar="DIR",
                    help="print an existing session and exit (default: newest)")
    ap.add_argument("--sessions-root", default=str(DEFAULT_SESSIONS_ROOT),
                    help=f"sessions root (default: {DEFAULT_SESSIONS_ROOT})")
    args = ap.parse_args()

    # Replies contain typographic quotes; a cp1252 console would raise on print.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    root = Path(args.sessions_root)
    explicit = Path(args.replay) if args.replay else None
    once = args.replay is not None

    if explicit is not None and not explicit.is_dir():
        print(f"Not a directory: {explicit}", file=sys.stderr)
        return 1

    try:
        return follow(root, once=once, explicit=explicit)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
