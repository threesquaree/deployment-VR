from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


RESEARCH_ROOT = Path(__file__).resolve().parent
RL_ROOT = RESEARCH_ROOT / "RL"

if str(RL_ROOT) not in sys.path:
    sys.path.insert(0, str(RL_ROOT))

from runtime_service.service import RuntimeService


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive CLI for the RL museum runtime without Unity.",
    )
    parser.add_argument(
        "--config",
        default=str(RL_ROOT / "runtime_config.json"),
        help="Path to the RL runtime_config.json file.",
    )
    parser.add_argument(
        "--participant-id",
        default="cli_user",
        help="Participant ID stored in the runtime logs.",
    )
    parser.add_argument(
        "--actor-node-id",
        default=None,
        help="Optional actor node ID stored in the runtime logs.",
    )
    parser.add_argument(
        "--object-name",
        default="NONE",
        help="Initial current_object_name, for example B1, B2, C5, or NONE.",
    )
    parser.add_argument(
        "--aoi-name",
        default=None,
        help="Initial current_aoi_name.",
    )
    parser.add_argument(
        "--mute",
        action="store_true",
        help="Disable local TTS playback for replies.",
    )
    return parser


def print_help() -> None:
    print("Commands:")
    print("  /help               Show this help.")
    print("  /status             Show current session context.")
    print("  /object <name>      Set current_object_name, for example B1 or NONE.")
    print("  /aoi <name>         Set current_aoi_name.")
    print("  /clear-aoi          Clear current_aoi_name.")
    print("  /exit               End session and quit.")


def main() -> int:
    args = build_parser().parse_args()

    service = RuntimeService(args.config)
    if args.mute:
        service.tts.enabled = False

    now = utc_now_iso()
    session = service.start_session(
        session_id=None,
        participant_id=args.participant_id,
        actor_node_id=args.actor_node_id,
        started_at=now,
        started_at_local=now,
    )

    current_object_name: Optional[str] = args.object_name
    current_aoi_name: Optional[str] = args.aoi_name

    print(f"session_id: {session.session_id}")
    print(f"model: {service.config['model_name']}")
    print(f"openai_model: {service.config['openai_model']}")
    print(f"current_object_name: {current_object_name}")
    print(f"current_aoi_name: {current_aoi_name}")
    print_help()

    while True:
        try:
            user_text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEnding session.")
            break

        if not user_text:
            continue

        if user_text == "/help":
            print_help()
            continue
        if user_text == "/status":
            print(f"session_id: {session.session_id}")
            print(f"current_object_name: {current_object_name}")
            print(f"current_aoi_name: {current_aoi_name}")
            continue
        if user_text.startswith("/object "):
            current_object_name = user_text[len("/object ") :].strip() or "NONE"
            print(f"current_object_name set to: {current_object_name}")
            continue
        if user_text.startswith("/aoi "):
            current_aoi_name = user_text[len("/aoi ") :].strip() or None
            print(f"current_aoi_name set to: {current_aoi_name}")
            continue
        if user_text == "/clear-aoi":
            current_aoi_name = None
            print("current_aoi_name cleared")
            continue
        if user_text == "/exit":
            break

        try:
            response = service.handle_turn(
                session_id=session.session_id,
                user_text=user_text,
                current_object_name=current_object_name,
                current_aoi_name=current_aoi_name,
                timestamp=utc_now_iso(),
                metadata={"source": "cli"},
            )
        except Exception as exc:
            print(f"error> {exc}")
            continue

        print(f"agent> {response.reply_text}")
        if response.action or response.option or response.subaction:
            print(
                "debug> "
                f"action={response.action} "
                f"option={response.option} "
                f"subaction={response.subaction} "
                f"mapped_exhibit={response.mapped_exhibit} "
                f"target_exhibit={response.target_exhibit}"
            )

    summary = service.end_session(
        session_id=session.session_id,
        ended_at=utc_now_iso(),
        reason="cli_exit",
    )
    print(
        f"Session ended. total_turns={summary.total_turns} "
        f"log_path={summary.log_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
