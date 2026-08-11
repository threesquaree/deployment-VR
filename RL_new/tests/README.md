# RL_new verification tests (E_flat_S2)

Maps to the verification ladder in `deploy_bundle/HANDOFF.md`. All scripts are
dependency-light (no pytest, no OpenAI key, no FastAPI) and run from the RL_new
folder with the study venv:

```
cd C:\Users\s3533204\Downloads\Research\Research\RL_new
..\RL\.venv\Scripts\python.exe tests\test_label_boundary.py
..\RL\.venv\Scripts\python.exe tests\test_frozen_state.py
..\RL\.venv\Scripts\python.exe tests\test_action_mix.py
```

| script | ladder step | what it pins |
|---|---|---|
| `test_label_boundary.py` | 1 | every classifier label maps onto the 8-label contract (`repeat_request -> confusion`); garbage degrades loudly to `statement`; classifier and bundle label lists are identical |
| `test_frozen_state.py` | 2 | the 31-d observation changes after every simulated visitor reply (the frozen-state collapse guard); disengaged turns collapse the legal set to `["Engage"]` |
| `test_action_mix.py` | 3 | free-run action mix vs the 67.7/20.0/12.2 Explain/Recover/Transition reference; hard tripwire: no action >85% |

Bundle smoke test (ships with the bundle, run from inside it):

```
cd deploy_bundle
..\..\RL\.venv\Scripts\python.exe run_agent_example.py
```

## Manual HTTP ladder (before a pilot)

Start `start_rl_new.bat`, then:

1. `curl http://127.0.0.1:8000/health` — must echo `model_name: E_flat_S2_ep1000`.
2. `POST /session/start`.
3. Normal `POST /turn` (a King_Caspar object name + a follow-up-style utterance)
   — expect `action_selection_source: rl_policy` and a fresh `obs_31` in the
   session `turns.jsonl`.
4. `POST /turn` with `metadata.response_type = "disengaged"` three times —
   expect `Engage/RecoverEngagement` with `available_options: ["Engage"]` twice
   (`rl_policy_recover_masked`), then the cap warning and a free policy action.
5. `POST /turn` with `metadata.is_silence_event = true` — expect
   `silence_rule_based` plus a `policy_action` counterfactual in `debug`.
6. `POST /session/end`, then check `obs_31` differs on every row of `turns.jsonl`.

Ladder step 4: one full VR pilot session before any real participant.
