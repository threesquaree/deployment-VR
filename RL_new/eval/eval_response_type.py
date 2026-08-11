"""Per-class scoring for the response-type classifier.

Reads a JSONL of turns that have been hand-labelled with a "gold" field and
reports precision/recall/F1 per label plus a confusion matrix. Rows without a
"gold" key are skipped, so you can label a sample of a real session log in place
and re-run this as labelling progresses.

Accuracy is deliberately NOT the headline metric: the training-time visitor was
~75% acknowledgment on early-exhibit turns, so a majority-class predictor scores
well while carrying no signal. The gate below is per-class instead, on the three
labels whose errors actually change agent behaviour:

  disengaged precision      - a false positive misrepresents an engaged visitor
                              in the only channel that carries disengagement
  confusion recall          - drives the agent toward ClarifyFact
  clarification_request recall - same

Usage:
  ../RL/.venv/Scripts/python.exe eval/eval_response_type.py <labelled.jsonl>
  ../RL/.venv/Scripts/python.exe eval/eval_response_type.py <labelled.jsonl> --pred-field response_type

Exit code is 1 if any critical threshold is missed, so this can gate a release.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# All nine labels: the eight in the state one-hot plus repeat_request, which is
# a real training reward-table label that collapses to "statement" in the state.
ALL_LABELS = [
    "acknowledgment",
    "follow_up_question",
    "question",
    "statement",
    "confusion",
    "silence",
    "clarification_request",
    "disengaged",
    "repeat_request",
]

CRITICAL_THRESHOLDS = {
    ("disengaged", "precision"): 0.7,
    ("confusion", "recall"): 0.7,
    ("clarification_request", "recall"): 0.7,
}


def load_rows(path: Path, pred_field: str) -> List[Tuple[str, str]]:
    pairs = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                print("skipping unparseable line {0}".format(line_no), file=sys.stderr)
                continue
            gold = str(row.get("gold") or "").strip()
            if not gold:
                continue
            pred = row.get(pred_field)
            if pred is None:
                # Fall back to the nested debug block written by the runtime.
                pred = (row.get("debug") or {}).get(pred_field)
            pairs.append((gold, str(pred or "").strip()))
    return pairs


def confusion_matrix(pairs: List[Tuple[str, str]], labels: List[str]) -> Dict[str, Dict[str, int]]:
    matrix = {g: {p: 0 for p in labels} for g in labels}
    for gold, pred in pairs:
        if gold not in matrix:
            matrix[gold] = {p: 0 for p in labels}
        if pred not in matrix[gold]:
            matrix[gold][pred] = 0
        matrix[gold][pred] += 1
    return matrix


def per_label_scores(pairs: List[Tuple[str, str]], labels: List[str]) -> Dict[str, Dict[str, float]]:
    scores = {}
    for label in labels:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / support if support else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        scores[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "predicted": tp + fp,
        }
    return scores


def format_report(pairs, scores, matrix, labels) -> str:
    lines = []
    total = len(pairs)
    correct = sum(1 for g, p in pairs if g == p)
    lines.append("labelled turns: {0}".format(total))
    lines.append("overall accuracy: {0:.3f}  (reference only - see module docstring)".format(
        correct / total if total else 0.0))

    present = [l for l in labels if scores[l]["support"] or scores[l]["predicted"]]
    macro = [scores[l]["f1"] for l in present if scores[l]["support"]]
    lines.append("macro F1 over labels with support: {0:.3f}".format(
        sum(macro) / len(macro) if macro else 0.0))
    lines.append("")
    lines.append("{0:<24}{1:>10}{2:>9}{3:>9}{4:>9}{5:>10}".format(
        "label", "precision", "recall", "f1", "support", "predicted"))
    for label in labels:
        s = scores[label]
        if not (s["support"] or s["predicted"]):
            continue
        lines.append("{0:<24}{1:>10.3f}{2:>9.3f}{3:>9.3f}{4:>9d}{5:>10d}".format(
            label, s["precision"], s["recall"], s["f1"], s["support"], s["predicted"]))

    lines.append("")
    lines.append("confusion matrix (rows = gold, cols = predicted)")
    header = "{0:<24}".format("") + "".join("{0:>6}".format(l[:5]) for l in present)
    lines.append(header)
    for gold in present:
        row = "{0:<24}".format(gold[:23])
        row += "".join("{0:>6d}".format(matrix.get(gold, {}).get(p, 0)) for p in present)
        lines.append(row)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="JSONL with a 'gold' field on labelled rows")
    parser.add_argument("--pred-field", default="response_type",
                        help="field holding the predicted label (default: response_type)")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print("no such file: {0}".format(path), file=sys.stderr)
        return 2

    pairs = load_rows(path, args.pred_field)
    if not pairs:
        print("no rows with a 'gold' field - nothing to score", file=sys.stderr)
        return 2

    scores = per_label_scores(pairs, ALL_LABELS)
    matrix = confusion_matrix(pairs, ALL_LABELS)
    print(format_report(pairs, scores, matrix, ALL_LABELS))

    print("")
    failed = []
    for (label, metric), threshold in sorted(CRITICAL_THRESHOLDS.items()):
        value = scores[label][metric]
        support = scores[label]["support"]
        predicted = scores[label]["predicted"]
        if not support:
            print("SKIP  {0} {1}: no gold examples in this sample".format(label, metric))
            continue
        if metric == "precision" and not predicted:
            # Precision is undefined with zero predictions. Say so rather than
            # reporting 0.000, but still fail: a label the classifier never emits
            # is exactly the failure mode this gate exists to catch.
            failed.append((label, metric, value, threshold))
            print("FAIL  {0} {1}: undefined - classifier never predicted this label "
                  "({2} gold examples missed)".format(label, metric, support))
            continue
        status = "OK  " if value >= threshold else "FAIL"
        if value < threshold:
            failed.append((label, metric, value, threshold))
        print("{0}  {1} {2}: {3:.3f} (threshold {4:.2f}, support {5})".format(
            status, label, metric, value, threshold, support))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
