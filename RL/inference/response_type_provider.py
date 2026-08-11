from __future__ import annotations

from typing import List, Optional


RESPONSE_TYPE_LABELS = [
    "acknowledgment",
    "follow_up_question",
    "question",
    "statement",
    "confusion",
    "silence",
]

QUESTION_STARTERS = (
    "what",
    "why",
    "how",
    "where",
    "who",
    "when",
    "which",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "will",
)

CONFUSION_PHRASES = (
    "i don't understand",
    "i do not understand",
    "what do you mean",
    "i'm confused",
    "im confused",
    "confused",
    "unclear",
    "huh",
    "sorry?",
    "sorry",
    "can you repeat",
    "say that again",
    "i can't hear",
    "i cannot hear",
    "can't hear",
    "cannot hear",
    "that doesn't make sense",
    "that does not make sense",
    "stop asking",
    "just tell me",
    "don't ask me",
    "do not ask me",
    "answer me",
)

FOLLOW_UP_PHRASES = (
    "tell me more",
    "explain more",
    "can you explain more",
    "what does that mean",
    "what about that",
    "what about the",
    "more about",
    "how so",
    "and then",
    "why is that",
    "why does",
    "how does",
    "why is it",
    "how is it",
    "why is this",
    "how is this",
)

ACKNOWLEDGMENT_PHRASES = (
    "ok",
    "okay",
    "i see",
    "got it",
    "right",
    "sure",
    "makes sense",
    "interesting",
    "nice",
    "thanks",
    "thank you",
    "good",
    "cool",
    "ah",
    "alright",
)

SHORT_FRAGMENT_ACTIONS = {
    "AskClarification",
    "AskOpinion",
    "AskMemory",
}


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _is_question(text: str) -> bool:
    if not text:
        return False
    if "?" in text:
        return True
    return text.startswith(QUESTION_STARTERS)


def _history_to_text(history: List[str]) -> str:
    return " ".join(_normalize(item) for item in history[-4:] if item)


def predict_response_type(
    user_utterance: str,
    last_agent_reply: str,
    last_action: Optional[str],
    history: List[str],
    is_silence_event: bool = False,
) -> str:
    if is_silence_event:
        return "silence"

    text = _normalize(user_utterance)
    last_reply = _normalize(last_agent_reply)
    history_text = _history_to_text(history)
    action = (last_action or "").strip()

    if not text:
        return "statement"

    if any(phrase in text for phrase in CONFUSION_PHRASES):
        return "confusion"

    if text in {"what", "why", "how", "where"}:
        return "confusion"

    is_question = _is_question(text)
    follow_up_context = bool(last_reply) or any(tag.startswith("agent:") for tag in history[-4:])
    follow_up_signal = any(phrase in text for phrase in FOLLOW_UP_PHRASES)
    follow_up_signal = follow_up_signal or (
        is_question and text.startswith(("why", "how", "what about", "what does", "and "))
    )
    referential_follow_up = any(token in text for token in (" that", " this", " it ", " more", " again"))
    if is_question and follow_up_context and (follow_up_signal or referential_follow_up):
        return "follow_up_question"

    if is_question:
        return "question"

    if any(text == phrase or text.startswith(f"{phrase} ") for phrase in ACKNOWLEDGMENT_PHRASES):
        return "acknowledgment"

    token_count = len(text.split())
    if action in SHORT_FRAGMENT_ACTIONS and token_count <= 4 and "?" not in text:
        return "statement"

    if any(phrase in history_text for phrase in ("what do you mean", "i don't understand")) and token_count <= 3:
        return "acknowledgment"

    return "statement"
