"""
Prompt builder for one-shot revision after judge decision.
"""

from __future__ import annotations


def build_revise_prompt(
    *,
    option: str,
    subaction: str,
    action_description: str,
    original_prompt: str,
    draft_response: str,
    revision_instruction: str,
) -> str:
    return f"""You are revising one candidate reply for a museum dialogue system.

RL action must stay the same:
- Option: {option}
- Subaction: {subaction}
- Action description: {action_description}

Revision instruction:
{revision_instruction}

Original generation prompt:
{original_prompt}

Draft response to revise:
{draft_response}

Rules:
1) Keep the same action intent; do not change the action.
2) Follow the original constraints, especially maximum two sentences.
3) Improve coherence and context grounding.
4) If applicable, keep any required FACT_ID behavior from the original prompt.
5) Output only the revised final response text (no JSON, no explanation)."""

