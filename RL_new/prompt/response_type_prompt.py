"""Prompt for the response-type speech classifier.

Label definitions are the deployment-side restatement of the training
simulator's semantics (rl-agent-thesis src/simulator/sim8_adapter.py,
_determine_response_type_contextual). Two of the distinctions are only
decidable with the previous agent turn in view, so it is always included:

  follow_up_question vs question       - is the question about what was JUST said?
  clarification_request vs repeat_request - didn't understand vs didn't hear

Keep this prompt frozen for the duration of a study arm: it is part of the
measurement instrument, and editing it mid-study splits the condition.

Revision history (pre-study only; frozen from the first participant onward):
  2026-08-05 - farewells excluded from `disengaged`. Pilot sessions showed
    "thank you very much ... bye bye" scored as disengaged, which trips mask
    rule 7 and forces Engage/RecoverEngagement at a visitor who is leaving
    satisfied (observed twice in one session, back to back). Training's
    `disengaged` meant lecture fatigue MID-tour, never session end.
"""

from __future__ import annotations


_TEMPLATE = """Classify the museum visitor's spoken reply into exactly one response type.

The tour-guide agent just said (action: {action}):
"{agent_utterance}"

The visitor replied:
"{transcript}"

Labels:
- acknowledgment: backchannel or brief agreement, adding nothing new ("mm-hm", "oh interesting", "I see", "yeah")
- follow_up_question: a question probing the content the guide JUST delivered, including elaboration requests ("tell me more about that", "why does that matter?")
- question: a question NOT about the just-delivered content - a new topic, another exhibit, or logistics
- statement: a substantive observation, opinion, or answer that goes beyond a backchannel ("he looks proud", "it reminds me of Roman art")
- confusion: the visitor is lost, or reacts to the guide being off-topic or non-responsive ("huh?", "what does that have to do with it?")
- clarification_request: the visitor heard the fact but wants it explained differently ("what do you mean by lost-wax casting?")
- repeat_request: the visitor missed what was said and wants it again ("sorry, can you say that again?")
- disengaged: the visitor says outright that they have lost interest in the tour while it is still going, or wants the guide to stop what it is doing ("I'm getting bored", "this isn't interesting", "stop telling me about the painting", "I'm done with this conversation")

Notes:
- The transcript comes from speech recognition and may contain errors or missing punctuation. Judge the visitor's intent, not the spelling, and do not require a question mark to call something a question.
- A polite opener such as "sorry" or "excuse me" carries no meaning by itself. Classify what follows it. "Sorry, who is this?" is a question about the exhibit, not confusion and not a repeat request; only treat it as repeat_request if the visitor actually asks for something to be said again.
- Use disengaged ONLY for an explicit statement of lost interest or wanting the guide to stop. A short or flat reply is not enough on its own: "ok", "mm-hm", "yeah" are acknowledgment, and a quiet observation is a statement. If you are unsure between disengaged and anything else, do not choose disengaged.
- A FAREWELL IS NOT DISENGAGEMENT. A visitor who is leaving satisfied - "thank you, that was great, bye", "I'm off now", "goodbye", "thanks for everything" - is acknowledgment, even if they also say they are done or leaving. Reserve disengaged for dissatisfaction or boredom with the tour itself. Thanks and praise are never disengaged.

Reply with exactly one label from the list and nothing else."""


def build_response_type_prompt(ctx) -> str:
    """ctx is an inference.response_type_classifier.ClassificationContext."""
    agent_utterance = (getattr(ctx, "last_agent_reply", "") or "").strip()
    if not agent_utterance:
        agent_utterance = "(nothing yet - this is the visitor's opening turn)"
    action = (getattr(ctx, "last_action", "") or "").strip() or "none"
    transcript = (getattr(ctx, "user_utterance", "") or "").strip()
    return _TEMPLATE.format(
        action=action,
        agent_utterance=agent_utterance,
        transcript=transcript,
    )
