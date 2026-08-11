"""
Post-session speech-capture report.

Classifies every press-to-talk attempt in debug_logs/unity_debug.log as sent,
dropped, or skipped, and prints the capture rate. Works for both backends, so
Whisper sessions are directly comparable with the DictationRecognizer baseline
(P19 = 43%, P20 = 73%).

Usage:
  stt/.venv/Scripts/python.exe stt/check_session.py [--date 2026-07-28] [--since 14:00]
"""

import argparse
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "debug_logs" / "unity_debug.log"
TS = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]")


def parse_ts(line):
    m = TS.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--since", default=None, help="HH:MM lower bound")
    ap.add_argument("--until", default=None, help="HH:MM upper bound (bound BOTH ends to isolate one session)")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    lo = hi = None
    if args.since:
        lo = datetime.strptime(f"{args.date} {args.since}", "%Y-%m-%d %H:%M")
    if args.until:
        hi = datetime.strptime(f"{args.date} {args.until}", "%Y-%m-%d %H:%M")

    rows = []
    for line in open(args.log, encoding="utf-8", errors="replace"):
        if args.date not in line:
            continue
        t = parse_ts(line)
        if t is None or (lo and t < lo) or (hi and t > hi):
            continue
        rows.append((t, line))

    if not rows:
        print(f"No entries for {args.date}" + (f" since {args.since}" if args.since else ""))
        return

    attempts = []
    cur = None
    skips = 0
    failures = Counter()

    for t, line in rows:
        # Whisper backend
        if "armed sample=" in line:
            cur = {"start": t, "outcome": None}
            attempts.append(cur)
        elif "skip=press_too_short" in line:
            skips += 1
            cur = None
        # legacy backend
        elif "dictation_started" in line:
            cur = {"start": t, "outcome": None}
            attempts.append(cur)
        elif "sending_message" in line and cur:
            cur["outcome"] = "SENT"
            cur = None
        elif "error=mic_silent" in line and cur:
            cur["outcome"] = "DROP"
            failures["MicSilent (dead mic input)"] += 1
            cur = None
        elif "invalid_captured_speech" in line and cur:
            cur["outcome"] = "DROP"
            m = re.search(r"failure=(\w+)", line)
            failures[m.group(1) if m else "legacy_empty"] += 1
            cur = None

    sent = sum(1 for a in attempts if a["outcome"] == "SENT")
    drop = sum(1 for a in attempts if a["outcome"] == "DROP")
    unknown = len(attempts) - sent - drop
    total = len(attempts)
    rate = (sent / total * 100) if total else 0.0

    print("=" * 58)
    print(f"Speech capture report  {args.date}" + (f" from {args.since}" if args.since else ""))
    print("=" * 58)
    print(f"  attempts (excl. short-press skips) : {total}")
    print(f"  reached the agent                  : {sent}")
    print(f"  dropped                            : {drop}")
    if unknown:
        print(f"  unresolved (session ended mid-turn): {unknown}")
    print(f"  short-press skips (trigger misfire): {skips}")
    print()
    print(f"  CAPTURE RATE: {rate:.0f}%   (baseline: P19 43%, P20 73%)")
    if failures:
        print("\n  drop reasons:")
        for k, v in failures.most_common():
            print(f"    {v:3d}  {k}")

    degraded = sum(1 for _, l in rows if "recognizer_degraded" in l)
    if degraded:
        print(f"\n  !! recognizer_degraded fired {degraded}x -- investigate")

    utt = sum(1 for _, l in rows if "captured turn=" in l)
    if utt:
        print(f"\n  utterance WAVs written: {utt} (recoverable offline)")

    # Accept both '.' and ',' decimals: older log lines were written under a
    # comma-decimal locale before the formatting was pinned to invariant.
    def num(s):
        return float(s.replace(",", "."))

    press = [num(m.group(1)) for _, l in rows
             for m in [re.search(r"press_s=([0-9.,]+)", l)] if m]
    if press:
        print(f"\n  press durations: n={len(press)} "
              f"median={sorted(press)[len(press)//2]:.2f}s min={min(press):.2f}s max={max(press):.2f}s")
        taps = sum(1 for p in press if p < 1.0)
        if taps:
            print(f"    {taps} press(es) under 1.0s -- too short to contain a question")

    peaks = [num(m.group(1)) for _, l in rows
             for m in [re.search(r"peak=([0-9.,]+)", l)] if m]
    if peaks:
        quiet = sum(1 for p in peaks if p < 0.01)
        print(f"\n  mic level over {len(peaks)} captures: "
              f"min={min(peaks):.4f} median={sorted(peaks)[len(peaks)//2]:.4f} max={max(peaks):.4f}")
        if quiet:
            print(f"    {quiet}/{len(peaks)} captures had no signal.")
            print("    Cross-check against press durations above: short presses mean the")
            print("    visitor didn't speak; silence on LONG presses is a real mic fault")
            print("    (logged separately as error=mic_silent).")


if __name__ == "__main__":
    main()
