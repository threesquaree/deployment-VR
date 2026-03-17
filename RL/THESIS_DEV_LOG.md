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
