"""
Dialogue Planner for HRL Museum Dialogue Agent

This module implements structured prompting for LLM-based dialogue generation in the
HRL museum agent. It translates high-level options and subactions into structured
prompts that guide LLM generation while maintaining dialogue coherence and policy
adherence.
"""

import re
from typing import List, Optional

LAST_EXPLAIN_NEWFACT_META = {}
LAST_REPEATFACT_META = {}
LAST_TRANSITION_META = {}


def build_prompt(option: str, subaction: str, ex_id: Optional[str],
                last_utt: str, facts_all: List[str], facts_used: List[str], 
                selected_fact: Optional[str], dialogue_history: List[str] = None,
                exhibit_names: List[str] = None, knowledge_graph=None,
                auxiliary_context: dict = None,
                target_exhibit: str = None, coverage_dict: dict = None,
                current_aoi: Optional[str] = None,
                rl_action_description: Optional[str] = None,
                conversation_history_rows: Optional[List[dict]] = None) -> str:
    """Build structured prompt for LLM dialogue generation"""
    
    # H6: Handle coarse option granularity by mapping coarse options to original option names
    # for prompt construction purposes
    if option == "Engage":
        # Map subaction to its original option for prompt routing
        from src.agent.option_configs import get_subaction_origin
        option = get_subaction_origin(subaction)
    elif option == "Transition":
        # H6 coarse_3opt: "Transition" option maps to "OfferTransition" for prompts
        option = "OfferTransition"
    
    # Build context - show facts ONLY for Explain option
    show_facts = (option == "Explain")
    action_label = subaction
    action_description = _resolve_action_description(option, subaction, rl_action_description)
    context_section = _build_enhanced_context_section(
        ex_id,
        last_utt,
        facts_all,
        facts_used,
        dialogue_history,
        exhibit_names,
        knowledge_graph,
        auxiliary_context=auxiliary_context,
        show_facts=show_facts,
        action_label=action_label,
        action_description=action_description,
        current_aoi=current_aoi,
        conversation_history_rows=conversation_history_rows,
    )

    # Calculate current exhibit completion for contextual prompts
    current_completion = 0.0
    if coverage_dict and ex_id:
        current_completion = coverage_dict.get(ex_id, {"coverage": 0.0})["coverage"]
    
    # Route to specific subaction function
    if option == "Explain":
        if subaction == "ExplainNewFact":
            return build_explain_new_fact_prompt(
                ex_id,
                context_section,
                facts_all,
                facts_used,
                selected_fact,
                current_completion,
                user_text=last_utt,
            )
        elif subaction == "RepeatFact":
            return build_repeat_fact_prompt(
                ex_id,
                context_section,
                facts_all,
                facts_used,
                selected_fact,
                current_completion,
                user_text=last_utt,
                auxiliary_context=auxiliary_context,
            )
        elif subaction == "ClarifyFact":
            return build_clarify_fact_prompt(ex_id, context_section, facts_all, facts_used, selected_fact, current_completion)

    elif option == "AskQuestion":
        if subaction == "AskOpinion":
            return build_ask_opinion_prompt(ex_id, context_section, facts_all, facts_used, current_completion)
        elif subaction == "AskMemory":
            return build_ask_memory_prompt(ex_id, context_section, facts_all, facts_used, current_completion)
        elif subaction == "AskClarification":
            return build_ask_clarification_prompt(ex_id, context_section, facts_all, facts_used, current_completion)

    elif option == "OfferTransition":
        if subaction == "SummarizeAndSuggest":
            return build_summarize_and_suggest_prompt(ex_id, context_section, facts_all, facts_used, exhibit_names, knowledge_graph, target_exhibit, coverage_dict)

    elif option == "Conclude":
        if subaction == "WrapUp":
            return build_wrap_up_prompt(ex_id, context_section, facts_all, facts_used, current_completion)
    
    # Should never reach here - all options should be handled above
    raise ValueError(f"Unknown option '{option}' or subaction '{subaction}'")


def _resolve_action_description(option: str, subaction: str, provided: Optional[str]) -> str:
    if provided and str(provided).strip():
        return str(provided).strip()
    try:
        from prompt.action_descriptions import get_action_description
        return get_action_description(subaction)
    except Exception:
        return subaction


def _build_last_obj_like_payload(ex_id: Optional[str], knowledge_graph, auxiliary_context: dict) -> list:
    if not ex_id or not knowledge_graph:
        return []
    meta = knowledge_graph.get_exhibit_metadata(ex_id) or {}
    obj = {
        "objectName": meta.get("object_name", ex_id),
        "name": meta.get("painting_name", ex_id),
        "year": meta.get("year"),
        "artist": meta.get("artist"),
        "location": meta.get("location"),
        "style": meta.get("style"),
        "description": meta.get("description"),
        "moreInfo": meta.get("more_info"),
        "img": meta.get("img") or meta.get("image") or meta.get("image_url"),
    }
    areas = []
    for a in (auxiliary_context or {}).get("aois", []):
        areas.append({
            "name": a.get("name"),
            "description": a.get("description"),
        })
    return [{
        "name_of_object": meta.get("painting_name", ex_id),
        "object_information": obj,
        "areas_in_painting_information": areas,
    }]


def _build_last_aoi_like_payload(current_aoi: Optional[str], auxiliary_context: dict) -> list:
    if not current_aoi:
        return []
    desc = ""
    for a in (auxiliary_context or {}).get("aois", []):
        if str(a.get("name", "")).strip().lower() == str(current_aoi).strip().lower():
            desc = a.get("description", "")
            break
    return [{"b.name": current_aoi, "b.description": desc}]


def _build_image_like_payload(last_obj_like_payload: list, auxiliary_context: dict) -> list:
    if auxiliary_context:
        img = (
            auxiliary_context.get("img")
            or auxiliary_context.get("image")
            or auxiliary_context.get("image_url")
        )
        if img:
            return [{"img_path": img}]
    if last_obj_like_payload:
        img = (last_obj_like_payload[0].get("object_information") or {}).get("img")
        if img:
            return [{"img_path": img}]
    return []


def _build_last_agent_response_like_payload(dialogue_history: List) -> list:
    for turn in reversed(dialogue_history or []):
        if len(turn) >= 2 and str(turn[0]).strip().lower() == "agent":
            text = str(turn[1]).strip()
            if text:
                return [{"YourLastResponseToUser": text}]
    return []


def _build_conversation_history_like_payload(dialogue_history: List) -> list:
    rows = []
    for idx, turn in enumerate(reversed(dialogue_history or []), start=1):
        if len(turn) < 2:
            continue
        role = str(turn[0]).strip().lower()
        text = str(turn[1]).strip()
        if not text:
            continue
        speaker = "Agent" if role == "agent" else "User"
        rows.append({
            "Time": f"T-{idx}",
            "Speaker": speaker,
            "Text": text,
        })
        if len(rows) >= 20:
            break
    return rows


def _build_graph_data_like_payload(knowledge_graph) -> list:
    if not knowledge_graph:
        return []
    rows = []
    for ex_id in knowledge_graph.get_exhibit_names():
        meta = knowledge_graph.get_exhibit_metadata(ex_id) or {}
        obj = {
            "objectName": meta.get("object_name", ex_id),
            "name": meta.get("painting_name", ex_id),
            "year": meta.get("year"),
            "artist": meta.get("artist"),
            "location": meta.get("location"),
            "style": meta.get("style"),
            "description": meta.get("description"),
            "moreInfo": meta.get("more_info"),
            "img": meta.get("img") or meta.get("image") or meta.get("image_url"),
        }
        for aoi_name in meta.get("aois", []):
            aoi_meta = knowledge_graph.get_aoi_metadata(aoi_name) or {}
            aoi = {
                "name": aoi_meta.get("name", aoi_name),
                "description": aoi_meta.get("description", ""),
            }
            rows.append({"c": obj, "a": aoi})
    return rows


def _build_enhanced_context_section(ex_id: Optional[str], last_utt: str, facts_all: List[str],
                                  facts_used: List[str], dialogue_history: List = None,
                                  exhibit_names: List[str] = None, knowledge_graph=None,
                                  auxiliary_context: dict = None, show_facts: bool = True,
                                  action_label: str = "", action_description: str = "",
                                  current_aoi: Optional[str] = None,
                                  conversation_history_rows: Optional[List[dict]] = None) -> str:
    """Build the shared RL base prompt in structured sections."""
    dialogue_history = dialogue_history or []
    auxiliary_context = auxiliary_context or {}

    last_obj_like = _build_last_obj_like_payload(ex_id, knowledge_graph, auxiliary_context)
    last_aoi_like = _build_last_aoi_like_payload(current_aoi, auxiliary_context)
    image_like = _build_image_like_payload(last_obj_like, auxiliary_context)
    last_agent_like = _build_last_agent_response_like_payload(dialogue_history)
    history_like = (
        list(reversed(conversation_history_rows[-20:]))
        if conversation_history_rows
        else _build_conversation_history_like_payload(dialogue_history)
    )
    graph_data_like = _build_graph_data_like_payload(knowledge_graph)

    try:
        from prompt.base_prompt import render_base_prompt
        return render_base_prompt(
            action_label=action_label,
            action_description=action_description,
            last_obj_like=last_obj_like,
            last_aoi_like=last_aoi_like,
            image_like=image_like,
            last_agent_like=last_agent_like,
            history_like=history_like,
            graph_data_like=graph_data_like,
            user_input=last_utt,
        )
    except Exception:
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
Exhibit Data: {graph_data_like}.

[User Input]
{last_utt}

[Response Constraints]
No links or emojis.
No speculation.
Avoid repetition.
Maximum two sentences."""


def _analyze_visitor_utterance(utterance: str) -> str:
    """Analyze visitor's utterance to understand their intent and interests"""
    utterance_lower = utterance.lower()
    
    # Question detection
    if any(word in utterance_lower for word in ['what', 'how', 'why', 'when', 'where', 'who', 'which']) or '?' in utterance:
        if any(word in utterance_lower for word in ['more', 'tell me', 'explain', 'about']):
            return "Asking for more detailed information - wants deeper explanation"
        elif any(word in utterance_lower for word in ['meaning', 'significance', 'important']):
            return "Asking about meaning/significance - wants cultural/historical context"
        elif any(word in utterance_lower for word in ['made', 'created', 'built', 'constructed']):
            return "Asking about creation/construction - wants process/technique information"
        else:
            return "Asking a specific question - wants direct answer"
    
    # Interest/engagement detection
    elif any(word in utterance_lower for word in ['interesting', 'fascinating', 'amazing', 'beautiful', 'incredible']):
        return "Expressing positive interest - engaged and wants to learn more"
    
    # Confusion/clarification detection
    elif any(word in utterance_lower for word in ['confused', 'understand', 'unclear', 'not sure']):
        return "Expressing confusion - needs clarification or simpler explanation"
    
    # Agreement/acknowledgment
    elif any(word in utterance_lower for word in ['yes', 'ok', 'sure', 'i see', 'understand']):
        return "Acknowledging information - ready for next topic or deeper detail"
    
    # Personal connection
    elif any(word in utterance_lower for word in ['reminds me', 'similar', 'like', 'seen']):
        return "Making personal connections - engage with their experience"
    
    else:
        return "General engagement - continue educational dialogue"


# ===== EXPLAIN OPTION FUNCTIONS =====

def build_explain_new_fact_prompt(ex_id: Optional[str], context_section: str,
                                facts_all: List[str], facts_used: List[str],
                                selected_fact: Optional[str], current_completion: float = 0.0,
                                user_text: str = "") -> str:
    """Build ExplainNewFact prompt via RL/prompt module."""
    global LAST_EXPLAIN_NEWFACT_META
    # In current runtime flow, facts_all is already the candidate new_facts list.
    new_facts = list(facts_all or [])

    try:
        from prompt.ExplainNewFacts import build_explain_new_fact_prompt as _build_prompt
        prompt, meta = _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            new_facts=new_facts,
            facts_used=facts_used,
            user_text=user_text,
            current_completion=current_completion,
            t_low=0.18,
            t_high=0.35,
            allow_top2_high=True,
        )
        LAST_EXPLAIN_NEWFACT_META = meta or {}
        return prompt
    except Exception:
        LAST_EXPLAIN_NEWFACT_META = {}
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

ExplainNewFact policy:
1. First answer the user's question directly.
2. If confidence is low or no new facts exist, do not force facts.
3. If adding a fact, use exact [FACT_ID], and never invent or repeat IDs.
4. Maximum two sentences.

Response:"""

def build_repeat_fact_prompt(ex_id: Optional[str], context_section: str,
                           facts_all: List[str], facts_used: List[str],
                           selected_fact: Optional[str], current_completion: float = 0.0,
                           user_text: str = "", auxiliary_context: Optional[dict] = None) -> str:
    """Build RepeatFact prompt via RL/prompt module."""
    global LAST_REPEATFACT_META

    try:
        from prompt.RepeatFact import build_repeat_fact_prompt as _build_prompt
        prompt, meta = _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            facts_used=facts_used,
            user_text=user_text,
            current_completion=current_completion,
            t_low=0.18,
            t_high=0.35,
            auxiliary_context=auxiliary_context,
        )
        LAST_REPEATFACT_META = meta or {}
        return prompt
    except Exception:
        LAST_REPEATFACT_META = {}
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

RepeatFact policy:
1. First answer the user's question naturally.
2. Then restate one previously shared fact with its exact [FACT_ID].
3. Do not add new facts or invent IDs.
4. Maximum two sentences.

Response:"""
def build_clarify_fact_prompt(ex_id: Optional[str], context_section: str,
                            facts_all: List[str], facts_used: List[str],
                            selected_fact: Optional[str], current_completion: float = 0.0) -> str:
    """Build prompt for clarifying a fact."""
    try:
        from prompt.ClarifyFact import build_clarify_fact_prompt as _build_prompt
        return _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            facts_used=facts_used,
            selected_fact=selected_fact,
            current_completion=current_completion,
        )
    except Exception:
        if facts_used:
            fact_to_clarify = selected_fact if selected_fact else facts_used[-1]
            return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

ClarifyFact policy:
1. First, respond naturally to the user's question.
2. Clarify this previously discussed fact in simpler words:
   "{fact_to_clarify}"
3. Do not introduce new facts or [FACT_ID].
4. Maximum two sentences.

Response:"""
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

ClarifyFact policy:
1. No previously discussed fact is available.
2. Answer simply without adding [FACT_ID].
3. Maximum two sentences.

Response:"""


# ===== ASK QUESTION OPTION FUNCTIONS =====

def build_ask_opinion_prompt(ex_id: Optional[str], context_section: str,
                               facts_all: List[str], facts_used: List[str],
                               current_completion: float = 0.0) -> str:
    """Build prompt for asking the visitor's opinion."""
    try:
        from prompt.AskOpinion import build_ask_opinion_prompt as _build_prompt
        return _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            current_completion=current_completion,
        )
    except Exception:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

AskOpinion policy:
1. First respond naturally to the user's input.
2. Then ask one opinion/feeling question tied to current exhibit or AOI keywords.
3. Do not include [FACT_ID] or new facts.
4. Maximum two sentences.

Response:"""


def build_ask_memory_prompt(ex_id: Optional[str], context_section: str,
                          facts_all: List[str], facts_used: List[str],
                          current_completion: float = 0.0) -> str:
    """Build prompt for checking the visitor's memory."""
    try:
        from prompt.AskMemory import build_ask_memory_prompt as _build_prompt
        return _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            facts_used=facts_used,
            current_completion=current_completion,
        )
    except Exception:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

AskMemory policy:
1. First respond naturally.
2. Then ask one memory-check question.
3. Priority: facts_used first; if unavailable, use recent conversation points.
4. Do not include [FACT_ID].
5. Maximum two sentences.

Response:"""


def build_ask_clarification_prompt(ex_id: Optional[str], context_section: str,
                                 facts_all: List[str], facts_used: List[str],
                                 current_completion: float = 0.0) -> str:
    """Build prompt for asking for clarification."""
    try:
        from prompt.AskClarification import build_ask_clarification_prompt as _build_prompt
        return _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            current_completion=current_completion,
        )
    except Exception:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

AskClarification policy:
1. Follow this priority order: Answer > Summary > Clarify question.
2. Only ask a clarification question if ambiguity is genuine.
3. Do not include any [FACT_ID].
4. Do not quote the visitor verbatim.
5. Maximum two sentences.

Response:"""


# ===== OFFER TRANSITION OPTION FUNCTIONS =====

def _build_exhibit_inventory_section(exhibit_names: List[str], facts_used: List[str], knowledge_graph) -> str:
    """Build a section showing all exhibits and their exploration status"""
    if not exhibit_names or not knowledge_graph:
        return ""
    
    inventory_lines = ["MUSEUM EXHIBITS INVENTORY:", ""]
    
    # Convert facts_used to a set for faster lookup (plain text without IDs)
    facts_used_set = set(facts_used)
    
    # Calculate facts per exhibit
    exhibit_facts_count = {}
    exhibit_facts_used = {}
    
    for exhibit_name in exhibit_names:
        facts_all = knowledge_graph.get_exhibit_facts(exhibit_name) if knowledge_graph else []
        # Strip IDs from facts_all for comparison
        facts_remaining = [f for f in facts_all if knowledge_graph.strip_fact_id(f) not in facts_used_set]
        
        exhibit_facts_count[exhibit_name] = len(facts_all)
        exhibit_facts_used[exhibit_name] = len(facts_all) - len(facts_remaining)
    
    # Sort by unexplored facts (most first)
    sorted_exhibits = sorted(
        exhibit_names,
        key=lambda ex: (exhibit_facts_count.get(ex, 0) - exhibit_facts_used.get(ex, 0)),
        reverse=True
    )
    
    for exhibit_name in sorted_exhibits:
        total = exhibit_facts_count.get(exhibit_name, 0)
        used = exhibit_facts_used.get(exhibit_name, 0)
        remaining = total - used
        
        status_icon = "âœ“" if used == total else "â—" if used > 0 else "â—‹"
        inventory_lines.append(
            f"  {status_icon} {exhibit_name.replace('_', ' ')}: "
            f"{used}/{total} facts discussed ({remaining} unexplored)"
        )
    
    inventory_lines.append("")
    return "\n".join(inventory_lines)


def build_summarize_and_suggest_prompt(ex_id: Optional[str], context_section: str,
                                     facts_all: List[str], facts_used: List[str],
                                     exhibit_names: List[str] = None, knowledge_graph=None,
                                     target_exhibit: str = None, coverage_dict: dict = None) -> str:
    """Build prompt for SummarizeAndSuggest transition."""
    global LAST_TRANSITION_META
    try:
        from prompt.SummarizeAndSuggest import build_summarize_and_suggest_prompt as _build_prompt
        prompt, meta = _build_prompt(
            current_exhibit=ex_id,
            target_exhibit=target_exhibit,
            context_section=context_section,
        )
        LAST_TRANSITION_META = meta or {}
        return prompt
    except Exception:
        LAST_TRANSITION_META = {
            "transition_target": target_exhibit,
            "transition_has_target": 1 if target_exhibit else 0,
            "transition_mode": "summarize_and_suggest" if target_exhibit else "fallback",
        }
        current_name = (ex_id or "current exhibit").replace("_", " ")
        if target_exhibit:
            target_name = target_exhibit.replace("_", " ")
            return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {current_name}
---

{context_section}

SummarizeAndSuggest policy:
1. Keep exactly two sentences.
2. Sentence 1: briefly summarize what has been discussed so far.
3. Sentence 2: suggest moving to "{target_name}" and name it explicitly.
4. Do not imply the visitor already moved.
5. Do not include [FACT_ID].

Response:"""
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {current_name}
---

{context_section}

SummarizeAndSuggest policy:
1. Keep exactly two sentences.
2. Sentence 1: briefly summarize what has been discussed so far.
3. Sentence 2: suggest choosing any other exhibit.
4. Do not imply the visitor already moved.
5. Do not include [FACT_ID].

Response:"""

# ===== CONCLUDE OPTION FUNCTIONS =====

def build_wrap_up_prompt(ex_id: Optional[str], context_section: str,
                        facts_all: List[str], facts_used: List[str],
                        current_completion: float = 0.0) -> str:
    """Build prompt for wrapping up the visit."""
    try:
        from prompt.WrapUp import build_wrap_up_prompt as _build_prompt
        return _build_prompt(
            ex_id=ex_id,
            context_section=context_section,
            current_completion=current_completion,
        )
    except Exception:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

WrapUp policy:
1. Keep exactly two sentences.
2. If the user's latest input contains a clear question:
   - Sentence 1: briefly answer that question directly.
   - Sentence 2: politely close the visit (thanks + warm ending).
3. If there is no clear question:
   - Sentence 1: briefly summarize 1-2 key points already discussed.
   - Sentence 2: politely close the visit (thanks + warm ending).
4. Do not introduce new facts.
5. Do not include any [FACT_ID].
6. Do not ask a new question.
7. Do not mention system state (coverage, policy, strategy, completion).

Response:"""




