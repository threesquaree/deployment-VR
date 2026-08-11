"""Smoke test + integration reference for the VR laptop. Run from inside this folder:

    python run_agent_example.py

No repo, no simulator, no BERT -- needs only this folder plus `pip install -r
requirements.txt`. Exercises the full decision path the VR loop must implement:
WorldState -> masks -> 31-d observation -> masked policy -> action. If this prints
sensible decisions on the VR laptop, the ML side of the integration works; what remains
is wiring YOUR classifier, NLG and gaze into the same loop (see HANDOFF.md, turn-loop
section).
"""
import json
import torch

from dialogue_masks import (WorldState, available_options, available_subactions,
                            from_summary, validate_response_type)
from state_builder_31d import build_observation
from agent import FlatActorCriticAgent

# --- load exactly what training recorded; never hardcode flags ---
summary = json.load(open("summary.json"))
mask_flags = from_summary(summary)
# Fact IDs MUST come from the same extraction training used, or coverage ratios and
# exhaustion flags will disagree with the policy's training distribution.
from knowledge_graph import SimpleKnowledgeGraph
skg = SimpleKnowledgeGraph("museum_knowledge_graph.json")
exhibits = skg.get_exhibit_names()
fact_ids = {ex: {skg.extract_fact_id(f) for f in skg.get_exhibit_facts(ex)}
            for ex in exhibits}

agent = FlatActorCriticAgent(state_dim=31,
                             options=["Explain", "AskQuestion", "OfferTransition",
                                      "Conclude", "Engage"],
                             subactions={"Explain": ["ExplainNewFact", "ClarifyFact"],
                                         "AskQuestion": ["AskOpinion"],
                                         "OfferTransition": ["SummarizeAndSuggest"],
                                         "Conclude": ["WrapUp"],
                                         "Engage": ["RecoverEngagement"]},
                             hidden_dim=256, lstm_hidden_dim=128, use_lstm=True,
                             device="cpu")
sd = torch.load("checkpoint_ep1000_model.pt", map_location="cpu", weights_only=False)
agent.network.load_state_dict(sd["agent_state"])
agent.network.eval()
agent.reset()   # once per session/episode -- clears the LSTM
print(f"loaded checkpoint (episode {sd.get('episode', '?')}), 31-d policy ready\n")

# --- three illustrative situations ---
scenarios = [
    ("fresh visitor at exhibit 1, engaged",
     dict(focus=1, mentioned={}, rtype="statement", disengaged=False)),
    ("visitor just DISENGAGED mid-tour",
     dict(focus=2, mentioned={exhibits[1]: set(list(fact_ids[exhibits[1]])[:3])},
          rtype="disengaged", disengaged=True)),
    ("exhibit exhausted, visitor engaged (dead end)",
     dict(focus=1, mentioned={exhibits[0]: set(fact_ids[exhibits[0]])},
          rtype="acknowledgment", disengaged=False)),
]
for label, s in scenarios:
    ws = WorldState(focus=s["focus"], exhibit_keys=exhibits,
                    facts_mentioned=s["mentioned"], exhibit_fact_ids=fact_ids,
                    last_response_type=validate_response_type(s["rtype"]),
                    visitor_disengaged=s["disengaged"], **mask_flags)
    legal = available_options(ws)
    subs = {o: available_subactions(ws, o) for o in legal}
    obs = build_observation(ws, actions_used={}, dwell=0.5, last_delta_dwell=0.0)
    a = agent.select_action(obs, legal, subs, deterministic=True)
    print(f"{label}\n  legal: {legal}\n  -> {a['option_name']}/{a['subaction_name']}\n")
