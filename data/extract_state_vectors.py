import csv
import glob
import json
import os
from pathlib import Path


DATA_ROOT = r"C:\Users\Vrmuseum\Desktop\Research\data\RL_data"
OUTPUT_CSV = r"C:\Users\Vrmuseum\Desktop\Research\data\state_vectors.csv"

EXHIBITS = ["Dom_Miguel", "King_Caspar", "Pedro_Sunda", "Turban", "Diego_Bemba"]
ACTION_GROUPS = ["Explain", "AskQuestion", "OfferTransition", "Conclude"]


def get_coverage(coverage_snapshot):
    row = {}
    for exhibit in EXHIBITS:
        data = coverage_snapshot.get(exhibit, {})
        row[f"coverage_{exhibit}"] = data.get("coverage", 0.0)
        row[f"mentioned_{exhibit}"] = data.get("mentioned", 0)
        row[f"total_{exhibit}"] = data.get("total", 5)
    return row


def get_option_counts(option_count_snapshot):
    row = {}
    for group in ACTION_GROUPS:
        row[f"count_{group}"] = option_count_snapshot.get(group, 0)
    return row


def compute_mean_coverage(coverage_snapshot):
    vals = [coverage_snapshot.get(exhibit, {}).get("coverage", 0.0) for exhibit in EXHIBITS]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def extract_all(data_root, output_csv):
    pattern = os.path.join(data_root, "*", "turns.jsonl")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No turns.jsonl found under {data_root}")
        return

    fieldnames = (
        [
            "session_id",
            "turn_number",
            "selected_action",
            "trigger_source",
            "trigger_type",
            "is_silence_event",
            "current_object_name",
            "mapped_exhibit",
            "current_aoi_name",
            "mean_coverage",
        ]
        + [f"coverage_{exhibit}" for exhibit in EXHIBITS]
        + [f"mentioned_{exhibit}" for exhibit in EXHIBITS]
        + [f"total_{exhibit}" for exhibit in EXHIBITS]
        + [f"count_{group}" for group in ACTION_GROUPS]
    )

    rows = []
    session_count = 0
    skipped_non_turn_records = 0

    for fpath in files:
        session_count += 1
        session_dir_name = Path(fpath).parent.name
        with open(fpath, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                try:
                    turn = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if turn.get("record_type") != "interaction":
                    skipped_non_turn_records += 1
                    continue

                coverage_snapshot = turn.get("coverage_snapshot", {}) or {}
                trigger_source = turn.get("trigger_source", "") or ""
                is_silence_event = bool((turn.get("debug") or {}).get("is_silence_event", False))
                row = {
                    "session_id": turn.get("session_id", session_dir_name),
                    "turn_number": turn.get("turn_number", ""),
                    "selected_action": turn.get("action", ""),
                    "trigger_source": trigger_source,
                    "trigger_type": "silence" if trigger_source == "unity_silence_timer" else "user_input",
                    "is_silence_event": 1 if is_silence_event else 0,
                    "current_object_name": turn.get("current_object_name", ""),
                    "mapped_exhibit": turn.get("mapped_exhibit", ""),
                    "current_aoi_name": turn.get("current_aoi_name", ""),
                    "mean_coverage": compute_mean_coverage(coverage_snapshot),
                }
                row.update(get_coverage(coverage_snapshot))
                row.update(get_option_counts(turn.get("option_count_snapshot", {}) or {}))
                rows.append(row)

    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. {len(rows)} turns extracted from {session_count} sessions.")
    print(f"Skipped non-turn records: {skipped_non_turn_records}")
    print(f"Output: {output_csv}")


if __name__ == "__main__":
    extract_all(DATA_ROOT, OUTPUT_CSV)
