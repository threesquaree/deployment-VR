"""
Prompt builder for OfferTransition/SummarizeAndSuggest strategy.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from prompt.base_prompt import SILENCE_NO_PARAPHRASE, SILENCE_OPENER


def build_summarize_and_suggest_prompt(
    *,
    current_exhibit: Optional[str],
    target_exhibit: Optional[str],
    context_section: str,
    is_silence: bool = False,
) -> Tuple[str, Dict[str, object]]:
    current_name = (current_exhibit or "current exhibit").replace("_", " ")
    # Silence rule 5 (exhibit exhausted) routes here with no visitor utterance, so
    # sentence 1 must not promise to answer a question that was never asked. The
    # summary in sentence 2 is deliberately left alone -- recapping covered ground is
    # the point of this action, unlike the accidental echo the opener produced.
    lead = (
        f"Sentence 1: {SILENCE_OPENER} {SILENCE_NO_PARAPHRASE}"
        if is_silence
        else None
    )

    if target_exhibit:
        target_name = target_exhibit.replace("_", " ")
        prompt = f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {current_name}
---

{context_section}

SummarizeAndSuggest policy:
1. Keep exactly two sentences.
2. {lead if is_silence else "Sentence 1: answer user's question directly "}
3. Sentence 2: briefly summarize what has been discussed so far, then suggest moving to "{target_name}" and name it explicitly.
4. This is only a suggestion; do not imply the visitor already moved.
5. Do not introduce new facts about the target exhibit.
6. Do not include any [FACT_ID].

Response:"""
        meta = {
            "transition_target": target_exhibit,
            "transition_has_target": 1,
            "transition_mode": "summarize_and_suggest",
        }
        return prompt, meta

    prompt = f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {current_name}
---

{context_section}

SummarizeAndSuggest policy:
1. Keep exactly two sentences.
2. {lead if is_silence else "Sentence 1: answer user's question"}
3. Sentence 2: briefly summarize what has been discussed so far then provide a neutral suggestion to choose any other exhibit.
4. This is only a suggestion; do not imply the visitor already moved.
5. Do not include any [FACT_ID].

Response:"""
    meta = {
        "transition_target": None,
        "transition_has_target": 0,
        "transition_mode": "fallback",
    }
    return prompt, meta
