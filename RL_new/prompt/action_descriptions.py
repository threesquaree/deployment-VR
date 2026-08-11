"""
Action description registry for RL prompt guidance.

Covers the deadend_fix_v1 action space:
Explain: ExplainNewFact, ClarifyFact
AskQuestion: AskOpinion
OfferTransition: SummarizeAndSuggest
Conclude: WrapUp
Engage: RecoverEngagement
(Legacy subactions from earlier checkpoints are kept for compatibility.)
"""

from typing import Dict


ACTION_DESCRIPTIONS: Dict[str, str] = {
    "ExplainNewFact": "Explain: ExplainNewFact",
    "RepeatFact": "Explain: RepeatFact",
    "ClarifyFact": "Explain: ClarifyFact",
    "AskOpinion": "AskQuestion: AskOpinion",
    "AskMemory": "AskQuestion: AskMemory",
    "AskClarification": "AskQuestion: AskClarification",
    "SummarizeAndSuggest": "OfferTransition: SummarizeAndSuggest",
    "WrapUp": "Conclude: WrapUp",
    "RecoverEngagement": (
        "Engage: RecoverEngagement — the visitor's attention is fading; "
        "re-engage them with one light, open opinion question about something "
        "already shown at this exhibit, without introducing new facts"
    ),
}


def get_action_description(subaction: str) -> str:
    sub = (subaction or "").strip()
    if not sub:
        return ""
    return ACTION_DESCRIPTIONS.get(sub, sub)
