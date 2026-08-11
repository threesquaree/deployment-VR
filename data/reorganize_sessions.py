"""One-off reorganisation of the round-2 study data for analysis (2026-08-10).

Turns `data/sessions/{rl,baseline}` from a mix of participants, researcher tests,
aborted runs and redundant exports into a clean, analysis-ready layout:

    data/sessions/
        rl/                    15 participants, P21..P35   (all F2_flat_learn_both)
        baseline/              20 participants, P01..P20   (23 sessions; P05/P07/P19 have 2)
        rl_excluded/           13 folders + excluded_manifest.csv
        baseline_excluded/      8 folders + excluded_manifest.csv
        baseline_aggregates/   23 redundant user-utterance exports
        test data/rl/          20 researcher-test folders
        test data/baseline/     7 researcher-test folders

Everything is a MOVE or RENAME on one volume. Nothing is deleted, and every
change is recorded in the manifests, so the whole thing is reversible.

Usage (from the Research/ root, with the study venv):
    RL\.venv\Scripts\python.exe data\reorganize_sessions.py           # dry run
    RL\.venv\Scripts\python.exe data\reorganize_sessions.py --apply   # execute
"""
from __future__ import print_function

import csv
import json
import os
import shutil
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
SESSIONS = os.path.join(ROOT, "sessions")
RL = os.path.join(SESSIONS, "rl")
BASE = os.path.join(SESSIONS, "baseline")

APPLY = "--apply" in sys.argv

# --- the four folders whose files are split across rl/ and baseline/ ----------
SPLIT_FOLDERS = [
    "rl_8e667cc452dd45818c854cfe7b2cc266_2026-07-28T23-57-13",
    "rl_e33efd20d0cc4f5da2e267f75eb2293d_2026-07-29T00-41-12",
    "rl_4a19ea0e8fa340b297196a5948866869_2026-07-29T17-41-31",
    "rl_d1f4bb17e4554bdeb508bf16c178898d_2026-07-29T18-28-01",
]

# --- RL: explicit exclusion reasons (everything else is keeper or test) -------
RL_EXCLUDED = {
    # superseded: July 29 block ran the OLD pre-migration agent (158-d SMDP)
    "rl_49513238742e4a3fa8c136fe668fc2f5_2026-07-29T11-20-02": "superseded_old_agent",
    "rl_91c55a1443d24d83a7e14ab9dad84a62_2026-07-29T12-24-20": "superseded_old_agent",
    "rl_9fe6a2a6905b49daa9f71fcfdaf80bb5_2026-07-29T13-06-37": "superseded_old_agent",
    "rl_94041a28d4f14ea29bc061d6718bc2c2_2026-07-29T13-55-39": "superseded_old_agent",
    "rl_18e3862c3e6e4563a9ad5e4c68618cbc_2026-07-29T14-03-55": "superseded_old_agent",
    "rl_772f83ba2dc24892970b826040721a1f_2026-07-29T15-15-05": "superseded_old_agent",
    "rl_a29c22871b6248b09457c089765e60ce_2026-07-29T17-02-54": "superseded_old_agent",
    # failed for a known technical reason
    "rl_cec718292e0543b58dc72be123994719_2026-08-05T13-27-13": "failed_technical_no_turns",
    "rl_9b79950f387f45709d71c0038b4dc14e_2026-08-05T16-40-05": "failed_technical_eye_tracking_dead",
    "rl_f1ec8b4b065d495da5170e8353e0a4b7_2026-08-06T13-06-12": "failed_technical_openrouter_402",
    "rl_66fbf5b6d8104010aef99cabf1aa47a2_2026-08-06T17-26-25": "failed_technical_no_turns",
    # aborted before a participant number was entered
    "rl_d1f4bb17e4554bdeb508bf16c178898d_2026-07-29T18-28-01": "aborted_blank_id",
    "rl_e70597e54a624c199018ec684da56a9c_2026-08-05T16-37-02": "aborted_blank_id",
}

# RL keepers, in the order they were run -> P21..P35
RL_KEEPERS = [
    "rl_cf3f3aa286f24c90900860a18ade1c41_2026-08-04T13-07-23",
    "rl_1aa84bd679474915a5e43115575c3d8a_2026-08-04T13-58-25",
    "rl_bdc90f552ce44c2f9c5ff79b00763bed_2026-08-04T15-33-48",
    "rl_30d6c3df31514cb3ad113d13bf696aff_2026-08-05T11-09-25",
    "rl_e8f0299500a24bd58e30f4ed0f8de02e_2026-08-05T12-06-50",
    "rl_73a796342f5c45b5858b18d391df06e2_2026-08-05T13-36-17",
    "rl_c22b0b27dc22485a96e9f902cbf1e914_2026-08-06T12-18-45",  # truncated by OpenRouter outage
    "rl_dc06feb1e4934d41b6042429ad92e62e_2026-08-06T13-20-18",
    "rl_e6a9862fb78b4fe9aa73cb9e74e93163_2026-08-06T15-04-42",
    "rl_4e5a771953f144afa84e7179ce49394d_2026-08-06T15-59-24",
    "rl_8fc0ef99c74047a69dd2aedb5ab8e394_2026-08-06T17-37-37",
    "rl_af653775faca489d8c7c320ee3664953_2026-08-07T14-10-33",
    "rl_4aaa4dbd2ea14036ba8baf6b08501939_2026-08-07T15-24-15",
    "rl_92ebf0c8d0044a258b6489d113d07e06_2026-08-07T16-06-50",
    "rl_a6b3a7dacf194054afba64167d2fa6b6_2026-08-07T17-07-26",
]

RL_NOTES = {
    "rl_c22b0b27dc22485a96e9f902cbf1e914_2026-08-06T12-18-45":
        "TRUNCATED: OpenRouter 402 killed the session at turn 14; 7 further "
        "utterances exist as WAVs in speech/ (utt_0015-0021) but were never answered",
}


# ----------------------------------------------------------------------------
def read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return None


def turn_rows(folder):
    """Non-summary rows in turns.jsonl (RL) / interaction rows (baseline)."""
    path = os.path.join(folder, "turns.jsonl")
    if not os.path.isfile(path):
        return None
    rows = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("record_type") == "session_summary":
                continue
            if r.get("record_type") == "session_start":
                continue
            rows.append(r)
    return rows


def dir_bytes(path):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def pid_base(participant_id):
    """'030 (2026-08-06 15-59-24)' -> '030';  ' (…)' -> ''."""
    return (participant_id or "").split(" (")[0].strip()


def exhibits_of(rows):
    seen = []
    for r in rows or []:
        ex = r.get("mapped_exhibit")
        if ex and ex not in seen:
            seen.append(ex)
    return "|".join(seen)


def move(src, dst, actions):
    actions.append(("move", src, dst))
    if APPLY:
        parent = os.path.dirname(dst)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        shutil.move(src, dst)


# ----------------------------------------------------------------------------
def merge_split_folders(actions):
    """Union the rl/ and baseline/ halves of the 4 split folders into rl/."""
    merged = []
    for name in SPLIT_FOLDERS:
        a = os.path.join(RL, name)
        b = os.path.join(BASE, name)
        if not os.path.isdir(b):
            continue
        moved = []
        for f in sorted(os.listdir(b)):
            src = os.path.join(b, f)
            target_name = f
            if os.path.exists(os.path.join(a, f)):
                # never overwrite: baseline's copy is kept side by side
                stem, ext = os.path.splitext(f)
                target_name = "{0}.baseline{1}".format(stem, ext)
            dst = os.path.join(a, target_name)
            actions.append(("merge", src, dst))
            moved.append("{0}->{1}".format(f, target_name))
            if APPLY:
                shutil.move(src, dst)
        if APPLY and not os.listdir(b):
            os.rmdir(b)
        actions.append(("rmdir_empty", b, ""))
        merged.append((name, moved))
    return merged


def classify_rl():
    keepers, excluded, tests, unknown = [], [], [], []
    for name in sorted(os.listdir(RL)):
        path = os.path.join(RL, name)
        if not os.path.isdir(path):
            continue
        meta = read_json(os.path.join(path, "meta.json")) or {}
        pid = meta.get("participant_id", "")
        if name in RL_EXCLUDED:
            excluded.append((name, RL_EXCLUDED[name], pid))
        elif name in RL_KEEPERS:
            keepers.append(name)
        elif "test" in pid.lower() or pid.strip().lower() == "verify":
            tests.append((name, pid))
        else:
            unknown.append((name, pid))
    return keepers, excluded, tests, unknown


def classify_baseline():
    keepers, excluded, tests, aggregates, unknown = [], [], [], [], []
    for name in sorted(os.listdir(BASE)):
        path = os.path.join(BASE, name)
        if not os.path.isdir(path):
            continue
        if name.startswith("rl_"):
            continue  # handled by merge_split_folders
        meta_path = os.path.join(path, "meta.json")
        if not os.path.isfile(meta_path):
            aggregates.append(name)
            continue
        meta = read_json(meta_path) or {}
        pid = meta.get("participant_id", "")
        base = pid_base(pid)
        rows = turn_rows(path)
        n = len(rows) if rows is not None else None
        if "test" in pid.lower():
            tests.append((name, pid))
        elif base == "" or not base.isdigit():
            excluded.append((name, "aborted_blank_id", pid))
        elif not n:
            excluded.append((name, "no_turns_recorded", pid))
        else:
            keepers.append((name, int(base), meta.get("started_at_local", ""), n))
    # ca_unknown has meta.json but no identity at all
    return keepers, excluded, tests, aggregates, unknown


# ----------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("REORGANISE STUDY SESSIONS   mode = {0}".format("APPLY" if APPLY else "DRY RUN"))
    print("=" * 78)

    bytes_before = dir_bytes(SESSIONS)
    n_rl_before = len([d for d in os.listdir(RL) if os.path.isdir(os.path.join(RL, d))])
    n_bl_before = len([d for d in os.listdir(BASE) if os.path.isdir(os.path.join(BASE, d))])
    print("before: rl={0} folders, baseline={1} folders, {2:.2f} GB total\n".format(
        n_rl_before, n_bl_before, bytes_before / 1e9))

    actions = []

    # --- 1. merge split folders -------------------------------------------
    merged = merge_split_folders(actions)
    print("[1] merged {0} split folder(s) from baseline/ into rl/:".format(len(merged)))
    for name, moved in merged:
        print("      {0}".format(name[:52]))
        for m in moved:
            print("         {0}".format(m))

    # --- 2. classify -------------------------------------------------------
    rl_keep, rl_excl, rl_test, rl_unknown = classify_rl()
    bl_keep, bl_excl, bl_test, bl_agg, bl_unknown = classify_baseline()

    print("\n[2] classification")
    print("      RL:       keep={0}  excluded={1}  test={2}  UNKNOWN={3}".format(
        len(rl_keep), len(rl_excl), len(rl_test), len(rl_unknown)))
    print("      baseline: keep={0}  excluded={1}  test={2}  aggregates={3}  UNKNOWN={4}".format(
        len(bl_keep), len(bl_excl), len(bl_test), len(bl_agg), len(bl_unknown)))
    for n, p in rl_unknown + bl_unknown:
        print("      !! UNCLASSIFIED: {0}  pid={1!r}".format(n, p))

    assert not rl_unknown and not bl_unknown, "unclassified folders present - aborting"
    assert len(rl_keep) == 15, "expected 15 RL keepers, got {0}".format(len(rl_keep))
    assert len(rl_keep) + len(rl_excl) + len(rl_test) == n_rl_before, "RL accounting mismatch"
    assert (len(bl_keep) + len(bl_excl) + len(bl_test) + len(bl_agg)
            + len(SPLIT_FOLDERS)) == n_bl_before, "baseline accounting mismatch"

    # --- 3. build the rename plan -----------------------------------------
    rl_plan = []
    for i, name in enumerate(RL_KEEPERS):
        path = os.path.join(RL, name)
        meta = read_json(os.path.join(path, "meta.json")) or {}
        rows = turn_rows(path) or []
        rl_plan.append({
            "number": 21 + i, "session_index": 1, "old": name,
            "new": "P{0}_{1}".format(21 + i, name),
            "old_id": pid_base(meta.get("participant_id", "")),
            "session_id": meta.get("session_id", ""),
            "start": meta.get("started_at_local", ""),
            "turns": len(rows), "exhibits": exhibits_of(rows),
            "agent_version": "F2_flat_learn_both_ep1000",
            "notes": RL_NOTES.get(name, ""),
        })

    by_number = defaultdict(list)
    for name, num, start, n in bl_keep:
        by_number[num].append((start, name, n))
    bl_plan = []
    for num in sorted(by_number):
        sessions = sorted(by_number[num])
        multi = len(sessions) > 1
        for idx, (start, name, n) in enumerate(sessions, start=1):
            path = os.path.join(BASE, name)
            meta = read_json(os.path.join(path, "meta.json")) or {}
            rows = turn_rows(path) or []
            prefix = "P{0:02d}_s{1}".format(num, idx) if multi else "P{0:02d}".format(num)
            bl_plan.append({
                "number": num, "session_index": idx, "old": name,
                "new": "{0}_{1}".format(prefix, name),
                "old_id": pid_base(meta.get("participant_id", "")),
                "session_id": meta.get("session_id", ""),
                "start": start, "turns": n,
                "exhibits": exhibits_of(rows),
                "agent_version": "baseline_ca", "notes": "",
            })

    print("\n[3] RL renumbering (15 participants)")
    for p in rl_plan:
        print("      P{0}  <- id {1:<4} {2}  turns={3:<3} {4}".format(
            p["number"], p["old_id"], p["start"][:16], p["turns"], p["notes"][:40]))
    print("\n    baseline renaming ({0} sessions, {1} participants)".format(
        len(bl_plan), len(by_number)))
    for p in bl_plan:
        tag = "P{0:02d}".format(p["number"]) + ("_s{0}".format(p["session_index"])
                                                if any(q["number"] == p["number"] and q is not p
                                                       for q in bl_plan) else "")
        print("      {0:<8} {1}  turns={2}".format(tag, p["start"][:16], p["turns"]))

    # --- 4. moves ----------------------------------------------------------
    tdir_rl = os.path.join(SESSIONS, "test data", "rl")
    tdir_bl = os.path.join(SESSIONS, "test data", "baseline")
    xdir_rl = os.path.join(SESSIONS, "rl_excluded")
    xdir_bl = os.path.join(SESSIONS, "baseline_excluded")
    adir_bl = os.path.join(SESSIONS, "baseline_aggregates")

    for name, _pid in rl_test:
        move(os.path.join(RL, name), os.path.join(tdir_rl, name), actions)
    for name, _pid in bl_test:
        move(os.path.join(BASE, name), os.path.join(tdir_bl, name), actions)
    for name, _reason, _pid in rl_excl:
        move(os.path.join(RL, name), os.path.join(xdir_rl, name), actions)
    for name, _reason, _pid in bl_excl:
        move(os.path.join(BASE, name), os.path.join(xdir_bl, name), actions)
    for name in bl_agg:
        move(os.path.join(BASE, name), os.path.join(adir_bl, name), actions)

    print("\n[4] moves: {0} test(rl) + {1} test(baseline) + {2} excl(rl) + "
          "{3} excl(baseline) + {4} aggregates".format(
              len(rl_test), len(bl_test), len(rl_excl), len(bl_excl), len(bl_agg)))

    # --- 5. renames + additive meta patch ---------------------------------
    for p in rl_plan:
        move(os.path.join(RL, p["old"]), os.path.join(RL, p["new"]), actions)
    for p in bl_plan:
        move(os.path.join(BASE, p["old"]), os.path.join(BASE, p["new"]), actions)

    if APPLY:
        for arm_dir, plan in ((RL, rl_plan), (BASE, bl_plan)):
            for p in plan:
                mp = os.path.join(arm_dir, p["new"], "meta.json")
                meta = read_json(mp)
                if meta is None:
                    continue
                meta["participant_number"] = p["number"]
                meta["session_index"] = p["session_index"]
                meta["agent_version"] = p["agent_version"]
                with open(mp, "w", encoding="utf-8") as fh:
                    json.dump(meta, fh, indent=2, ensure_ascii=False)
    print("[5] renamed {0} RL + {1} baseline keepers; meta.json patched additively "
          "(participant_number, session_index, agent_version)".format(len(rl_plan), len(bl_plan)))

    # --- 6. manifests ------------------------------------------------------
    def write_csv(path, rows, header):
        if not APPLY:
            return
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    hdr = ["participant_number", "session_index", "original_participant_id", "session_id",
           "folder", "original_folder", "started_at_local", "turns", "exhibits_covered",
           "agent_version", "notes"]
    write_csv(os.path.join(RL, "participants.csv"),
              [[p["number"], p["session_index"], p["old_id"], p["session_id"], p["new"],
                p["old"], p["start"], p["turns"], p["exhibits"], p["agent_version"], p["notes"]]
               for p in rl_plan], hdr)
    write_csv(os.path.join(BASE, "participants.csv"),
              [[p["number"], p["session_index"], p["old_id"], p["session_id"], p["new"],
                p["old"], p["start"], p["turns"], p["exhibits"], p["agent_version"], p["notes"]]
               for p in bl_plan], hdr)
    xhdr = ["folder", "reason", "original_participant_id"]
    write_csv(os.path.join(xdir_rl, "excluded_manifest.csv"),
              [[n, r, p] for n, r, p in rl_excl], xhdr)
    write_csv(os.path.join(xdir_bl, "excluded_manifest.csv"),
              [[n, r, p] for n, r, p in bl_excl], xhdr)
    print("[6] manifests written (participants.csv x2, excluded_manifest.csv x2)")

    # --- 7. verify ---------------------------------------------------------
    bytes_after = dir_bytes(SESSIONS)
    print("\n" + "=" * 78)
    if APPLY:
        rl_now = sorted(d for d in os.listdir(RL) if os.path.isdir(os.path.join(RL, d)))
        bl_now = sorted(d for d in os.listdir(BASE) if os.path.isdir(os.path.join(BASE, d)))
        print("after:  rl={0} folders, baseline={1} folders, {2:.2f} GB total".format(
            len(rl_now), len(bl_now), bytes_after / 1e9))
        print("bytes before == after: {0}  ({1} vs {2})".format(
            bytes_before == bytes_after, bytes_before, bytes_after))
        nums = sorted(p["number"] for p in rl_plan)
        print("RL numbers contiguous 21..35: {0}".format(nums == list(range(21, 36))))
        bnums = sorted(set(p["number"] for p in bl_plan))
        print("baseline numbers 1..20 complete: {0}".format(bnums == list(range(1, 21))))
    else:
        print("DRY RUN - nothing was changed. {0} actions queued.".format(len(actions)))
        print("Re-run with --apply to execute.")
    print("=" * 78)


if __name__ == "__main__":
    main()
