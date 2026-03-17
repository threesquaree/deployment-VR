"""
Dialogue Planner for HRL Museum Dialogue Agent

This module implements structured prompting for LLM-based dialogue generation in the
HRL museum agent. It translates high-level options and subactions into structured
prompts that guide LLM generation while maintaining dialogue coherence and policy
adherence.
"""

import re
from typing import List, Optional


def build_prompt(option: str, subaction: str, ex_id: Optional[str], 
                last_utt: str, facts_all: List[str], facts_used: List[str], 
                selected_fact: Optional[str], dialogue_history: List[str] = None,
                exhibit_names: List[str] = None, knowledge_graph=None,
                target_exhibit: str = None, coverage_dict: dict = None) -> str:
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
    
    # Build context - show facts ONLY for Explain option and Conclude option
    show_facts = (option == "Explain") or (option == "Conclude" and subaction == "SummarizeKeyPoints")
    context_section = _build_enhanced_context_section(ex_id, last_utt, facts_all, facts_used, dialogue_history, exhibit_names, knowledge_graph, show_facts=show_facts)

    # Calculate current exhibit completion for contextual prompts
    current_completion = 0.0
    if coverage_dict and ex_id:
        current_completion = coverage_dict.get(ex_id, {"coverage": 0.0})["coverage"]
    
    # Route to specific subaction function
    if option == "Explain":
        if subaction == "ExplainNewFact":
            return build_explain_new_fact_prompt(ex_id, context_section, facts_all, facts_used, selected_fact, current_completion)
        elif subaction == "RepeatFact":
            return build_repeat_fact_prompt(ex_id, context_section, facts_all, facts_used, selected_fact, current_completion)
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
        if subaction in ("SuggestMove", "SummarizeAndSuggest"):
            return build_offer_transition_prompt(ex_id, context_section, facts_all, facts_used, exhibit_names, knowledge_graph, target_exhibit, coverage_dict)

    elif option == "Conclude":
        if subaction == "WrapUp":
            return build_wrap_up_prompt(ex_id, context_section, facts_all, facts_used, current_completion)
        elif subaction == "SummarizeKeyPoints":
            return build_summarize_key_points_prompt(ex_id, context_section, facts_all, facts_used, current_completion)
    
    # Should never reach here - all options should be handled above
    raise ValueError(f"Unknown option '{option}' or subaction '{subaction}'")


def _build_enhanced_context_section(ex_id: Optional[str], last_utt: str, facts_all: List[str], 
                                  facts_used: List[str], dialogue_history: List = None,
                                  exhibit_names: List[str] = None, knowledge_graph=None, show_facts: bool = True) -> str:
    """Build enhanced context section with rich dialogue understanding
    
    Args:
        dialogue_history: List of (role, utterance) tuples where role is 'agent' or 'user'
    """
    import re
    context_parts = []
    
    # === EXHIBIT INFORMATION ===
    if ex_id:
        context_parts.append(f"CURRENT EXHIBIT: {ex_id.replace('_', ' ')}")
    
    # === VISITOR'S CURRENT MESSAGE ===
    if last_utt.strip():
        context_parts.append("VISITOR'S MESSAGE:")
        context_parts.append(f'"{last_utt}"')
        context_parts.append("")
    
    # === DIALOGUE HISTORY (for natural conversation flow) ===
    fact_ids_in_context = set()  # Track fact IDs already in conversation
    if dialogue_history and len(dialogue_history) > 0:
        # Get last 4 utterances (2 full exchanges: agent->user->agent->user)
        recent_context = dialogue_history[-4:] if len(dialogue_history) > 4 else dialogue_history
        context_parts.append("CONVERSATION CONTEXT (for natural flow):")
        for i, utterance_tuple in enumerate(recent_context, 1):
            # Handle both (role, utterance) and (role, utterance, turn_number) formats
            if len(utterance_tuple) >= 2:
                role, utterance = utterance_tuple[0], utterance_tuple[1]
            else:
                continue  # Skip invalid entries
            
            role_label = "AGENT" if role == "agent" else "VISITOR"
            context_parts.append(f'  {role_label}: "{utterance}"')
            
            # Extract fact IDs from this utterance
            fact_ids = re.findall(r'\[([A-Z]{2}_\d{3})\]', utterance)
            fact_ids_in_context.update(fact_ids)
        
        # CRITICAL: Warn about fact ID reuse
        if fact_ids_in_context:
            context_parts.append("")
            context_parts.append(f"FACTS ALREADY SHARED: {sorted(fact_ids_in_context)}")
            context_parts.append("(Use conversation context to build naturally on what was discussed)")
        context_parts.append("")

    # === SHOW FACTS ONLY IF ALLOWED (Explain or Summarize actions) ===
    # NOTE: For ExplainNewFact, facts_all is already filtered to unmentioned facts by env.py
    # The specific prompt builders (build_explain_new_fact_prompt) handle showing facts
    # So we DON'T show facts here to avoid duplication
    if not show_facts:
        # For Ask/Transition/Conclude - NO FACTS SHOWN
        context_parts.append("NO FACTS IN THIS RESPONSE TYPE")
        context_parts.append("Your job is to ask questions or suggest actions ONLY")
        context_parts.append("")
    
    return "\n".join(context_parts)


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
                                selected_fact: Optional[str], current_completion: float = 0.0) -> str:
    """Build prompt for explaining a new fact about current exhibit"""
    
    # CRITICAL: Filter to only show NEW/unused facts
    used_ids = set()
    for fact in facts_used:
        # Extract fact ID from used facts
        import re
        match = re.search(r'\[([A-Z]{2}_\d{3})\]', fact)
        if match:
            used_ids.add(match.group(1))
    
    # Filter out already-used facts
    new_facts = []
    for fact in facts_all:
        import re
        match = re.search(r'\[([A-Z]{2}_\d{3})\]', fact)
        if match and match.group(1) not in used_ids:
            new_facts.append(fact)

    if not new_facts:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

No new facts available. Ask if they'd like to explore a different aspect or move to another exhibit.
DO NOT mention completion percentage or meta-information.

Response (1-2 sentences):"""

    new_facts_list = "\n".join([f"  ✓ {fact}" for fact in new_facts])
    
    # Show used facts as a warning
    used_warning = ""
    if facts_used:
        used_ids_str = ", ".join(sorted(used_ids))
        used_warning = f"""
🚫 ALREADY MENTIONED (DO NOT USE THESE):
   {used_ids_str}
"""

    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id}
Progress: {current_completion:.1%} covered
---

{context_section}
{used_warning}
🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use the conversation context above to maintain natural flow. Your response MUST:
- Respond naturally to their message (use context, don't quote verbatim)
- Then naturally weave in a NEW fact that connects to their interest

⚠️ USE ONLY NEW FACTS - NEVER REPEAT ⚠️
NEW FACTS AVAILABLE (pick 1-2 from this list ONLY):
{new_facts_list}

🚨 RESPONSE STRUCTURE:
1. Respond naturally to what they said (e.g., "I'm glad you think so!", "Great question!", "Yes, exactly!")
2. Share 1-2 NEW facts that relate to their interest
3. Use EXACT fact IDs in brackets: [ID1] ... [ID2]
4. Keep it conversational (2-3 sentences total)
5. DO NOT quote what the visitor said verbatim (avoid "You said...", "I see you...")

STRATEGY: Explain/ExplainNewFact - Reference what was already shared from history to build on it naturally. Use history to know what facts were mentioned and continue the educational flow.

✓ GOOD EXAMPLES:
"I'm glad you're enjoying it! Speaking of the artistry, this piece was actually created in 1654 [KC_003]."
"That's a great observation! The turban here is indeed traditional [TU_001], made of fine silk [TU_002]."

✗ FORBIDDEN:
- Quoting or repeating what the visitor said verbatim
- Ignoring what the visitor said and just listing facts
- Repeating ANY fact ID from the "ALREADY MENTIONED" list
- Making up fact IDs that don't exist

Response:"""


def build_repeat_fact_prompt(ex_id: Optional[str], context_section: str,
                           facts_all: List[str], facts_used: List[str],
                           selected_fact: Optional[str], current_completion: float = 0.0) -> str:
    """Build prompt for repeating a previously shared fact"""

    if facts_used:
        fact_to_repeat = selected_fact if selected_fact else facts_used[-1]

        # Extract fact ID from the fact string
        fact_id_match = re.search(r'\[([A-Z]{2}_\d{3})\]', fact_to_repeat)
        fact_id = fact_id_match.group(1) if fact_id_match else ""
        fact_content = re.sub(r'\[([A-Z]{2}_\d{3})\]\s*', '', fact_to_repeat).strip()
        
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id}
Progress: {current_completion:.1%} covered
---

{context_section}

🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use conversation context to maintain natural flow. React naturally to what they said!

YOUR TASK:
1. Respond naturally to their message (use context, don't quote verbatim)
2. Rephrase this fact in fresh, clearer words: "{fact_content}"
3. Include the exact fact ID: [{fact_id}]
4. DO NOT quote what the visitor said verbatim

STRATEGY: Explain/RepeatFact - Use history to identify which fact needs repeating based on the conversation flow.

✓ GOOD EXAMPLES:
"Great question! To put it simply, this piece dates back to 1643 [{fact_id}]."
"I see what you're curious about! The oil on panel technique [{fact_id}] creates that depth you're noticing."

Keep it brief (2-3 sentences). Don't add NEW facts.

Response:"""
    else:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

No facts shared yet. Share an interesting fact about this exhibit that relates to what they just said.
DO NOT mention completion percentage or meta-information.

Response (2-3 sentences):"""


def build_clarify_fact_prompt(ex_id: Optional[str], context_section: str,
                            facts_all: List[str], facts_used: List[str],
                            selected_fact: Optional[str], current_completion: float = 0.0) -> str:
    """Build prompt for clarifying a fact"""
    if facts_used:
        fact_to_clarify = selected_fact if selected_fact else facts_used[-1]
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use conversation context to understand what needs clarification. Address their confusion naturally!

YOUR TASK:
1. Show you understand what confused them (use context, don't quote verbatim)
2. Clarify this fact using a simple analogy or everyday example: "{fact_to_clarify}"
3. DO NOT quote what the visitor said verbatim

STRATEGY: Explain/ClarifyFact - Reference what was discussed from history to understand what needs clarification.

✓ GOOD EXAMPLES:
"Ah, I see what you mean! Think of it like this - the technique is similar to..."
"That's a great question! Basically, what this means is..."
"I can see why that's confusing! Imagine it as..."

Keep it conversational (2-3 sentences). NO new facts or [FACT_IDs] - just clarify what we already discussed."""
    else:
        return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

No facts shared yet. Clarify an interesting fact about this exhibit that relates to what they just said.
DO NOT mention completion percentage or meta-information.

Response (2-3 sentences):"""


# ===== ASK QUESTION OPTION FUNCTIONS =====

def build_ask_opinion_prompt(ex_id: Optional[str], context_section: str,
                               facts_all: List[str], facts_used: List[str],
                               current_completion: float = 0.0) -> str:
    """Build prompt for asking the visitor's opinion"""

    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use conversation history to ask a relevant follow-up question. React naturally to what they said!

YOUR TASK:
1. React warmly to what they said (use context, don't quote verbatim)
2. Ask a genuine question about their opinion/feeling on something related
3. DO NOT quote what the visitor said verbatim

STRATEGY: AskQuestion/AskOpinion - Use history to ask relevant follow-ups based on what was discussed.

✓ GOOD EXAMPLES:
"That's a lovely observation! What draws your eye most about this piece?"
"I see what you mean! Do you find the colors striking, or is it more the subject matter?"
"Absolutely! What's your first impression of the artist's style here?"

✗ BAD (generic/ignoring their input/quoting verbatim):
"What do you think of this painting?"
"Do you have any questions?"
"You said 'interesting' - what do you think?" (quoting verbatim)

Keep it conversational (1-2 sentences). NO facts or [IDs].

Response:"""


def build_ask_memory_prompt(ex_id: Optional[str], context_section: str,
                          facts_all: List[str], facts_used: List[str],
                          current_completion: float = 0.0) -> str:
    """Build prompt for checking the visitor's memory"""

    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use conversation history to reference what was discussed earlier. Respond naturally to what they said!

YOUR TASK:
1. Respond naturally to what they said (use context, don't quote verbatim)
2. Playfully check if they remember something from earlier in your chat
3. Reference past topics naturally, don't quote verbatim
4. DO NOT quote what the visitor said verbatim

STRATEGY: AskQuestion/AskMemory - Naturally reference past conversation to check memory, don't quote verbatim.

✓ GOOD EXAMPLES:
"Great question! Speaking of which, do you recall what year this was painted?"
"I'm glad you noticed that! Can you remember what we said about the artist's technique?"
"Exactly right! Do you remember why that detail is significant?"

Keep it light and engaging (1-2 sentences). NO [FACT_IDs].

Response:"""


def build_ask_clarification_prompt(ex_id: Optional[str], context_section: str,
                                 facts_all: List[str], facts_used: List[str],
                                 current_completion: float = 0.0) -> str:
    """Build prompt for asking for clarification"""
    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

🎯 PRIORITY: RESPOND NATURALLY TO THE VISITOR
Use conversation history to understand what needs clarification. Respond naturally to what they said!

YOUR TASK:
1. Show you're listening by responding naturally (use context, don't quote verbatim)
2. Ask a clarifying question to better understand what interests them
3. DO NOT quote what the visitor said verbatim

STRATEGY: AskQuestion/AskClarification - Use history to understand what needs clarification and ask relevant questions.

✓ GOOD EXAMPLES:
"That's interesting! Are you more curious about the historical context or the artistic technique?"
"I'd love to tell you more! Would you like to know about the symbolism or the artist's life?"
"Good point! What specifically caught your attention about that?"

Keep it warm and curious (1-2 sentences). NO [FACT_IDs].

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
        
        status_icon = "✓" if used == total else "◐" if used > 0 else "○"
        inventory_lines.append(
            f"  {status_icon} {exhibit_name.replace('_', ' ')}: "
            f"{used}/{total} facts discussed ({remaining} unexplored)"
        )
    
    inventory_lines.append("")
    return "\n".join(inventory_lines)


def build_offer_transition_prompt(ex_id: Optional[str], context_section: str,
                                facts_all: List[str], facts_used: List[str],
                                exhibit_names: List[str] = None, knowledge_graph = None,
                                target_exhibit: str = None, coverage_dict: dict = None) -> str:
    """
    Build prompt for transitioning to another exhibit.

    Uses exhibit completion tracking to choose the best target exhibit.
    - target_exhibit: The exhibit we want to guide visitor to (from env selection logic)
    - coverage_dict: Museum-wide completion stats (from state tracking)
    """

    # Fallback for when we don't have proper state data
    if not target_exhibit:
        return f"""You are a museum guide. SUGGEST moving to a different exhibit.

{context_section}

Respond naturally:
- Suggest visiting another exhibit
- Be conversational and helpful
- Keep it brief (2 sentences)"""

    # Main transition logic using state-driven exhibit selection
    target_name = target_exhibit.replace('_', ' ')
    current_name = ex_id.replace('_', ' ') if ex_id else 'current exhibit'
    
    # Get target exhibit info if knowledge graph available
    target_description = ""
    if knowledge_graph:
        try:
            target_facts = knowledge_graph.get_exhibit_facts(target_exhibit)
            if target_facts:
                # Get first fact as a teaser
                target_description = f"\nTEASER about {target_name}: {target_facts[0][:100]}..."
        except:
            pass

    # Use exhibit completion data to inform the transition
    if coverage_dict:
        current_stats = coverage_dict.get(ex_id, {"mentioned": 0, "total": 1, "coverage": 0})
        target_stats = coverage_dict.get(target_exhibit, {"mentioned": 0, "total": 1, "coverage": 0})
        
        # Calculate remaining facts
        target_remaining = target_stats["total"] - target_stats["mentioned"]
        
        # CRITICAL: Warn if target is exhausted (should never happen, but safety check)
        if target_remaining <= 0:
            freshness_note = "⚠️ WARNING: This exhibit has already been fully covered!"
        elif target_stats["mentioned"] == 0:
            freshness_note = f"(completely fresh - {target_stats['total']} facts to discover)"
        else:
            freshness_note = f"({target_remaining} new facts remaining out of {target_stats['total']})"

        return f"""MUSEUM GUIDE - SMOOTH TRANSITION TO NEW PAINTING

YOU ARE CURRENTLY AT: "{current_name}" (covered {current_stats["mentioned"]}/{current_stats["total"]} facts)
YOU WILL NOW MOVE TO: "{target_name}" {freshness_note}
{target_description}

{context_section}

🎯 YOUR TASK:
1. Briefly wrap up "{current_name}" (1 short sentence - use conversation history to reference what was discussed naturally)
2. Smoothly introduce "{target_name}" by name and make it sound interesting
3. IMPORTANT: You are SUGGESTING the move - the visitor hasn't moved yet!
4. DO NOT quote what the visitor said verbatim - use conversation context for natural flow

STRATEGY: OfferTransition/SummarizeAndSuggest - Reference what was discussed to transition smoothly. Use history to wrap up naturally.

✓ GOOD EXAMPLES:
"We've explored {current_name}'s fascinating history. Now, let me take you to see {target_name} - a remarkable piece that tells a very different story."
"That covers the highlights of {current_name}! Right this way to {target_name}, where we'll discover..."

✗ BAD (DO NOT DO THIS):
- Jumping straight into facts about the new exhibit
- Not mentioning {target_name} by name
- Saying "we're now looking at" (you haven't moved yet!)

Response (2-3 sentences, conversational):"""

    # Simple fallback without completion data
    return f"""MUSEUM GUIDE - SUGGEST MOVE TO NEW PAINTING

CURRENT PAINTING: "{current_name}"
NEXT PAINTING: "{target_name}"

{context_section}

🎯 YOUR TASK:
1. Briefly wrap up the current painting (use conversation history to reference what was discussed naturally)
2. Suggest moving to "{target_name}" by name
3. Make it sound enticing
4. DO NOT quote what the visitor said verbatim - use conversation context for natural flow

✓ EXAMPLE: "We've seen some wonderful details here. Shall we head over to {target_name}? It has quite a story to tell."

Response (2 sentences):"""

# ===== CONCLUDE OPTION FUNCTIONS =====

def build_wrap_up_prompt(ex_id: Optional[str], context_section: str,
                        facts_all: List[str], facts_used: List[str],
                        current_completion: float = 0.0) -> str:
    """Build prompt for wrapping up the visit"""
    return f"""[CONTEXT - DO NOT REPEAT]
Museum guide at: {ex_id} | Progress: {current_completion:.1%} covered
---

{context_section}

YOUR TASK:
- Thank them warmly for visiting
- Express hope they enjoyed the experience
- Use conversation history to summarize naturally what was discussed
- Keep it natural and conversational (2 sentences)
- DO NOT quote what the visitor said verbatim

STRATEGY: Conclude/WrapUp - Summarize naturally using history context. Reference the overall experience without quoting verbatim.

CRITICAL RULES:
- NO [FACT_ID] tags or recapping information
- Focus on their overall experience
- End on a positive, welcoming note
- DO NOT mention completion percentage or meta-information

Response:"""


def build_summarize_key_points_prompt(ex_id: Optional[str], context_section: str, 
                                    facts_all: List[str], facts_used: List[str]) -> str:
    """Build prompt for summarizing key points"""
    if facts_used:
        key_points = facts_used[-3:] if len(facts_used) >= 3 else facts_used
        summary_points = "\n".join([f"- {fact}" for fact in key_points])
        
        return f"""SUMMARIZE these key points briefly: 
{summary_points}

{context_section}

INSTRUCTIONS:
1. Recap 2-3 main points using conversation history
2. Keep very brief (2-3 sentences max)
3. DO NOT quote what the visitor said verbatim

CRITICAL RULES:
- NO new facts - only summarize what's been discussed
- NO [FACT_ID] tags
- Focus on the most interesting or important points

STRATEGY: Conclude/SummarizeKeyPoints - Use history to summarize naturally what was discussed, without quoting verbatim.

Response:"""
    else:
        return f"""Museum guide. Current exhibit: {ex_id} (completion: {current_completion:.1%}).

{context_section}

YOUR TASK:
- Provide a warm conclusion to the visit
- Thank the visitor for their time and engagement
- Express appreciation for their interest
- End on a positive, welcoming note

Response (2 sentences):"""


