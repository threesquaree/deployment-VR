"""
Prompt builder for AskOpinion.
"""

from __future__ import annotations

from typing import Optional

from prompt.base_prompt import SILENCE_NO_PARAPHRASE, SILENCE_OPENER


def build_ask_opinion_prompt(
    *,
    ex_id: Optional[str],
    context_section: str,
    current_completion: float = 0.0,
    is_silence: bool = False,
) -> str:
    # The silence rule table routes here whenever the previous turn was an Explain, so
    # this is the single most common way the agent speaks with no visitor input at all.
    opener = (
        f"{SILENCE_OPENER} {SILENCE_NO_PARAPHRASE}"
        if is_silence
        else "First, respond naturally to the user's current input without quoting them verbatim."
    )
    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

AskOpinion policy:
1. {opener}
2. Then ask exactly one opinion question.
3. The question must include at least one keyword from the current exhibit or current AOI.
4. The question must be opinion/feeling-oriented.
5. Do not introduce new facts.
6. Do not include any [FACT_ID].
7. Maximum two sentences.

Response:"""

