"""
Prompt builder for response verification (judge).
"""

from __future__ import annotations

from typing import List, Optional


def build_judge_prompt(
    *,
    option: str,
    subaction: str,
    action_description: str,
    current_exhibit: Optional[str],
    current_aoi: Optional[str],
    user_input: str,
    conversation_history: object,
    candidate_response: str,
    selected_fact_ids: Optional[List[str]] = None,
) -> str:
    selected_fact_ids = [str(x).strip() for x in (selected_fact_ids or []) if str(x).strip()]
    is_fact_bearing = subaction in {"ExplainNewFact", "RepeatFact"}
    return f"""You are a verifier for a dialogue system.

Evaluate the candidate response on three separate dimensions.

A) action_alignment (RL action adherence)
- 2: Clearly follows the selected RL action intent.
- 1: Partially reflects the RL action.
- 0: Ignores or contradicts the RL action.

B) language_consistency (dialogue coherence)
- 2: Natural, clear, and appropriate for the dialogue context.
- 1: Generally acceptable, but somewhat stiff or slightly unnatural.
- 0: Unnatural or hard to understand, with clear grammar/fluency issues or clearly inappropriate tone.

C) gaze_grounding (state grounding to object/AOI/gaze)
- 2: Clearly grounded in current viewed object/AOI/gaze state.
- 1: Weak or implicit grounding; not clearly incorrect.
- 0: Conflicts with current gaze/object/AOI state.

Decision rule:
- Return "revise" only if action_alignment == 0 OR language_consistency == 0.
- Otherwise return "pass".

Fact realization rule:
- Fact-bearing actions are only: ExplainNewFact and RepeatFact.
- For fact-bearing actions, decide which selected facts are clearly realized in the candidate response.
- selected_fact_ids are the only candidate fact ids for realization.
- realized_fact_ids must be a subset of selected_fact_ids.
- If none of the selected facts is clearly expressed, return an empty list.
- For all non-fact-bearing actions, return realized_fact_ids as [].

Runtime context:
- RL option: {option}
- RL subaction: {subaction}
- Action description: {action_description}
- Is fact-bearing action: {is_fact_bearing}
- selected_fact_ids: {selected_fact_ids}
- Current exhibit: {current_exhibit}
- Current AOI: {current_aoi}
- User input: {user_input}
- Recent conversation history: {conversation_history}

Candidate response:
{candidate_response}

Return JSON only:
{{
  "decision": "pass" or "revise",
  "action_alignment": 0|1|2,
  "language_consistency": 0|1|2,
  "gaze_grounding": 0|1|2,
  "realized_fact_ids": ["FACT_ID", "..."],
  "reason": "one short sentence",
  "revision_instruction": "one short sentence"
}}"""
