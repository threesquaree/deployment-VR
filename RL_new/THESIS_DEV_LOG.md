# RL Thesis Development Log

## Purpose
This document is a research-oriented implementation log for the RL museum guide branch.

It is separate from `RL_BRANCH_LOG.md`:
- `RL_BRANCH_LOG.md` is the engineering maintenance log.
- `THESIS_DEV_LOG.md` is the thesis-facing log for architecture rationale, integration issues, experimental constraints, and implementation tradeoffs.

Use this file to support later thesis writing, especially the methodology, system design, implementation, and discussion chapters.

## Logging Rules
For each meaningful change or debugging milestone, record:
- Date
- What changed
- Why it was changed
- What problem or limitation it addressed
- What evidence was used
- What tradeoff or residual limitation remains

## Current System Scope
As of now, the RL branch is not a full-scene RL agent. It is an online RL-based dialogue branch integrated into the Unity project with the following scope:
- Baseline conversational agent remains intact.
- RL branch runs through a separate FastAPI runtime.
- RL branch currently supports only a subset of exhibits.
- Unity provides gaze-derived object context.
- OpenAI is used for final natural-language generation.
- Neo4j is no longer required online for RL mode.

## Key Design Decisions

### 2026-03-11 - Preserve Dual-Agent Architecture
What changed:
- The project was structured to keep two routes alive in parallel: the original baseline conversational agent and a new RL-based agent.

Why:
- This allows A/B comparison, preserves the original experiment route, and reduces risk while integrating the RL branch.

Evidence:
- The existing Unity project already depended on `RasaCommunication` and baseline flow.
- Replacing the baseline directly would have made debugging much harder.

Tradeoff:
- The Unity scene becomes more complex because both branches must coexist.

### 2026-03-11 - Introduce a Dedicated RL Runtime Layer
What changed:
- A separate FastAPI runtime was introduced between Unity and the RL inference code.

Why:
- The RL code already handled policy selection, prompt building, and OpenAI generation, but it did not provide production-style session handling or a Unity-facing API.
- A runtime layer was needed to normalize Unity inputs, maintain session state, log interactions, and expose stable HTTP endpoints.

Evidence:
- Existing `RLMuseumRuntime` functionality could be reused as a black-box inference unit.
- Unity previously depended on HTTP-based communication through Rasa, so an HTTP runtime was a natural fit.

Tradeoff:
- This adds another process that must be run during RL-mode testing.

### 2026-03-11 - Use a Single Active Model Config
What changed:
- RL model selection was reduced to a single `runtime_config.json` rather than a full model registry.

Why:
- The intended workflow is to evaluate one exported RL agent at a time, not to hot-switch across multiple agents in one experiment.

Evidence:
- The project goal is iterative retraining and replacement of the exported checkpoint, not multi-agent serving.

Tradeoff:
- Switching agents still requires editing config and restarting the runtime.

### 2026-03-11 - Remove Online Neo4j Dependency from RL Mode
What changed:
- RL mode was changed so session start and runtime gaze processing no longer require Neo4j.

Why:
- Live debugging showed that `GetEyeData.StartDataCollection(...)` still tried to create Neo4j actor/measure nodes before starting the RL session.
- When Neo4j was offline, the session never started and RL turns were skipped.

Evidence:
- Unity Console showed Neo4j connection failures and downstream exceptions during actor/measure creation.
- Runtime health remained at `active_sessions: 0` and Unity debug logs showed `skip=no_active_session`.

Tradeoff:
- RL mode loses online Neo4j-backed behavior traces during runtime.
- These traces must be reconstructed later from local logs if needed.

### 2026-03-12 - Prefer Stable Gaze but Fallback to Raw Gaze
What changed:
- RL turn routing was changed to prefer the stable dwell-based object/AOI, but fallback to the most recent raw gaze hit when stable focus had not yet been established.

Why:
- Stable gaze is better for grounded exhibit selection, but the original threshold caused many turns to fail if the user spoke before the dwell timer completed.
- Baseline behavior was effectively closer to immediate raw gaze.

Evidence:
- Runtime returned `No valid current exhibit` even after the session had started.
- Unity logs showed that speech dispatch happened before a stable exhibit had been established.

Tradeoff:
- This improves usability but reduces the strictness of gaze grounding in early-turn situations.

### 2026-03-12 - Normalize Unity Object Names in the Runtime
What changed:
- Runtime exhibit mapping was updated to normalize Unity object names such as `B1_Painting` before mapping to RL exhibit keys.

Why:
- Unity was not always sending canonical object IDs like `B1`; it sometimes sent full scene object names such as `B1_Painting`.
- The original runtime mapping expected exact object IDs and rejected these turns.

Evidence:
- Unity debug logs showed payloads like `current_object=B1_Painting`.
- Runtime returned `No valid current exhibit` despite the user clearly looking at a supported painting.

Tradeoff:
- Runtime mapping is now slightly more heuristic and depends on naming conventions.

### 2026-03-12 - Force `.env` Override in the RL Runtime
What changed:
- OpenAI env loading was changed to use `override=True` when reading `RL/.env`.

Why:
- The runtime still failed with `Missing OpenAI API key in env var 'api_key'` even when `RL/.env` existed and the runtime was launched from the correct directory.
- The most likely cause was an empty or stale parent-shell `api_key` masking the `.env` value.

Evidence:
- `RL/.env` existed and contained a valid key.
- Runtime continued to raise the missing-key error until env loading behavior was examined.

Tradeoff:
- Runtime now explicitly prioritizes the project-local `.env` over inherited process state.

## Integration Timeline

### 2026-03-11 - Initial RL Branch Integration
- Added a dedicated RL runtime branch under `RL/runtime_service/`.
- Added Unity-side `RLCommunication.cs` and `AgentMode.cs`.
- Kept baseline scripts intact.
- Added project-level logging through JSONL interactions and session summaries.

### 2026-03-11 - Runtime Environment Setup
- Created a dedicated RL virtual environment.
- Installed FastAPI, Uvicorn, OpenAI, dotenv, pyttsx3, neo4j, torch, numpy, and transformers.
- Confirmed runtime importability in the RL environment.

### 2026-03-11 to 2026-03-12 - Live Integration Debugging
Main observed failures during integration:
- Session never started because RL mode still depended on Neo4j actor/measure creation.
- RL requests failed with `No valid current exhibit` due to missing stable focus or non-normalized Unity object names.
- Runtime failed with missing OpenAI API key despite local `.env` existing.

Each of these failures produced concrete code changes rather than being treated as transient test issues.

## Current Known Limitations
- RL coverage is still limited to a subset of exhibits rather than the whole scene.
- Scene-level question handling without a current exhibit is not yet fully designed.
- The system currently assumes an exhibit-grounded turn model for most RL interactions.
- TTS remains Python-side local playback rather than a fully Unity-managed speech pipeline.
- Unity still contains unrelated warnings and at least one missing script on another scene object (`Testobject4`).

## Open Research / Engineering Questions
- How should the system classify scene-level questions versus exhibit-level questions?
- Should `NoExhibit` become an explicit runtime state?
- When should the system clarify versus recommend versus transition?
- How should comparative questions be handled when the user has a current gaze target but asks about the broader scene?

## Writing Use
This file should later support:
- Methodology: system architecture and design choices
- Implementation: Unity-runtime-RL integration details
- Results/Discussion: integration failures, fixes, and remaining limitations
- Future work: full-scene coverage, stronger intent routing, and improved grounding

### 2026-03-13 - Simplified Current Exhibit Resolution for the RL Branch
What changed:
- The RL branch adopted a simplified current exhibit resolution policy: `stable valid exhibit > recent raw valid exhibit > None`.
- Only the five exhibits currently supported by the RL branch (`B1`, `B2`, `B3`, `C5`, `C6`) are allowed to enter the RL current exhibit state.
- Unity-side object names are normalized before RL use, and raw gaze fallback is constrained by a short validity window rather than being carried indefinitely.

Why:
- The project is still in an integration-first phase, not a retraining phase.
- The current RL state space only supports five exhibits plus `None`, so a richer hierarchy such as dialogue carry-over, question-aware overrides, or multi-level gaze confidence would not yet change the policy input itself.
- A lightweight and explicit grounding rule is preferable at this stage because it reduces ambiguity, keeps runtime cost negligible, and makes online failures easier to interpret.

Evidence and rationale:
- Earlier debugging showed that turns failed when stable dwell had not yet been reached.
- Earlier fallback logic was useful for responsiveness but too loose because it could allow unsupported or stale visual targets to influence the RL path.
- The final v1 rule balances usability and grounding by preserving a short raw visual fallback while ensuring that only policy-supported exhibits are ever passed forward.

Tradeoff:
- This design intentionally sacrifices richer context continuity in favor of integration stability.
- It does not yet model dialogue carry-over, scene-level question routing, or explicit question-type inference.
- These remain candidates for a later v2 design, especially if evaluation shows that `None` turns or no-grounding responses are frequent.

Current interpretation for thesis writing:
- At this stage, current exhibit grounding in the RL branch is treated as a constrained visual-state resolution problem rather than a full multimodal intent-routing problem.
- The system therefore resolves to one of six policy-visible states: `B1`, `B2`, `B3`, `C5`, `C6`, or `None`.

### 2026-03-13 - Main RL Online Path Confirmed; Missing Audio Was a TTS Configuration Issue
What changed:
- End-to-end RL response generation was confirmed during a live Unity test.
- The system successfully performed exhibit grounding, RL action selection, prompt construction, and OpenAI-based response generation for a `B1` interaction.
- The remaining perceived failure was not response generation but missing audible playback, which was caused by `tts_enabled = false` in the runtime configuration.
- Runtime-side local TTS was then enabled in configuration.

Why this matters:
- This marks the first confirmation that the new RL branch is functioning as an actual online conversational path rather than only a partially integrated pipeline.
- It also clarifies an important debugging lesson for the thesis: a user-perceived failure to respond may originate from the speech realization layer even when the policy and language generation layers are already working.

Evidence:
- Unity recorded a successful `TurnResponse` with `Explain/ExplainNewFact` and mapped exhibit `Diego_Bemba`.
- The session log stored the generated answer text and updated RL coverage state.
- No HTTP error occurred in this turn.

Tradeoff / limitation:
- The system currently relies on Python-side local TTS rather than Unity-managed playback.
- This is sufficient for integration validation, but it remains a weaker deployment architecture for synchronization, interruption handling, and embodied presentation.

### 2026-03-13 - Asynchronous TTS Introduced to Decouple Speech Realization from HTTP Response Timing
What changed:
- Runtime-side local TTS was changed from a synchronous `pyttsx3.runAndWait()` call in the request path to a queued background worker model.

Why:
- Once local TTS was enabled, the system reached a new integration stage where responses were generated successfully but Unity could still time out waiting for the HTTP response.
- The blocking TTS call delayed `/turn` completion long enough for Unity to treat the request as failed, even though text generation had already succeeded.
- A later automatic prompt then collided with the still-running pyttsx3 loop, causing `run loop already started`.

Evidence:
- Unity logs showed a successful spoken response followed by `Request timeout` and then `HTTP 500 ... run loop already started`.
- This pattern is consistent with synchronous local speech playback occurring before the HTTP response is returned.

Tradeoff:
- Asynchronous local TTS improves responsiveness and avoids request-path blocking, but it weakens direct synchronization between response completion and speech completion.
- This further highlights that the current system is an integration-oriented prototype rather than a tightly synchronized embodied dialogue runtime.

### 2026-03-18 - Active Online RL Model Switched to a Centred Engagement + Broadened Novelty Variant
What changed:
- The active runtime checkpoint was changed from `H3_MDP_StateMachine.pt` to `H1_MDP_StateMachine_CentredEng_BroadNov.pt`.
- This was not a full reward redesign. The baseline reward skeleton remained intact, including `reward_mode = baseline`, `w_engagement = 1.0`, `w_responsiveness = 0.5`, and `w_conclude = 0.4`.
- The new checkpoint introduces two targeted reward refinements:
  - centred engagement: engagement is rewarded relative to the visitor's own recent dwell baseline via an EMA term
  - broadened novelty: content-progression reward is extended beyond only new-fact explanation to include repetition, clarification, and question actions, with a staleness penalty when exhibit content is exhausted

Why:
- The new checkpoint better reflects the design goal that engagement should be visitor-relative rather than driven only by absolute dwell length.
- It also better matches museum dialogue reality, where conversational progress may occur through repetition, clarification, or questioning rather than only through introducing unseen facts.

Evidence:
- The runtime configuration now points to `H1_MDP_StateMachine_CentredEng_BroadNov`.
- Online sessions after the switch report this checkpoint name in their session summaries.

Tradeoff:
- The branch still evaluates one exported model at a time, so model comparison remains operationally simple but requires explicit config switching and restart.

### 2026-03-18 - Periodic Prompting Was Deferred Until the First Successful RL Exchange
What changed:
- The RL prompting schedule in Unity was changed so periodic prompting does not begin as soon as the scene starts.
- Instead, the prompt timer is armed only after the first successful RL question-response cycle has completed.

Why:
- Immediate prompting at scene start distorted the intended interaction flow and made the guide speak before the visitor had established an interaction.
- Delaying the timer until after the first valid RL response makes automatic prompting function more like a recovery or continuation mechanism rather than an unsolicited opening turn.

Evidence:
- Earlier live tests showed `prompting_user` could be sent before a visitor had asked a first question.
- After the change, the RL route no longer begins periodic prompting until Unity has received a valid `/turn` response.

Tradeoff:
- This makes the opening phase more natural, but it also means a fully passive visitor may now receive no automatic RL prompt until at least one successful exchange has occurred.

### 2026-03-18 - Local TTS Was Reworked to Use Per-Utterance Engine Initialization
What changed:
- The runtime-side local TTS worker was changed from reusing one persistent `pyttsx3` engine to initializing a fresh engine for each utterance.

Why:
- A recurring live symptom was that an early turn could be heard but a later turn might be logged as spoken without being audibly perceived.
- Direct terminal smoke tests showed that one-shot `pyttsx3.init() -> say() -> runAndWait()` remained reliable, while the long-lived runtime path was less stable.
- This suggested that persistent engine reuse inside the long-running runtime process was a plausible instability source.

Evidence:
- Unity logs confirmed that turns were still sent and replies were still returned even when a later spoken reply was not heard.
- Runtime logs showed `queued`, `speaking`, and `finished` even in some cases where the user reported not hearing the later reply.
- Manual post-session `pyttsx3` tests continued to speak normally.

Tradeoff:
- Per-utterance initialization introduces extra startup overhead and may slightly increase latency before speech begins.
- The design is less efficient than persistent engine reuse, but it is more aligned with the empirically reliable one-shot execution pattern observed during debugging.

### 2026-03-18 - User-Facing Spoken Text Was Separated from Internal Fact-Tagged Output
What changed:
- Runtime reply handling was modified so that the raw model output can still contain fact markers such as `[KC_001]` for internal bookkeeping, while the text delivered to Unity and to local TTS is cleaned before presentation.
- The raw fact-tagged reply is now retained in debug output rather than exposed in the main user-facing text.

Why:
- Fact markers are useful for coverage accounting and later policy analysis, but hearing or displaying them directly degrades the visitor experience.
- The system therefore needed a clean separation between user-facing realization and internal traceability.

Evidence:
- Session logs already relied on extracted fact IDs to build `facts_mentioned_snapshot` and coverage state.
- Spoken output containing explicit fact tags was judged to be undesirable for live interaction quality.

Tradeoff:
- The primary `reply_text` field is now user-facing rather than a verbatim record of the raw model completion.
- To preserve analytical traceability, the raw fact-tagged text is retained separately in debug data.

### 2026-03-25 - RL Focus Handling Was Extended with an Explicit `NONE` State
What changed:
- The RL Unity path was updated so focus handling no longer only distinguishes between supported exhibit focus and transient missing data.
- A new explicit `NONE` state was introduced for cases where the visitor is not looking at any supported RL artwork for a sustained interval.
- The timing policy was set to:
  - enter a supported painting after `0.5s` of stable focus
  - retain recent raw supported focus for `1.0s`
  - enter `NONE` after `2.0s` without supported focus
- Runtime-side exhibit resolution was also updated so `NONE` is treated differently from an empty `current_object_name`: `NONE` now represents confirmed no-focus, whereas an empty string still functions as temporary missing data.

Why:
- Earlier logic was biased toward preserving the last valid exhibit and therefore made it difficult to represent the real interaction state in which the visitor is looking at the wider VR environment rather than any supported artwork.
- The system needed to preserve no-focus as a meaningful state while still tolerating short gaze loss and jitter.

Evidence:
- Unity-side preferred focus selection now returns `NONE` after sustained unsupported focus instead of indefinitely relying on recent supported gaze.
- Runtime exhibit resolution now explicitly separates `NONE` from empty input and no longer treats both as the same previous-exhibit fallback case.

Tradeoff:
- This makes the RL state more faithful to visitor attention, but it also introduces more no-focus states that may not be well represented in the training distribution.
- In practice, this is one reason to keep first-layer question routing primarily question-driven rather than gaze-driven.

### 2026-03-25 - Automatic One-Minute Prompting Was Confirmed to Be RL-Specific and Then Disabled
What changed:
- The active branch was inspected to determine which path still produced automatic `prompting_user` reminders.
- The baseline CA route was found to retain legacy `prompting_user` rules and guide actions, but not to automatically arm periodic prompting in the current Unity flow.
- The RL path was confirmed to be the only route still scheduling periodic prompting automatically.
- RL periodic prompting was then disabled by adding an explicit `enablePeriodicPrompting = false` gate in Unity.

Why:
- The project needed a clean interaction baseline without unsolicited one-minute reminders in the RL route.
- It was also necessary to distinguish between dormant legacy CA prompting code and the actually active source of periodic prompting in the live branch.

Evidence:
- Code inspection showed that periodic prompting in Unity was armed only on the RL path after a successful RL turn.
- After the change, prompt scheduling and firing on the RL side are both guarded by `enablePeriodicPrompting`.

Tradeoff:
- Disabling periodic prompting removes an automatic recovery mechanism for prolonged inactivity.
- However, it also simplifies interpretation of dialogue behavior during evaluation by reducing unsolicited system turns.

### 2026-03-25 - Auxiliary Painting Context Was Separated from Formal Fact Tracking
What changed:
- The RL prompt-generation path was extended with a second exhibit-information layer: an auxiliary painting context package.
- This auxiliary package now provides the LLM with the current painting's `painting_name`, `object_name`, and AOI-level descriptions.
- The formal fact pipeline was intentionally left unchanged. The system still constructs and tracks only the existing five formal facts per exhibit:
  - `description`
  - `more_info`
  - `artist + year`
  - `location`
  - `style`
- Auxiliary context is passed to prompt construction as reference-only context and is explicitly excluded from `facts_mentioned` and coverage accounting.

Why:
- Online behavior showed a recurring mismatch between what the user asked and what the formal fact set could answer directly.
- Many visitor questions were not actually requests for new exhibit-level facts, but for local visual details such as what the sitter is holding, wearing, or displaying.
- The existing knowledge graph already contained AOI-level descriptions for these details, but the RL generation path was not systematically surfacing them to the LLM.
- At the same time, changing the formal fact definition would have broken comparability with the existing coverage-based evaluation scheme.

Evidence:
- Code inspection confirmed that the formal fact builder in `knowledge_graph.py` currently derives exactly five tracked facts from exhibit metadata: `description`, `more_info`, `artist + year`, `location`, and `style`.
- The same KG file also contains AOI descriptions such as `Box`, `Ivory tusk`, `Cavalier hat`, `Clothes`, and `Incense Pot`, which were available in the data but not consistently available in the prompt.
- Recent session logs showed failures on questions like what a figure is holding or wearing, even when the underlying KG already contained the relevant AOI detail.

Tradeoff:
- This change improves the LLM's access to local visual detail without redefining the tracked fact space.
- However, it also creates a deliberate separation between answer quality and formal coverage: a response may now be more accurate because of auxiliary context without increasing `facts_mentioned`.
- This was accepted as the cleaner research design because it preserves the original evaluation meaning of formal fact coverage while still improving grounded response quality.

### 2026-04-02 - RL Prompting Was Reframed as a Unified Base + Action-Specific Policy Layer
What changed:
- The RL prompt stack was reorganized into a shared base prompt and per-action policy prompts.
- A single base template now carries common runtime context (current exhibit, AOI focus, image path, prior response, conversation history, and exhibit data).
- Action-specific intent is injected via `Selected action` and `Action Description`, then refined in dedicated action prompt modules.

Why:
- Earlier prompt logic had grown fragmented across fallback and inline prompt paths.
- A unified base makes action-level control explicit while preserving consistent context grounding across all turns.
- This also improves maintainability for ablation-style thesis experiments because action guidance can be modified independently from shared context framing.

Evidence:
- Runtime prompt construction now routes through a single base prompt function plus subaction handlers in `RL/prompt/`.
- Action description mapping is centralized and aligned to the active checkpoint action set.

Tradeoff:
- Prompt assembly now has more moving modules, which improves modularity but increases cross-file coordination burden during rapid iteration.

### 2026-04-02 - Explain/Repeat Strategy Moved from Forced Fact Injection to Relevance-Gated Selection
What changed:
- Added a deterministic relevance selector for `ExplainNewFact` and `RepeatFact` with threshold control (`t_low`, `t_high`).
- When relevance confidence is low, the system does not force fact insertion and can answer directly.
- Selection metadata is emitted for analysis (selected IDs, top score, low-confidence flags).

Why:
- Forced fact insertion produced brittle behavior when user queries were weakly related to available fact text.
- A relevance-gated mechanism better matches conversational quality goals while preserving fact-ID constraints when facts are actually used.

Evidence:
- New selector module is called by both explain/repeat prompt builders.
- Runtime metadata now exposes selection outcomes in structured form.

Tradeoff:
- Threshold choice introduces a new hyperparameter dependency; different thresholds can shift coverage-versus-naturalness balance.

### 2026-04-02 - Added a Verifier-and-Revision Layer for Action and Language Reliability
What changed:
- Added a second-stage verifier (judge) after draft response generation.
- Judge evaluates three axes: `action_alignment`, `language_consistency`, and `gaze_grounding`.
- Decision rule is enforced server-side: revise only when action or language score is 0.
- Added a single revision pass (at most once) rather than iterative self-correction loops.

Why:
- RL action selection is a soft control signal when final language is generated by an LLM.
- The verifier layer was added to reduce action drift and low-quality language realizations without redesigning the policy model.
- One-shot revision preserves latency bounds while adding quality control.

Evidence:
- Runtime path now executes draft -> judge -> optional revise -> final.
- Judge JSON schema validation and fallback behavior are implemented in dedicated modules.

Tradeoff:
- Additional model calls increase latency and token cost.
- Judge quality itself becomes a dependency; parse-failure fallback avoids runtime blocking but can reduce correction recall.

### 2026-04-02 - Runtime Configuration Shifted to H1 Checkpoint with Judge Controls Enabled
What changed:
- Active checkpoint was switched to `H1_MDP_Sim8_CentredEng_BroadNov_RespType.pt`.
- Runtime config now includes judge controls:
  - `judge_enabled = true`
  - `judge_fail_policy = pass`
- `model_name` label was aligned with the active checkpoint for cleaner experiment traceability.

Why:
- The branch required a checkpoint/model label consistent with the current online experiment path.
- Judge controls needed to be explicit runtime-level knobs for reproducible testing.

Evidence:
- `runtime_config.json` now points to the H1 checkpoint and includes judge settings.

Tradeoff:
- Checkpoint switching still requires runtime restart, so multi-model online comparison remains sequential rather than hot-swapped.

### 2026-04-02 - ExplainNewFact Was Reframed to Prefer Continuous Fact Progression
What changed:
- `ExplainNewFact` selection and prompting were revised so explain turns no longer drop fact use simply because text-only relevance falls below `t_low`.
- The effective behavior is now:
  - if `new_facts` is empty: answer directly and lightly suggest another exhibit
  - if at least two candidate facts exceed `t_high`: use `top1 + top2`
  - otherwise: always use `top1`
- Low-confidence explain turns were explicitly restructured into a two-sentence pattern:
  - sentence 1 briefly answers the user
  - sentence 2 adds the most relevant selected fact
  - the prompt now requires natural connection between the two sentences
- Explain metadata was extended with `second_score` and `selection_mode`.

Why:
- The project direction shifted away from treating low relevance as a reason to suppress fact delivery.
- For this branch, `ExplainNewFact` is being treated as an action whose purpose is to keep content progression active whenever unexplained facts still exist.
- This better matches the experimental intention of preserving explanatory momentum rather than maximizing narrow lexical query-fact alignment.

Evidence:
- Explain prompt modules now emit modes such as `single_top1_low` and `high_two`.
- Session logs showed many turns where fact scores were low in absolute terms, but a stable top fact still existed and could be integrated into a two-sentence answer.

Tradeoff:
- This design increases the chance of "softly forced" fact insertion on weakly related questions.
- It may improve perceived informativeness and coverage progression, but it also weakens the interpretation of selected facts as strictly relevance-qualified content.

### 2026-04-02 - Fact Usage Accounting Was Shifted from Surface Text Tags to Judge-Confirmed Realization
What changed:
- The RL branch no longer relies only on visible `[FACT_ID]` strings in the final reply to decide whether a fact has been used.
- The judge layer was extended to output `realized_fact_ids`, constrained to the selected fact set.
- Only `ExplainNewFact` and `RepeatFact` are treated as fact-bearing actions.
- Runtime fact-state updates (`facts_mentioned`, coverage, used/new fact progression) now follow judge-confirmed realization rather than raw visible tag extraction alone.
- If a revised answer is generated, the revised answer is judged again and the second judge output becomes the final accounting source.

Why:
- Once prompt behavior, revision, and user-facing text cleanup became more complex, raw output tags were no longer a sufficiently reliable proxy for what fact content had actually been realized.
- The system needed a distinction between:
  - planned fact use (`selected_fact_ids`)
  - realized fact use (`realized_fact_ids`)

Evidence:
- The runtime now records both selected and realized fact IDs in formal logs.
- Session inspection confirmed that coverage could now update from realized facts without depending only on user-visible raw markers.

Tradeoff:
- Fact accounting now depends on judge quality as well as generation quality.
- This improves interpretability of realized content but adds another inference dependency in the measurement chain.

### 2026-04-02 - RL Action Logging Was Made More Analytically Specific
What changed:
- `action_label` in RL interaction logs was changed from storing only the coarse option name to storing the full action string (for example, `Explain/ExplainNewFact`).
- `option` and `subaction` fields were retained separately.

Why:
- Logging only the option duplicated information already present in `option` and obscured the actual strategy used.
- Full action labels make turn-level policy analysis easier without changing the underlying runtime behavior.

Evidence:
- Session inspection showed that a coarse `action_label` such as `Explain` was insufficient for action-type analysis, whereas the full action string preserves directly interpretable strategy identity.

Tradeoff:
- No meaningful runtime tradeoff; this is primarily an observability improvement.

### 2026-04-02 - Unity AOI Extraction Was Generalized to Match the Active Scene's Actual Naming Scheme
What changed:
- Unity-side AOI parsing in `GetEyeData.cs` was extended so RL AOI extraction no longer depends only on the legacy `_AoI_` naming convention.
- The parser now also supports AOI-like object names already present in the active scene, such as `B1_Box`, `B2_Gilt garment`, and `C6_Ring`.
- Filtering was added to prevent non-AOI scene objects from being misread as AOIs, including `Painting`, `Text`, and painting-identity names such as `Dom Miguel`.

Why:
- Session logs showed a systematic pattern where object grounding succeeded but AOI fields remained `None`.
- Scene inspection revealed that the active scene often names local detail objects in the `B1_Box` / `B2_Gilt garment` style rather than consistently using `_AoI_`.
- Without this change, the RL branch could not preserve AOI information even when the user was visually targeting meaningful subregions.

Evidence:
- Raw session files showed populated object IDs but empty AOI fields.
- Scene inspection found AOI-like object names for supported RL exhibits that were incompatible with the previous parser.

Tradeoff:
- AOI parsing is now more heuristic and tied more closely to the scene's naming conventions.
- This improves practical grounding in the current scene, but it also increases dependence on scene-asset consistency rather than on one explicit legacy naming format.
