"""31-d observation builder for deployment — the exact input `E_flat_S2` was trained on.

Replaces the stale `state_builder.py` (154-d, wrong layout, needs DialogueBERT at runtime).
The study agent was trained with `--drop-bert`: no transformer anywhere in this vector.
Every dimension is a counter, a flag or a one-hot the VR pipeline already has.

Layout (must match env._get_obs() exactly; asserted by tests/test_state_builder_31d.py):

  [0:6]    focus one-hot          exhibit index (focus-1), or slot 5 when no focus
  [6:11]   coverage ratios        facts delivered / facts total, per exhibit
  [11:17]  subaction usage        actions_used[sa] / max(total_actions, 1), in
                                  [ExplainNewFact, ClarifyFact, AskOpinion,
                                   SummarizeAndSuggest, WrapUp, RecoverEngagement]
  [17:21]  availability flags     ExplainNewFact legal, AskOpinion legal,
                                  RecoverEngagement legal, current exhibit exhausted
  [21:29]  response-type one-hot  dialogue_masks.RESPONSE_TYPE_LABELS order;
                                  `disengaged` at index 28
  [29:31]  dwell trajectory       [2*dwell - 1, delta_dwell]

The response type MUST be validated at the classifier boundary
(dialogue_masks.validate_response_type) BEFORE reaching this builder; the builder itself
mirrors the env's silent statement-fallback so that parity with training holds bit-for-bit.
"""
from typing import Dict
import numpy as np

from dialogue_masks import (WorldState, available_subactions, RESPONSE_TYPE_LABELS)

SUBACTION_ORDER = ["ExplainNewFact", "ClarifyFact", "AskOpinion",
                   "SummarizeAndSuggest", "WrapUp", "RecoverEngagement"]
STATE_DIM = 31


def build_observation(ws: WorldState,
                      actions_used: Dict[str, int],
                      dwell: float,
                      last_delta_dwell: float) -> np.ndarray:
    """Mirror of env._get_obs() under the study agent's flags
    (drop_bert=1, response_type_feature=1, drop_dwell=0, engagement_gate=0)."""
    n_ex = len(ws.exhibit_keys)
    obs = np.zeros(STATE_DIM, dtype=np.float32)

    # focus one-hot
    if ws.focus > 0:
        obs[ws.focus - 1] = 1.0
    else:
        obs[n_ex] = 1.0

    # coverage ratios
    for i, ex in enumerate(ws.exhibit_keys):
        total = len(ws.exhibit_fact_ids.get(ex, ()))
        if total:
            obs[n_ex + 1 + i] = len(ws.facts_mentioned.get(ex, ())) / total

    # subaction usage, normalized by total actions so far
    total_actions = sum(actions_used.get(sa, 0) for sa in SUBACTION_ORDER) or 1
    for i, sa in enumerate(SUBACTION_ORDER):
        obs[11 + i] = actions_used.get(sa, 0) / total_actions

    # availability flags (env order: Explain sub, AskQuestion sub, Engage sub, exhausted)
    obs[17] = 1.0 if "ExplainNewFact" in available_subactions(ws, "Explain") else 0.0
    obs[18] = 1.0 if "AskOpinion" in available_subactions(ws, "AskQuestion") else 0.0
    obs[19] = 1.0 if "RecoverEngagement" in available_subactions(ws, "Engage") else 0.0
    obs[20] = 1.0 if ws.is_exhausted(ws.current_exhibit()) else 0.0

    # response-type one-hot (env falls back to "statement" for unknowns; validation
    # against unknowns belongs at the classifier boundary, not here)
    rt = ws.last_response_type if ws.last_response_type in RESPONSE_TYPE_LABELS else "statement"
    obs[21 + RESPONSE_TYPE_LABELS.index(rt)] = 1.0

    # dwell trajectory
    obs[29] = float(2.0 * dwell - 1.0)
    obs[30] = float(last_delta_dwell)
    return obs
