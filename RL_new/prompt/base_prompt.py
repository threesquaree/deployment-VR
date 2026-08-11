"""
Shared RL base prompt template.
"""

# --- silence-turn prompt fragments -------------------------------------------------
# A silence-triggered turn renders [User Input] empty: the visitor said nothing. Every
# action policy that opens with "answer the user's question" then has no referent, and
# the most salient text left in the context block is the agent's OWN previous reply --
# so the model fills the mandatory first sentence by paraphrasing it and the visitor
# hears the same point twice. These fragments replace the opener on silence turns.
#
# Applied ONLY when is_silence is True. The user-input wording is left byte-identical
# so sessions already collected under it stay comparable.

SILENCE_OPENER = (
    "The visitor has gone quiet and has NOT asked anything. Do not answer, acknowledge, "
    "or invent a question."
)

SILENCE_NO_PARAPHRASE = (
    "Do not restate, summarise, or paraphrase your previous reply -- open with a brief, "
    "fresh invitation instead."
)


def render_base_prompt(
    action_label: str,
    action_description: str,
    last_obj_like: object,
    last_aoi_like: object,
    image_like: object,
    last_agent_like: object,
    history_like: object,
    graph_data_like: object,
    user_input: str,
    exhibit_facts_like: str = "",
) -> str:
    # HANDOFF.md NLG checklist (b): the current exhibit's un-mentioned facts must
    # reach the prompt on every turn. Explain turns carry them via the fact
    # selector; non-Explain turns supply this line instead. Empty -> omitted, so
    # prompts without it stay byte-identical to previously collected sessions.
    exhibit_facts_line = f"\n{exhibit_facts_like}" if exhibit_facts_like else ""
    return f"""[System Role]
You are an AI assistant serving as a virtual museum guide for a VR exhibition of five unique paintings.

[RL Guidance]
Selected action: {action_label}
Action Description: {action_description}
Use this action as guidance for this turn's reply.
Do not mention the action explicitly.

[Current Context]
The main room has five paintings across two walls.
Currently, the user is viewing: ({last_obj_like}).
Focus area: {last_aoi_like}.
Image: {image_like}.
Prior agent response: {last_agent_like}.
Conversation history: {history_like}.
Exhibit Data: {graph_data_like}.{exhibit_facts_line}

[User Input]
{user_input}

[Response Constraints]
No links or emojis.
No speculation.
Avoid repetition.
Maximum two sentences."""

