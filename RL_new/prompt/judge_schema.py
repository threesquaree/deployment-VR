"""
Parser and validator for judge JSON output.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple


def _extract_json_object(text: str) -> str:
    s = (text or "").strip()
    if not s:
        raise ValueError("empty judge output")
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    return s[start : end + 1]


def _score_to_int(value, key: str) -> int:
    try:
        v = int(value)
    except Exception as exc:
        raise ValueError(f"{key} is not int-like") from exc
    if v not in (0, 1, 2):
        raise ValueError(f"{key} must be 0|1|2")
    return v


def _normalize_realized_fact_ids(value, selected_fact_ids: Optional[List[str]]) -> List[str]:
    allowed = []
    seen = set()
    for item in selected_fact_ids or []:
        text = str(item).strip()
        if text and text not in seen:
            allowed.append(text)
            seen.add(text)
    allowed_set = set(allowed)
    if value is None:
        return []
    if isinstance(value, str):
        candidate_ids = re.findall(r"[A-Z]{2}_\d{3}", value)
    elif isinstance(value, list):
        candidate_ids = [str(item).strip() for item in value]
    else:
        raise ValueError("realized_fact_ids must be a list or string")
    realized = []
    realized_seen = set()
    for item in candidate_ids:
        if item in allowed_set and item not in realized_seen:
            realized.append(item)
            realized_seen.add(item)
    return realized


def parse_and_validate_judge_output(raw_text: str, selected_fact_ids: Optional[List[str]] = None) -> Dict[str, object]:
    obj = json.loads(_extract_json_object(raw_text))

    # Backward compatibility for earlier naming.
    if "language_consistency" not in obj and "context_consistency" in obj:
        obj["language_consistency"] = obj.get("context_consistency")
    if "gaze_grounding" not in obj and "state_grounding" in obj:
        obj["gaze_grounding"] = obj.get("state_grounding")

    action_alignment = _score_to_int(obj.get("action_alignment"), "action_alignment")
    language_consistency = _score_to_int(obj.get("language_consistency"), "language_consistency")
    gaze_grounding = _score_to_int(obj.get("gaze_grounding"), "gaze_grounding")
    realized_fact_ids = _normalize_realized_fact_ids(obj.get("realized_fact_ids"), selected_fact_ids)

    decision = str(obj.get("decision", "")).strip().lower()
    if decision not in ("pass", "revise"):
        # Derive by rule if model did not follow the schema strictly.
        decision = "revise" if (action_alignment == 0 or language_consistency == 0) else "pass"

    # Enforce rule server-side as source of truth.
    decision = "revise" if (action_alignment == 0 or language_consistency == 0) else "pass"

    reason = str(obj.get("reason", "")).strip() or "Scored by verifier."
    revision_instruction = str(obj.get("revision_instruction", "")).strip() or "Improve action and language alignment."

    return {
        "decision": decision,
        "action_alignment": action_alignment,
        "language_consistency": language_consistency,
        "gaze_grounding": gaze_grounding,
        "realized_fact_ids": realized_fact_ids,
        "reason": reason,
        "revision_instruction": revision_instruction,
    }


def build_fallback_judge_result(policy: str, error: str) -> Tuple[Dict[str, object], bool]:
    p = str(policy or "pass").strip().lower()
    decision = "revise" if p == "revise" else "pass"
    result = {
        "decision": decision,
        "action_alignment": 1,
        "language_consistency": 1,
        "gaze_grounding": 1,
        "realized_fact_ids": [],
        "reason": f"Judge parse failure: {error}",
        "revision_instruction": "Keep response concise and aligned with action/context.",
    }
    return result, False
