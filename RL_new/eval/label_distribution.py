"""Marginal label distribution of a response-type classifier over historical data.

This is the training/deployment distribution check. In training the visitor
simulator's baseline was ~75% `acknowledgment` on early-exhibit turns; the
deployed lexical rules emit it ~2% of the time on real visitor speech, with
three labels never firing at all. The response-type block is 8 of the 158 state
dimensions, so that gap is a distribution shift in a channel the policy was
trained to read.

No gold labels are needed - this only reports what each classifier produces.

Usage:
  ../RL/.venv/Scripts/python.exe eval/label_distribution.py --classifier rules_v1
  ../RL/.venv/Scripts/python.exe eval/label_distribution.py --classifier hybrid_v1 --limit 100

hybrid_v1 makes one LLM call per utterance, so use --limit when sampling it.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from inference.response_type_classifier import (  # noqa: E402
    ClassificationContext,
    build_classifier,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Field names differ by source - turns.jsonl uses user_text, the CA logs do not.
SOURCES: List[Tuple[str, str, str]] = [
    ("data/sessions/baseline/*/turns.jsonl", "jsonl", "user_text"),
    ("data/sessions/rl/*/turns.jsonl", "jsonl", "user_text"),
    ("data/Baseline_data/*/turns.jsonl", "jsonl", "user_text"),
    ("data/RL_data/*/turns.jsonl", "jsonl", "user_text"),
    ("data/test/*/turns.jsonl", "jsonl", "user_text"),
    ("data/false_in_user_study/*/turns.jsonl", "jsonl", "user_text"),
    ("RL/logs/sessions/*.jsonl", "jsonl", "user_text"),
    ("CA/improved/logs/*.jsonl", "jsonl", "text"),
    ("CA/original/logs/*.csv", "csv", "Response"),
]


def _iter_jsonl(path: Path, field: str) -> Iterator[Dict[str, str]]:
    prev_agent = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            text = str(row.get(field) or "").strip()
            if text:
                yield {"user_text": text, "prev_agent_text": prev_agent}
            reply = str(row.get("reply_text") or "").strip()
            if reply:
                prev_agent = reply


def _iter_csv(path: Path, field: str) -> Iterator[Dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            text = str(row.get(field) or "").strip()
            if text:
                yield {"user_text": text, "prev_agent_text": ""}


def load_pool(limit: Optional[int] = None, seed: int = 20260728) -> List[Dict[str, str]]:
    """Deduplicated visitor utterances with their preceding agent turn."""
    seen = set()
    pool: List[Dict[str, str]] = []
    for pattern, kind, field in SOURCES:
        for path in sorted(REPO_ROOT.glob(pattern)):
            reader = _iter_jsonl if kind == "jsonl" else _iter_csv
            for item in reader(path, field):
                key = " ".join(item["user_text"].lower().split())
                if not key or key in seen:
                    continue
                seen.add(key)
                item["source_file"] = str(path.relative_to(REPO_ROOT))
                pool.append(item)
    if limit and len(pool) > limit:
        # default_rng, never np.random.* - state_builder.get_projection_matrix
        # reseeds the global numpy RNG, so global-RNG sampling would silently
        # depend on call ordering.
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(pool), size=limit, replace=False)
        pool = [pool[i] for i in sorted(idx)]
    return pool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--classifier", default="rules_v1", help="rules_v1 | hybrid_v1")
    parser.add_argument("--limit", type=int, default=None,
                        help="sample this many utterances (use for hybrid_v1 - it calls an LLM per turn)")
    parser.add_argument("--config", default=str(REPO_ROOT / "RL_new" / "runtime_config.json"))
    parser.add_argument("--dump", default=None, help="optional JSONL of per-utterance predictions")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8-sig") as handle:
        config = json.load(handle)

    classifier = build_classifier(args.classifier, config)
    pool = load_pool(limit=args.limit)
    print("classifier: {0}".format(args.classifier))
    print("utterances: {0}".format(len(pool)))

    counts = Counter()
    sources = Counter()
    dump_handle = open(args.dump, "w", encoding="utf-8") if args.dump else None
    try:
        for item in pool:
            ctx = ClassificationContext(
                user_utterance=item["user_text"],
                last_agent_reply=item.get("prev_agent_text", ""),
                last_action=None,
                history=(["agent: " + item["prev_agent_text"]] if item.get("prev_agent_text") else []),
            )
            result = classifier.classify(ctx)
            counts[result.label] += 1
            sources[result.source] += 1
            if dump_handle:
                dump_handle.write(json.dumps({
                    "user_text": item["user_text"],
                    "prev_agent_text": item.get("prev_agent_text", ""),
                    "source_file": item.get("source_file"),
                    "response_type": result.label,
                    "response_type_source": result.source,
                    "response_type_rules_v1": result.rules_v1_label,
                }, ensure_ascii=False) + "\n")
    finally:
        if dump_handle:
            dump_handle.close()

    total = sum(counts.values()) or 1
    print("")
    print("{0:<24}{1:>8}{2:>9}".format("label", "count", "share"))
    for label, count in counts.most_common():
        print("{0:<24}{1:>8d}{2:>8.1f}%".format(label, count, 100.0 * count / total))

    print("")
    print("provenance:")
    for source, count in sources.most_common():
        print("  {0:<22}{1:>8d}".format(source, count))

    print("")
    print("training reference: the simulator's visitor was ~75% acknowledgment on")
    print("early-exhibit turns. A large gap here is a state-distribution shift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
