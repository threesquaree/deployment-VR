# RL Branch Log

## 2026-03-11 - Initial Plan and Branch Setup

Author: Codex

Summary:
- Added an RL-only runtime branch design that keeps the baseline conversational agent intact.
- Chosen runtime shape: Unity -> FastAPI runtime -> `RLMuseumRuntime` -> OpenAI -> optional Python local TTS.
- Chosen log shape: one JSONL interaction per turn, one session summary at session end, offline Neo4j export later.

Confirmed decisions:
- Baseline conversational agent stays unchanged.
- RL route does not require Rasa online.
- RL route does not require Neo4j online.
- `runtime_config.json` is the single active model config.
- Changing exported RL agents means updating config and restarting runtime.
- Unity owns stable gaze and dwell logic.
- RL runtime does not auto-fallback to baseline on failure.
- RL runtime uses its own `.env` and Python environment.

Planned files:
- `runtime_config.json`
- `runtime_service/`
- `tools/export_logs_to_neo4j.py`
- `VR_RCEA/VR/Assets/MyScripts/RLCommunication.cs`

Validation target:
- `uvicorn runtime_service.api:app --host 127.0.0.1 --port 8000`
- Unity RL mode talking to local runtime without touching the baseline path

Notes for maintainers:
- Keep appending to this file. Do not rewrite prior entries.
- Record the date, author, change summary, impact scope, and validation result for every future change.

## 2026-03-11 - Runtime Service and Unity RL Route Implemented

Author: Codex

Summary:
- Added `runtime_config.json`, `requirements-runtime.txt`, `.env.example`, and `runtime_service/` for the RL branch.
- Added `RLCommunication.cs` and `AgentMode.cs`.
- Patched `GetEyeData.cs` to route baseline vs RL without modifying `RasaCommunication.cs`.
- Added JSONL logging, session summary logging, and a basic offline Neo4j export script.

Impact scope:
- New RL runtime branch only.
- Baseline route remains present and still uses `RasaCommunication` when `AgentMode.Baseline` is selected.

Validation:
- Python syntax check passed for new RL Python files via `python -m py_compile`.
- Runtime import currently blocked in the local environment because `fastapi` is not installed yet.

Follow-up:
- Create `RL/.env` from `.env.example`.
- Install `RL/requirements-runtime.txt` into the RL virtual environment.
- In Unity, assign `AgentMode`, `RLCommunication`, and `outputText` in the inspector before testing RL mode.

## 2026-03-11 - RL Environment Installed

Author: Codex

Summary:
- Created `RL/.venv`.
- Installed runtime web dependencies: FastAPI, Uvicorn, OpenAI, python-dotenv, pyttsx3, neo4j.
- Installed model/runtime dependencies: torch, numpy, transformers.

Validation:
- `from runtime_service.api import app` now succeeds in `RL/.venv`.
- `import torch, fastapi, transformers` succeeds in `RL/.venv`.
- Transformers attempted to reach Hugging Face for `bert-base-uncased`; network access is blocked in this environment, but the current code falls back and does not stop runtime import.

Remaining setup:
- Create `RL/.env` with the OpenAI API key.
- If you want fully local BERT assets, pre-cache `bert-base-uncased`; otherwise the recognizer will use its fallback path when download access is unavailable.

## 2026-03-11 - RL .env Created

Author: Codex

Summary:
- Created `RL/.env` using the existing OpenAI key format already used by the baseline CA branch.
- RL runtime no longer needs to rely on `CA/original/.env` at run time.

Validation:
- `RL/.env` now exists and matches the expected `api_key=...` format used by `RL/prompt/openai_generator.py`.

## 2026-03-11 - Scene Naming Update

Author: Codex

Summary:
- Renamed the scene object `RasaManager` to `AgentManager` in `teleport_area_version.unity` to reflect dual baseline/RL use.

Validation:
- The object name in `teleport_area_version.unity` now uses `AgentManager`.
## 2026-03-11 - RL Runtime Decoupled from Neo4j Start Path

Author: Codex

Summary:
- Live debugging showed RL sessions were never starting because GetEyeData.StartDataCollection(...) still created Neo4j actor/measure nodes before calling rl.StartSession(...).
- Updated GetEyeData.cs so AgentMode.RL starts the RL session directly and does not require Neo4j actor/measure creation.
- Updated RL mode to skip ProcessDatabaseQueries(...) entirely so runtime gaze processing no longer depends on Neo4j being online.

Impact scope:
- RL route only.
- Baseline route keeps the existing Neo4j-backed start and gaze write behavior.

Validation:
- Runtime diagnosis before the change showed active_sessions: 0, skip=no_active_session, and Unity Neo4j connection failures.
- After this change, RL mode should be able to start a session and record locally even when Neo4j is offline.

## 2026-03-12 - RL Turn Object Selection Fallback Added

Author: Codex

Summary:
- Updated RL turn routing in GetEyeData.cs to prefer the stable dwell-based object/AOI, but fall back to the latest raw gaze hit when no stable focus has been established yet.
- Applied the same fallback to periodic RL prompting so RL mode behaves closer to the baseline scene flow.

Impact scope:
- RL route only.
- Baseline route continues using its original immediate gaze-to-Neo4j behavior.

Validation:
- This change addresses runtime 400 responses caused by missing current_exhibit when the visitor speaks before dwelling on a mapped exhibit for the full stability threshold.

## 2026-03-12 - RL Turn Payload Logging Added

Author: Codex

Summary:
- Added explicit Unity-side debug logging in RLCommunication.cs for the final turn payload fields sent to the runtime.
- The debug log now records user_text, current_object_name, and current_aoi_name at dispatch time.

Impact scope:
- RL route only.
- No baseline behavior changes.

Validation:
- This change is intended to make a single Unity test run sufficient to diagnose whether exhibit selection is failing before or after the HTTP request reaches the runtime.

## 2026-03-12 - Runtime Object Name Normalization Added

Author: Codex

Summary:
- Live Unity logs showed RL turns were being sent with object names like B1_Painting, while the RL mapping only recognized canonical object IDs like B1.
- Updated the runtime mapping layer to normalize Unity object names before exhibit lookup.
- The runtime now accepts canonical IDs, names with _AoI_ suffixes, and names whose leading token is a supported object ID.

Impact scope:
- RL runtime only.
- Unity no longer needs to pre-normalize B1_Painting-style names for exhibit mapping to succeed.

Validation:
- This change targets the observed 400 responses where Unity sent current_object=B1_Painting and the runtime rejected the turn with no valid current exhibit.

## 2026-03-12 - Runtime .env Override Enabled

Author: Codex

Summary:
- Updated RL OpenAI environment loading to use `override=True` when reading `RL/.env`.
- This prevents an empty or stale `api_key` in the parent shell environment from masking the valid key stored in `RL/.env`.

Impact scope:
- RL runtime only.
- No Unity-side changes.

Validation:
- This change targets the observed case where the runtime was launched from `RL/` with a valid `.env` present but still returned `Missing OpenAI API key in env var 'api_key'`.

## 2026-03-13 - Current Exhibit Resolution Scheme v1 Implemented

Author: Codex

Summary:
- Updated Unity-side RL current exhibit selection to follow a strict v1 rule: `stable valid exhibit > recent raw valid exhibit > None`.
- Restricted RL-bound visual grounding to the currently supported exhibit set only: `B1`, `B2`, `B3`, `C5`, `C6`.
- Added normalization on the Unity side so scene object names such as `B1_Painting` or `C6_AoI_Ring` collapse to canonical RL object IDs before being used as current exhibit candidates.
- Added a short raw fallback window (`rawFocusFallbackWindowSeconds = 1.0`) so the latest valid raw gaze hit can support a turn when stable dwell has not yet been reached, without persisting indefinitely.

Impact scope:
- RL route only.
- Baseline route remains unchanged.

Implementation details:
- `stableCurrentObjectName` is now only populated for supported RL objects.
- The latest valid raw RL object/AOI is tracked separately from generic `lastFocusedObject`.
- `GetPreferredCurrentObjectName()` now returns only:
  1. stable supported RL exhibit
  2. recent raw supported RL exhibit within the fallback window
  3. empty string, which maps downstream to `None`
- Unsupported objects no longer enter the RL current exhibit path.

Why this change was made:
- The previous fallback behavior was too permissive because it could reuse any recent raw gaze object, including unsupported scene objects.
- The RL state space currently only supports five exhibit IDs plus `None`, so a more complex carry-over design would have added runtime complexity without increasing the information actually sent to the policy.

Validation target:
- In RL mode, Unity should now send only canonical supported exhibit IDs or an empty current object.
- This should reduce invalid exhibit grounding while keeping early-turn speech usable before stable dwell completes.

Residual limitation:
- This v1 scheme still does not include dialogue carry-over or question-type-aware routing.
- `None` remains a valid no-grounding state, but downstream no-exhibit handling still needs separate evaluation.

## 2026-03-13 - RL Branch End-to-End Text Generation Confirmed, TTS Enabled

Author: Codex

Summary:
- Confirmed that the Unity -> runtime -> RL -> OpenAI main path is now working end to end.
- A live RL turn for `B1` successfully produced a mapped exhibit (`Diego_Bemba`), selected `Explain/ExplainNewFact`, and generated a natural-language reply that was written to the session log.
- The lack of audible output was traced to configuration rather than generation failure: `tts_enabled` in `runtime_config.json` was still set to `false`.
- Enabled runtime-side local TTS by updating `runtime_config.json` to set `tts_enabled` to `true`.

Impact scope:
- RL runtime only.
- Baseline route remains unchanged.

Validation:
- Unity debug log recorded a successful `TurnResponse` instead of `LocalError`.
- Session log `50cd66a91df543b4b3d2e66f74969dcd.jsonl` contains a completed interaction record with `reply_text`, action metadata, and coverage update.

Operational note:
- Runtime must be restarted after this config change for local TTS playback to take effect.

## 2026-03-13 - Runtime TTS Made Asynchronous

Author: Codex

Summary:
- Live testing after enabling local TTS showed that the main RL path was working, but `/turn` responses could still time out in Unity when runtime-side TTS was enabled.
- The root cause was synchronous Python TTS execution inside the HTTP request path: the runtime generated the reply, then blocked inside `pyttsx3.runAndWait()` before returning the HTTP response.
- This caused Unity request timeouts and allowed a later periodic `prompting_user` turn to overlap with an already active pyttsx3 run loop, producing `run loop already started`.
- Updated `LocalTTS` in `runtime_service/service.py` to use a background worker thread and a queue so speech playback no longer blocks `/turn` responses.

Impact scope:
- RL runtime only.
- No Unity-side behavior changes required.

Validation:
- `python -m py_compile runtime_service/service.py` passed after the change.
- The fix specifically targets the observed sequence: successful audible playback, followed by Unity request timeout, followed by `run loop already started` on the next turn.

Operational note:
- Restart the FastAPI runtime after this code change before retesting.

## 2026-03-18 - Active RL Model Switched to Centred Engagement + Broadened Novelty Checkpoint

Author: Codex

Summary:
- Updated the active runtime checkpoint in `runtime_config.json` from the previously used `H3_MDP_StateMachine.pt` to `H1_MDP_StateMachine_CentredEng_BroadNov.pt`.
- The new checkpoint keeps the baseline reward structure (`reward_mode = baseline`, `w_engagement = 1.0`, `w_responsiveness = 0.5`, `w_conclude = 0.4`) but adds two reward refinements:
  - centred engagement: reward is based on `dwell_t - EMA(dwell)` rather than raw dwell alone
  - broadened novelty: novelty credit now extends beyond `ExplainNewFact` to include repetition, clarification, and question-asking with a staleness penalty once content is exhausted

Impact scope:
- RL runtime only.
- No baseline route changes.

Validation:
- Active runtime sessions after the config update report `model_name = H1_MDP_StateMachine_CentredEng_BroadNov` in session summaries.
- Online Unity tests after restart produced valid `TurnResponse` records under the new checkpoint.

Operational note:
- Switching exported RL agents still requires editing `runtime_config.json` and restarting the FastAPI runtime.

## 2026-03-18 - Automatic Prompting Delayed Until First Successful RL Exchange

Author: Codex

Summary:
- Updated periodic RL prompting in `GetEyeData.cs` so prompt timing does not begin at scene entry.
- The periodic prompt schedule is now armed only after the user completes a first successful RL turn and Unity receives a valid `/turn` response.

Impact scope:
- RL route only.
- Baseline route behavior remains unchanged.

Validation:
- The RL branch no longer auto-speaks immediately on session start.
- Periodic prompting begins only after the first confirmed RL response has been received.

## 2026-03-18 - Local TTS Changed to Per-Utterance Engine Initialization

Author: Codex

Summary:
- Updated `LocalTTS` in `runtime_service/service.py` to stop reusing one long-lived `pyttsx3` engine across the whole runtime process.
- Each queued utterance now initializes its own `pyttsx3` engine, sets rate, speaks once, and then discards that engine.

Why this change was made:
- Live testing showed a pattern where the first spoken turn was audible but a later turn could be logged as spoken without being heard.
- Manual one-shot `pyttsx3` tests remained stable, suggesting that engine reuse inside the long-running runtime process was the more likely instability source.

Impact scope:
- RL runtime only.
- No Unity-side API changes.

Validation:
- Runtime-side local TTS still logs `queued`, `speaking`, and `finished` events after the change.
- The implementation now matches the per-run initialization pattern that succeeded in direct terminal smoke tests.

## 2026-03-18 - User-Facing Reply Text Decoupled from Internal Fact Tag Tracking

Author: Codex

Summary:
- Updated runtime reply handling so fact-tagged raw model output is preserved for internal state tracking, while user-facing reply text is cleaned before being returned to Unity or spoken via local TTS.
- Bracketed fact IDs such as `[KC_001]` are removed from `reply_text` and from spoken output, but retained in `debug.raw_reply_text`.

Impact scope:
- RL runtime only.
- Fact counting, coverage tracking, and downstream analysis remain based on the raw fact-tagged output.

Validation:
- Runtime continues to extract and record mentioned fact IDs in `facts_mentioned_snapshot`.
- User-facing reply text no longer needs to expose or vocalize fact markers.

## 2026-03-25 - Explicit `NONE` Focus State Added to RL Gaze Handling

Author: Codex

Summary:
- Updated Unity-side RL focus handling in `GetEyeData.cs` so unsupported or absent gaze targets can resolve to an explicit `NONE` state rather than only decaying into empty focus.
- The focus timing policy is now:
  - enter painting after `0.5s` of stable supported focus
  - keep recent raw supported focus for `1.0s`
  - enter `NONE` after `2.0s` without supported focus
- Updated runtime handling so `NONE` is treated as an explicit no-focus signal, while an empty `current_object_name` still means temporary missing data and may fall back to the session's previous exhibit.

Impact scope:
- RL route only.
- No baseline route behavior changes.

Validation:
- Unity now emits `NONE` from `GetPreferredCurrentObjectName()` once unsupported focus persists beyond the configured threshold.
- Runtime `_resolve_current_exhibit()` distinguishes `NONE` from an empty string and no longer collapses both cases into previous-exhibit fallback.

Operational note:
- This change preserves no-focus information in the RL path, but the current question-routing design may still choose not to use gaze as a first-layer routing signal.

## 2026-03-25 - Automatic RL Prompting Disabled After Verifying Branch Behavior

Author: Codex

Summary:
- Reviewed automatic `prompting_user` behavior across the baseline CA route and the RL route.
- Confirmed that the baseline CA side still contains `prompting_user` rules and proactive guide logic, but does not currently arm periodic prompting automatically in the active Unity flow.
- Confirmed that the RL route was the only path still arming periodic prompting in the active branch.
- Added `enablePeriodicPrompting = false` in `GetEyeData.cs` so RL no longer auto-sends periodic `prompting_user` turns.

Impact scope:
- RL route only.
- Baseline route remains functionally unchanged.

Validation:
- The active Unity RL path now guards both prompt scheduling and prompt firing behind `enablePeriodicPrompting`.
- RL no longer auto-prompts after the first successful turn unless periodic prompting is explicitly re-enabled in code or inspector configuration.

Operational note:
- The CA branch still retains legacy `prompting_user` rules and guide actions for compatibility, but they are not currently the source of automatic periodic prompting in the active setup.

## 2026-03-25 - Auxiliary Exhibit Context Added Without Changing Formal Fact Tracking

Author: Codex

Summary:
- Added a separate auxiliary exhibit context layer for RL prompt generation.
- Kept the formal fact system unchanged: tracked facts, fact IDs, `facts_mentioned`, and coverage counting still use only the existing five formal exhibit facts.
- Updated `knowledge_graph.py` and `rl_runtime.py` so the prompt builder now receives the current painting's `painting_name`, `object_name`, and AOI-level descriptions as non-tracked reference context.
- Updated `dialogue_planner.py` so this auxiliary context is exposed to the LLM as reference-only context and explicitly does not create new tracked fact IDs.

Impact scope:
- RL runtime prompt-generation layer only.
- RL policy selection, state construction, action selection, and formal fact coverage accounting remain unchanged.

Validation:
- `python -m py_compile` passed for `src/utils/knowledge_graph.py`, `src/utils/dialogue_planner.py`, and `inference/rl_runtime.py`.
- Runtime-side smoke check confirmed that `get_auxiliary_context(...)` returns painting title, object name, and AOI descriptions for supported exhibits.

Operational note:
- Auxiliary exhibit context is intended to improve local visual-detail answers such as held objects, clothing, hats, and ornaments without inflating `facts_mentioned` or altering thesis-side coverage metrics.

## 2026-04-02 - RL Prompt Stack Modularized with Unified Base Prompt

Author: Codex

Summary:
- Refactored RL prompt construction into a unified base prompt plus per-subaction prompt modules.
- Added `prompt/base_prompt.py` as the shared prompt skeleton, including `[System Role]`, `[RL Guidance]`, `[Current Context]`, `[User Input]`, and response constraints.
- Updated `src/utils/dialogue_planner.py` to route subactions to dedicated files under `RL/prompt/`.
- Kept action descriptions centralized in `prompt/action_descriptions.py` and aligned with the active checkpoint action space.

Impact scope:
- RL runtime prompt-generation path only.
- Baseline CA path remains unchanged.

Validation:
- `python -m py_compile` passed for `src/utils/dialogue_planner.py` and prompt modules.
- Runtime still returns prompt-driven responses with preserved action metadata.

## 2026-04-02 - Explain/Repeat Fact Relevance Selection Added

Author: Codex

Summary:
- Added relevance-based fact selection for `ExplainNewFact` and `RepeatFact` via `prompt/fact_selector.py`.
- Implemented threshold policy (`t_low`, `t_high`) so low-confidence turns do not force fact insertion.
- Added structured selection metadata outputs (`selected_fact_ids`, `top_score`, low-confidence flags) for downstream analysis.

Impact scope:
- RL explanation strategy prompting only.
- No changes to baseline CA path.

Validation:
- `python -m py_compile` passed for `prompt/fact_selector.py`, `prompt/ExplainNewFacts.py`, and `prompt/RepeatFact.py`.
- Runtime prompt generation now includes threshold-conditioned behavior for explain/repeat paths.

## 2026-04-02 - Judge + One-Shot Revision Pipeline Added (GPT-5.4)

Author: Codex

Summary:
- Added a verifier pass after draft generation in RL runtime.
- New modules:
  - `prompt/judge.py` (verifier prompt)
  - `prompt/judge_schema.py` (JSON parsing and validation)
  - `prompt/revise.py` (single-pass revision prompt)
- Extended `prompt/openai_generator.py` with:
  - `generate_judge_json(...)`
  - `generate_revision_text(...)`
- Updated `inference/rl_runtime.py` to run:
  - draft generation
  - judge scoring
  - at most one revision when `action_alignment==0` or `language_consistency==0`

Impact scope:
- RL runtime generation path only.
- Baseline CA path remains unchanged.

Validation:
- `python -m py_compile` passed for new prompt modules and updated runtime files.
- Runtime now returns final response after judge gate with at-most-once revision behavior.

## 2026-04-02 - Runtime Config Updated for Judge Controls and H1 Checkpoint

Author: Codex

Summary:
- Updated `runtime_config.json` with:
  - `judge_enabled: true`
  - `judge_fail_policy: "pass"`
- Switched active RL checkpoint to:
  - `H1_MDP_Sim8_CentredEng_BroadNov_RespType.pt`
- Updated `model_name` to:
  - `H1_MDP_Sim8_CentredEng_BroadNov_RespType`

Impact scope:
- RL runtime configuration only.
- Requires runtime restart to take effect.

Validation:
- Config file readback confirms updated checkpoint path and model name.

## 2026-04-02 - ExplainNewFact Selection Logic Expanded and Two-Fact High-Confidence Mode Enabled

Author: Codex

Summary:
- Updated `prompt/fact_selector.py`, `prompt/ExplainNewFacts.py`, and `src/utils/dialogue_planner.py` to expand `ExplainNewFact` behavior.
- `ExplainNewFact` now uses three effective cases:
  - `new_facts` empty -> answer directly and lightly suggest another exhibit
  - at least two facts above `t_high` -> allow `top1 + top2`
  - all other cases -> always use `top1`
- Low-confidence explain turns no longer suppress fact use; they now follow a fixed two-sentence pattern:
  - sentence 1 answers the user briefly
  - sentence 2 adds the most relevant selected fact
  - prompt explicitly requires the two sentences to connect naturally
- Enabled `allow_top2_high = true` in the live explain prompt route.
- Added new explain metadata fields:
  - `second_score`
  - `selection_mode`

Impact scope:
- RL explanation prompt generation only.
- No baseline CA path changes.

Validation:
- `python -m py_compile` passed for `prompt/fact_selector.py`, `prompt/ExplainNewFacts.py`, and `src/utils/dialogue_planner.py`.
- Runtime logs now show `selection_mode` values such as `single_top1_low` and `high_two`, and two-fact explain turns can be observed when two scores exceed `t_high`.

## 2026-04-02 - Fact Realization Tracking Moved to Judge Output

Author: Codex

Summary:
- Extended the RL judge path so fact usage is no longer inferred only from visible `[FACT_ID]` markers in final text.
- Updated:
  - `prompt/judge.py`
  - `prompt/judge_schema.py`
  - `inference/rl_runtime.py`
  - `runtime_service/service.py`
- Judge now outputs `realized_fact_ids`.
- Only `ExplainNewFact` and `RepeatFact` are treated as fact-bearing actions.
- Runtime fact usage and coverage updates now use judge-confirmed `realized_fact_ids`.
- If a revision occurs, the system re-judges the revised response and uses the final judge result as the source of truth.

Impact scope:
- RL runtime logging and fact-accounting path only.
- Baseline CA path remains unchanged.

Validation:
- `python -m py_compile` passed for judge modules, runtime, and service.
- Runtime session logs now record both `selected_fact_ids` and `realized_fact_ids` in `judge.jsonl` and `generation_trace.jsonl`.
- Coverage updates were confirmed to follow realized facts rather than only visible raw text markers.

## 2026-04-02 - Interaction Log `action_label` Changed to Full Action String

Author: Codex

Summary:
- Updated `runtime_service/service.py` so `action_label` now stores the full action string rather than only the coarse option.
- The log now records values such as `Explain/ExplainNewFact` in `action_label`.
- Existing `option` and `subaction` fields remain unchanged.

Impact scope:
- RL interaction logging only.
- No prompt-generation or policy-selection changes.

Validation:
- `python -m py_compile runtime_service/service.py` passed.
- New interaction logs now preserve a non-redundant action label that matches the selected action string.

## 2026-04-02 - Unity AOI Parsing Extended Beyond Legacy `_AoI_` Names

Author: Codex

Summary:
- Updated `VR_RCEA/VR/Assets/MyScripts/GetEyeData.cs` so Unity RL AOI parsing no longer depends only on the legacy `_AoI_` naming pattern.
- Added support for scene object names already present in the active scene, such as:
  - `B1_Box`
  - `B2_Gilt garment`
  - `C6_Ring`
- Added filtering so non-AOI targets are not misclassified, including:
  - `Painting`
  - `Text`
  - painting-identity names such as `Dom Miguel`

Impact scope:
- Unity RL gaze-to-AOI extraction only.
- Baseline CA prompt path and RL runtime mapping remain unchanged.

Validation:
- Text-level inspection confirmed the new extraction path is used at both AOI parsing sites in `GetEyeData.cs`.
- Scene inspection showed that the active Unity scene contains AOI-like object names in the `B1/B2/C6` style rather than relying consistently on `_AoI_` suffixes.

## 2026-08-02 - Runtime migrated to study agent E_flat_S2 (deploy_bundle)

Author: Claude Code

Summary:
- Replaced the deadend_fix_v1 (158-d SMDP, DialogueBERT) serving path with the
  E_flat_S2 contract from `deploy_bundle/HANDOFF.md`: flat 31-d observation,
  6 actions, deterministic argmax, masks from the checkpoint's own summary.json.
- New `inference/bundle_loader.py` imports the parity-tested bundle modules
  byte-identical (sys.path shim) and hosts the classifier boundary
  (`to_contract_label`: repeat_request -> confusion, then strict validation).
- `inference/rl_runtime.py` decision half rewritten around `decide()`
  (WorldState -> dialogue_masks -> state_builder_31d -> masked argmax); the
  policy now runs on EVERY turn (silence-forced ones included) so the LSTM
  hidden trajectory sees every step; NLG/judge/fact-update half unchanged.
- Deleted `inference/test_model.py` and `inference/state_builder.py`
  (explicitly forbidden by HANDOFF; the cause of the original VR collapse).
- Forced recovery is a mask again (rule 7), not a policy bypass:
  visitor_disengaged = (label == "disengaged") per turn, no latch; deployment
  guardrail kept: after 2 consecutive masked recoveries the flag is passed
  False for one turn (logged, `max_consecutive_forced_recover`).
- Dropped the clarification_request->confusion state remap (valid contract
  label now enters the one-hot unchanged); dwell fixed at 0.5/0.0 per HANDOFF.
- `runtime_config.json`: model_name E_flat_S2_ep1000, checkpoint + summary
  paths point into deploy_bundle/; retired behaviour keys now raise at startup.
- NLG checklist (b): non-Explain turns now receive the current exhibit's
  un-mentioned facts (with [FACT_ID] tags) via `_build_enhanced_context_section`.
- New `tests/`: label boundary, frozen-state (anti-collapse), free-run action
  mix (70.0/9.0/21.0 Explain/Recover/Transition vs reference 67.7/20.0/12.2,
  all inside HANDOFF tripwires). Full HTTP ladder verified on port 8010:
  masked recovery x2 -> cap release, silence counterfactual, obs_31 unique
  every turn.

Validation target:
- `tests\README.md` for the ladder; one VR pilot session before participants.

## 2026-08-03 - Pilot session review + spatial transition targets

Author: Claude Code

Pilot session rl_7409c209...18-00-59 (25 turns) reviewed against HANDOFF:
- Action mix healthy for a fully engaged visitor (77/23 Explain/Transition on
  policy turns; Recover requires a disengaged label, which never occurred).
- Silence budget worked as configured: fired once at King_Caspar, further
  events there blocked by max_silence_per_exhibit=1 (kept at 1 by decision).
- Transition targets criss-crossed the room (KG insertion order). Fix:
  `exhibit_walk_order` in runtime_config.json (physical order
  B1->B2->B3->C5->C6 = Diego_Bemba, Dom_Miguel, Pedro_Sunda, Turban,
  King_Caspar, confirmed by Nayan); `_pick_transition_target` now suggests the
  physically closest exhibit with unseen facts (tie: more remaining facts).
  Parity-free: the target never enters the observation. Regression test:
  `tests/test_transition_target.py`.

## 2026-08-04 - Bundle swapped to F2_flat_learn_both (E_flat_S2 -> deploy_bundle_old/)

Author: Claude Code

Nayan replaced deploy_bundle/ with the F2_flat_learn_both agent (2026-08-04
HANDOFF, superseding E_flat_S2; old bundle kept as deploy_bundle_old/). All
code files (dialogue_masks, state_builder_31d, agent, networks, KG json) are
byte-identical to the previous bundle -- only checkpoint_ep1000_model.pt and
summary.json changed, so the runtime picked the new agent up via its existing
from_summary()/checkpoint paths with no decision-code changes.

- New mask flags (from summary.json): force_recover ON; stall mask OFF and
  clarify-misfire mask OFF (both retired -- the policy LEARNED the dead-end
  transition, 96.0% by choice, and ClarifyFact is now always legal).
- Changes: model_name -> F2_flat_learn_both_ep1000 (runtime_config.json,
  start_rl_new.bat, /health expectation); docstring touch-ups.
- Re-verified: bundle smoke test (dead-end scenario now shows 4 legal options
  with SummarizeAndSuggest CHOSEN, the F2 signature), all 4 tests pass
  (mix 70.0/9.0/21.0, inside tripwires), service boots with the new flags.
- Behavioural deltas to expect in VR vs E_flat_S2: at an exhausted painting
  the legal set stays wide (no forced-transition collapse), and ClarifyFact
  can fire on any label, not just confusion/clarification_request.

## 2026-08-05 - Response-type classifier review + two fixes

Author: Claude Code

Reviewed the classifier against 207 real turns from the Aug 3-5 pilots.
Common labels are good (acknowledgment bucket clean, repeat_request caught
twice and mapped correctly, 0 rules_v1 fallbacks in 183 speech turns).
Note for interpretation: under F2, mask_stall and mask_clarify are OFF, so
`disengaged` is now the ONLY label that changes the legal action set;
everything else only shifts the observation one-hot.

Fixed:
- FAREWELLS WERE SCORED `disengaged`. 2 of 4 disengaged labels in the pilots
  were goodbyes ("thank you very much ... bye bye"), each forcing
  Engage/RecoverEngagement at a visitor who was leaving satisfied -- twice
  back-to-back in the 11:09 session. Training's `disengaged` meant lecture
  fatigue MID-tour, never session end. prompt/response_type_prompt.py now
  excludes farewells explicitly (revision history added to its docstring;
  frozen from the first participant onward).
  Verified by replaying the exact pilot turns through the live classifier:
  both goodbyes -> acknowledgment, genuine "I'm done with this conversation"
  -> still disengaged, 7/8 synthetic controls exact (the 8th differed only
  between question/follow_up_question, which is behaviourally inert).
- RESTORED clarification_request -> confusion at the boundary. The E_flat
  migration dropped this remap because the contract lists the label, which
  missed that the SIMULATOR never produced it (p_clar: 0.0 in every run incl.
  F2), so obs[27] was zero for all of training; deployment was setting it live
  on 2.9% of turns. Now collapsed onto `confusion` (active ~6.7% in training).
  Raw label still logged in response_type. tests/test_label_boundary.py
  extended to pin both remaps and assert every remap target is a contract label.

Known, not changed:
- The TelemetryGate has never fired (0/207): a quiet visitor looking away trips
  Unity's 40s silence timer first, which short-circuits before the gate. All
  disengagement detection is currently verbal.
- `disengaged` runs 1.9% deployed vs 12.9% in training, which is why live
  Recover lands ~9% against the HANDOFF reference 20%. Classifier-population
  effect, not an integration fault.
- rules_v1 fallback agrees with the LLM only 39% of the time (its acknowledgment
  match fails on trailing punctuation -- "Okay." falls through to statement).
  Never exercised so far; a mid-study OpenRouter outage would degrade labels.

## 2026-08-10 - Study data reorganised for analysis (both arms)

Author: Claude Code

Study closed. `data/reorganize_sessions.py` (dry-run default, --apply to run)
reorganised data/sessions into an analysis-ready layout. All moves/renames on
one volume; nothing deleted; reversible from the manifests.

Final n: **15 RL participants (P21-P35, 404 turns)**, **20 baseline (P01-P20,
23 sessions, 227 turns)**. RL was NOT 20 as hoped.

- rl/ 15 + baseline/ 23 keepers, each with participants.csv (join key);
  meta.json additively gained participant_number / session_index / agent_version.
- rl_excluded/ 13, baseline_excluded/ 8 (each + excluded_manifest.csv),
  baseline_aggregates/ 23, test data/{rl 20, baseline 7}.
- Accounting verified: 48 RL + 65 baseline - 4 merged = 109 folders, no folder
  in two buckets; byte delta 15,265 B fully explained by the 4 new manifests
  (11,532 B) + 38 re-serialised meta.json files (3,733 B).

Key finding driving the exclusions: **the July 29 RL sessions (ids 21-26) ran
the OLD pre-migration 158-d SMDP agent** (turns.jsonl has rng_seed and
forced_recover_on_disengage, no obs_31), so they were superseded by the August
re-runs. Every kept RL session ran F2_flat_learn_both — asserted via obs_31
present on turn 1. No participant ever ran E_flat_S2.

Also fixed: 4 rl_* folders had their files SPLIT across sessions/rl and
sessions/baseline (neither copy complete) - merged, with the conflicting
second meta.json preserved as meta.baseline.json.
