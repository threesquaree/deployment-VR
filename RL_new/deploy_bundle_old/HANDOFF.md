# VR deployment handoff — study agent `E_flat_S2`

*2026-08-01. Everything on the training side is verified; this file is the contract for the
VR side. Companion evidence: `results/e_series_deployment_stack_20260731/CONCLUSIONS.md` and
`results/EXPERIMENTS.md`.*

## What ships (copy to the VR machine)

| file | role |
|---|---|
| `training_logs/experiments/20260731/flat_E_flat_S2_1000ep/checkpoints/checkpoint_ep1000_model.pt` | policy weights (flat, 31-d in, 6 actions out; weights under key `agent_state`) |
| `training_logs/experiments/20260731/flat_E_flat_S2_1000ep/summary.json` | the run's own config record — mask flags are read FROM THIS, never hardcoded |
| `inference/dialogue_masks.py` | action masking (7 rules) — dependency-free, parity-tested 16/16 flag combos |
| `inference/state_builder_31d.py` | observation builder — parity-tested against `env._get_obs()` on live episodes |
| `museum_knowledge_graph.json` | exhibits and facts |

Do **not** use `inference/state_builder.py` (154-d, stale) or `inference/test_model.py`
(partial mask reimplementation). Both predate this work and caused the original VR collapse.

## Verified numbers this agent should reproduce

Frozen, deterministic, 50-episode evals (`tools/eval_checkpoint.py`):

| | template sim | LLM sim |
|---|---:|---:|
| facts/episode | 26.94 ± 1.00 | 27.00 ± 1.05 |
| action mix Explain/Recover/Transition | 67.9 / 20.5 / 11.6% | 67.7 / 20.0 / 12.2% |

If VR behaviour deviates wildly from this mix (e.g. >85% any single action), integration is
broken — see the turn-loop section first, it is the historical culprit.

## THE TURN LOOP — the critical integration requirement

Acting is only **half** a turn. The state must be updated with the visitor's reaction BEFORE
the next decision, or the policy stares at a frozen observation and collapses to its modal
action (100% Explain). This exact mistake broke the first VR deployment *and* our own first
eval harness; it is the most likely failure mode of this integration.

```
loop:
  1. ws       = current WorldState                (focus, coverage, usage, flags, LAST rtype)
  2. legal    = dialogue_masks.available_options(ws)   + per-option subactions
  3. obs      = state_builder_31d.build_observation(ws, actions_used, dwell, delta_dwell)
  4. action   = policy(obs) restricted to legal        (argmax over masked logits)
  5. speak    = NLG(action, visitor's last utterance, unmentioned facts)   -> agent talks
  6. LISTEN   = classifier(visitor's reply)            -> one of the 8 labels
  7. UPDATE   = ws.last_response_type = label; ws.visitor_disengaged = (label=="disengaged");
                focus/coverage/usage counters; dwell from gaze
  8. goto 1                                            (steps 6-7 must happen EVERY turn)
```

## Mask flags: read from summary.json, never hardcode

```python
from inference.dialogue_masks import from_summary, WorldState
flags = from_summary(json.load(open("summary.json")))   # raises if provenance missing
ws = WorldState(..., **flags)
```
For this checkpoint that resolves to: stall mask ON, forced recovery ON, clarify-misfire mask
ON, rescue-only OFF. A policy trained under forced recovery has never chosen `Engage` freely —
deploying without that mask changes its behaviour entirely.

## Label contract (positional one-hot, indices 21–28)

`acknowledgment, follow_up_question, question, statement, confusion, silence,
clarification_request, disengaged` — exact strings, exact order; `disengaged` = index 28.
Run every classifier output through `dialogue_masks.validate_response_type()` — it raises on
unknown labels instead of silently reading them as `statement`.

**OPEN DECISION (owner: Nayan, on the VR machine):** can the classifier emit
`repeat_request`? It is NOT in the contract. If yes, map it explicitly before validation —
recommended `repeat_request -> confusion` (both are "please go over that again" states, and
`confusion` legally enables ClarifyFact, which is the right response). Do not let it reach
the validator unmapped.

## Observation inputs the VR side must supply

| input | source |
|---|---|
| focus (which exhibit, 0 = none) | VR position/gaze |
| facts_mentioned per exhibit | dialogue manager counters (fact ids delivered) |
| actions_used per subaction | counter over chosen actions |
| last_response_type | classifier (validated) |
| dwell in [0,1], delta_dwell | gaze dwell signal, same normalization as training; if no
equivalent exists, fixed dwell=0.5/delta=0 is tolerable (dims 29–30 are reward-irrelevant
under `utterance_only`, so the policy's dependence on them is weak) |

## Action space (policy output -> VR behaviour)

Flat softmax over 6: `Explain/ExplainNewFact, Explain/ClarifyFact, AskQuestion/AskOpinion,
OfferTransition/SummarizeAndSuggest, Conclude/WrapUp, Engage/RecoverEngagement`.
Mask before argmax: additive −1e10 on illegal entries (see `FlatActorCriticAgent.select_action`
for the reference implementation). Use **deterministic argmax** — it is what both evals used.

## NLG checklist (this is what "answering the visitor well" depends on)

The policy picks the *move*; the words come from the VR-side generator. Its prompt must
include: (a) the visitor's last utterance verbatim, (b) the current exhibit's un-mentioned
facts, (c) the chosen move. The observation/BERT question is irrelevant here — answer quality
lives entirely in this prompt.

## Verification ladder on the VR machine

1. `validate_response_type` wired at the classifier boundary → feed it every label the
   classifier can emit, including edge cases.
2. Scripted episode: fixed action sequence, assert the rebuilt observation changes after each
   simulated visitor reply (catches a missing step 6–7 immediately).
3. Free run vs the table above: expect a diverse mix, not >85% of anything.
4. First pilot session before real participants.
