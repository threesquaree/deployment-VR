"""
Prompt builder for RecoverEngagement (Engage option).

Policy text ported verbatim from the training repo's
src/utils/dialogue_planner.py::build_recover_engagement_prompt
(rl-agent-thesis, branch w-edu-ablation-template) so the served behavior
matches what deadend_fix_v1 was trained against.
"""

from __future__ import annotations

from typing import Optional

from prompt.base_prompt import SILENCE_NO_PARAPHRASE


def build_recover_engagement_prompt(
    *,
    ex_id: Optional[str],
    context_section: str,
    current_completion: float = 0.0,
    is_silence: bool = False,
) -> str:
    # This policy is already written for a quiet visitor and never claims to answer a
    # question, so it needs no new opener. It does invite the visitor to react to
    # "something already shown", which is intended -- but on a silence turn that shades
    # easily into restating the previous reply, so only the anti-echo line is added.
    # Reachable from the RL policy on ordinary user turns too, hence the flag.
    no_echo = f"\n8. {SILENCE_NO_PARAPHRASE}" if is_silence else ""
    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

RecoverEngagement policy:
1. The visitor's attention is fading after a stretch of explanation. Do NOT introduce
   new facts or continue the main content.
2. Re-engage them by inviting THEIR perspective: ask exactly one light, open
   opinion/perspective question about something already shown at this exhibit
   (what stands out to them, how it makes them feel, what they find most striking,
   what they would be curious to understand about it).
3. The question must be answerable purely in words — it asks for the visitor's view.
4. You are a TEXT-ONLY guide and cannot perform actions. NEVER offer to show, display,
   play, demonstrate, arrange, or take the visitor anywhere (no "would you like to
   see / try / watch / walk / look at ..."). Only converse.
5. The question must include at least one keyword from the current exhibit or AOI.
6. Warm, conversational tone — two sentences maximum. Do not include any [FACT_ID].
7. Do not quote the visitor or repeat their words verbatim.{no_echo}

Response:"""
