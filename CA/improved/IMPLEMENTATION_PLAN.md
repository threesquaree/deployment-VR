# CA Improved Implementation Plan

## Goal

Build a new `CA/improved/` line that:

- keeps `Rasa`
- removes online `Neo4j` dependency
- uses local JSON for static knowledge
- uses local in-memory session state for runtime context
- uses local JSONL logging for conversation records

This plan is intentionally staged. Each batch has:

- scope
- concrete tasks
- checks
- exit criteria
- next batch

## Progress

- Completed: Batch 0, Batch 1, Batch 2, Batch 3, Batch 4, Batch 5, Batch 6, Batch 7, Batch 8
- In progress: Batch 9 regression and end-to-end validation

## Core Constraints

1. Do not import runtime code from `CA/original/`.
2. Do not copy the whole `CA/original/` directory.
3. Replace `GRAPH.*` in batches, not all at once.
4. Keep prompt structure as stable as possible during migration.
5. Do not mix static KG, runtime session state, and logs in one layer.

## Target Structure

```text
CA/
  original/
  improved/
    README.md
    IMPLEMENTATION_PLAN.md
    actions.py
    config.yml
    credentials.yml
    endpoints.yml
    domain.yml
    data/
      nlu.yml
      rules.yml
      stories.yml
    local_runtime/
      models.py
      knowledge_base.py
      session_store.py
      conversation_logger.py
    knowledge/
      museum_knowledge_graph.json
      object_aoi_mapping.json
```

## Responsibility Split

### KnowledgeBase

Handles static knowledge only:

- painting metadata
- AOI metadata
- painting to AOI relationships
- object name and AOI normalization

### SessionStore

Handles runtime state only:

- session creation
- current object
- current AOI
- dialogue history
- last agent reply
- last interaction time

### ConversationLogger

Handles persistent local logging only:

- session start
- turn logs
- session end

## GRAPH Replacement Map

### Replace with `KnowledgeBase`

- `GRAPH.get_graph_data()`
- static exhibit lookup logic
- static AOI lookup logic
- painting image lookup
- object information lookup
- AOI information lookup

### Replace with `SessionStore`

- `GRAPH.creating_an_agent(...)`
- `GRAPH.get_user_id()`
- `GRAPH.get_agent_id()`
- `GRAPH.get_last_obj_id(...)`
- `GRAPH.get_last_aoi_id(...)`
- `GRAPH.conversation_history(...)`
- `GRAPH.get_last_agent_response(...)`
- `GRAPH.get_last_time_of_interaction(...)`

### Replace with `ConversationLogger`

- `GRAPH.import_conv(...)`

## Batch 0: Preparation

### Goal

Create a clean `CA/improved/` boundary before functional changes.

### Tasks

1. Create `CA/improved/`.
2. Copy only the minimal Rasa project skeleton:
   - `actions.py`
   - `config.yml`
   - `credentials.yml`
   - `endpoints.yml`
   - `domain.yml`
   - `data/`
3. Do not copy:
   - `.venv`
   - `.rasa`
   - `models/`
   - caches
   - `Neo4jClient.py`
   - large generated artifacts
4. Create:
   - `CA/improved/local_runtime/`
   - `CA/improved/knowledge/`

### Checks

1. `CA/improved/` exists and is structurally independent.
2. No runtime import path points to `CA/original/`.
3. No generated caches or virtual environments exist under `CA/improved/`.

### Exit Criteria

- `CA/improved/` is a clean working area.

### Next Batch

Batch 1: static KG export.

## Batch 1: Static KG Export

### Goal

Move static exhibit and AOI knowledge out of Neo4j and into files.

### Tasks

1. Extract static exhibit and AOI data from `CA/original/CreatingThePaintingGraph.py`.
2. Create `CA/improved/knowledge/museum_knowledge_graph.json`.
3. Create `CA/improved/knowledge/object_aoi_mapping.json`.
4. Keep the first version simple and complete rather than elegant.

### Required Fields

`museum_knowledge_graph.json` should include at least:

- exhibit key
- `object_name`
- `painting_name`
- `description`
- `more_info`
- `artist`
- `year`
- `location`
- `style`
- `img`
- `aois`

`object_aoi_mapping.json` should include at least:

- `object_name_to_exhibit`
- `exhibit_to_object_name`
- `aoi_aliases`

### Checks

1. All five paintings are present.
2. AOIs exist with descriptions.
3. No obvious field loss in `description`, `more_info`, `img`, `artist`.
4. Any AOI alias mismatches are explicitly listed.

### Exit Criteria

- Static knowledge is fully available without Neo4j.
- `CA/improved/knowledge/museum_knowledge_graph.json` exists.
- `CA/improved/knowledge/object_aoi_mapping.json` exists.

### Next Batch

Batch 2: implement `KnowledgeBase`.

## Batch 2: Implement KnowledgeBase

### Goal

Provide a code interface for static knowledge lookup.

### Tasks

Create `CA/improved/local_runtime/knowledge_base.py` with a standalone class.

Implement at least:

- `load()`
- `normalize_object_name(object_name)`
- `normalize_aoi_name(aoi_name)`
- `get_object_by_name(object_name)`
- `get_aoi_by_name(aoi_name)`
- `get_object_image(object_name)`
- `get_graph_data()`
- `get_object_context(object_name)`
- `get_aoi_context(aoi_name)`

Then update `actions.py` only for static knowledge reads:

- exhibit data
- image lookup
- static object and AOI context

Do not change session or history logic yet.

### Checks

1. `KnowledgeBase` loads both JSON files correctly.
2. Object names like `C6`, `B1` resolve correctly.
3. AOI names resolve correctly, including aliases if needed.
4. Static prompt fields no longer require Neo4j.

### Exit Criteria

- Static KG reads are file-backed.

### Next Batch

Batch 3: implement `SessionStore`.

## Batch 3: Implement SessionStore

### Goal

Replace Neo4j runtime state with in-memory session state.

### Tasks

Create `CA/improved/local_runtime/models.py` for internal runtime models.

Define a session structure containing at least:

- `session_id`
- `participant_id`
- `started_at`
- `current_object_name`
- `current_aoi_name`
- `dialogue_history`
- `last_agent_reply`
- `last_interaction_at`
- `turn_count`

Create `CA/improved/local_runtime/session_store.py`.

Implement at least:

- `start_session(participant_id)`
- `get_session(session_id)`
- `set_current_object(session_id, object_name)`
- `get_current_object(session_id)`
- `set_current_aoi(session_id, aoi_name)`
- `get_current_aoi(session_id)`
- `append_history(session_id, speaker, text, timestamp)`
- `get_history(session_id)`
- `set_last_agent_reply(session_id, text)`
- `get_last_agent_reply(session_id)`
- `set_last_interaction_at(session_id, timestamp)`
- `get_last_interaction_at(session_id)`

Define the runtime rule:

1. Prefer the current turn input.
2. If missing, use the last valid session value.
3. If no valid value exists, fall back.

### Checks

1. New sessions can be created.
2. Multiple turns append correctly.
3. Current object and AOI update correctly.
4. Last agent reply and last interaction time can be stored and retrieved.

### Exit Criteria

- Runtime state is available independently of Neo4j.

### Next Batch

Batch 4: migrate `action_get_actor_id`.

## Batch 4: Migrate `action_get_actor_id`

### Goal

Make session creation start from `SessionStore`, not Neo4j.

### Tasks

Update `action_get_actor_id` in `CA/improved/actions.py`.

Old behavior:

- read actor id
- create agent in Neo4j
- return `actorID` and `agentID`

New behavior:

- treat input as `participant_id`
- call `SessionStore.start_session(participant_id)`
- return `session_id`

Short-term compatibility is allowed, but `session_id` should become the primary key.

### Checks

1. A new user creates a new session.
2. Session id is available to subsequent actions.
3. Neo4j is no longer required for session start.

### Exit Criteria

- Conversation start no longer depends on Neo4j.

### Next Batch

Batch 5: migrate `action_providing_response` reads.

## Batch 5: Migrate `action_providing_response` Read Path

### Goal

Move all read-side runtime context in the main response action to `SessionStore` and `KnowledgeBase`.

### Tasks

Within `action_providing_response`, replace:

1. Current object reads
2. Current AOI reads
3. Conversation history reads
4. Last agent reply reads
5. Static object and AOI prompt context

The new read order should be:

1. current turn input
2. session cache
3. fallback

### Checks

1. Normal response flow uses current object correctly.
2. AOI falls back to last valid value if not provided on the current turn.
3. History is available from the session store.
4. Prompt assembly does not require Neo4j.

### Exit Criteria

- Main action reads no longer require Neo4j.

### Next Batch

Batch 6: implement and connect `ConversationLogger`.

## Batch 6: Implement ConversationLogger

### Goal

Replace graph-based conversation writes with local JSONL logging.

### Tasks

Create `CA/improved/local_runtime/conversation_logger.py`.

Implement at least:

- `log_session_start(...)`
- `log_turn(...)`
- `log_session_end(...)`

Then replace:

- `GRAPH.import_conv(...)`

Integrate write flow so that:

1. session state is updated
2. local turn log is written

### Checks

1. Every turn produces a local log entry.
2. Log entries include session id, object, AOI, and text.
3. Logging still works when Neo4j is unavailable.
4. Session history and local logs stay consistent.

### Exit Criteria

- Conversation writes no longer require Neo4j.

### Next Batch

Batch 7: migrate `interactive_guide_interaction`.

## Batch 7: Migrate `interactive_guide_interaction`

### Goal

Move proactive guide behavior to local session state and static knowledge.

### Tasks

Replace Neo4j-backed reads in proactive guide logic:

- current object
- current AOI
- last interaction time
- history
- static exhibit context

Replace proactive write flow with:

- `SessionStore`
- `ConversationLogger`

Keep the old trigger behavior as stable as possible.

### Checks

1. Proactive guide can read current context.
2. Last interaction timing logic still works.
3. Session continuity is preserved.
4. Neo4j is not required for proactive behavior.

### Exit Criteria

- All three core actions work without Neo4j.

### Next Batch

Batch 8: remove residual Neo4j dependency.

## Batch 8: Remove Residual Neo4j Dependency

### Goal

Clean out all remaining Neo4j wiring from `CA/improved/`.

### Tasks

1. Remove or disable `Neo4jClient` initialization.
2. Remove Neo4j imports.
3. Remove hard-coded Bolt URI, Neo4j credentials, and similar config.
4. Clean misleading log messages mentioning live Neo4j state.
5. Verify no `GRAPH.*` calls remain.

### Checks

1. Search for `GRAPH.` returns zero relevant hits in `CA/improved/`.
2. Search for `Neo4jClient` returns zero relevant runtime usage.
3. Core flow works with Neo4j turned off.

### Exit Criteria

- `CA/improved/` is fully decoupled from online Neo4j.

### Next Batch

Batch 9: regression and stability validation.

## Batch 9: Regression and Stability Validation

### Goal

Confirm that the improved line is usable as the new active branch for CA work.

### Tasks

Test at least:

1. new user start
2. normal question answering
3. painting-aware question answering
4. no-painting fallback
5. `"Repeat Question"` branch
6. proactive guide branch
7. multi-turn conversation continuity
8. AOI fallback behavior
9. multiple sessions without cross-session leakage

### Checks

1. End-to-end flow works with Neo4j off.
2. Behavior remains close enough to the old CA experience.
3. State is not leaking across sessions.
4. Logging and history remain coherent.
5. Carding or latency improves meaningfully.

### Exit Criteria

- `CA/improved/` is stable enough to continue feature work there.

## Risks

### Risk 1: Dual source of truth

If Rasa slots and `SessionStore` both act as state owners, behavior will drift.

Mitigation:

- converge toward `session_id` as the main runtime key
- keep slots minimal

### Risk 2: Incomplete KG migration

If static fields are lost, prompt quality drops.

Mitigation:

- prioritize completeness over elegance in Batch 1
- verify key fields explicitly

### Risk 3: Mixed intermediate state

If one action is half Neo4j-backed and half local-backed, debugging becomes difficult.

Mitigation:

- complete one responsibility per batch
- do not start the next batch before checks pass

### Risk 4: Prompt behavior drift

Even with the same model, behavior can change if context formatting changes.

Mitigation:

- keep prompt structure stable during migration
- change data source first, prompt wording later

### Risk 5: Residual hidden dependency

Hard-coded paths, environment assumptions, or old logging can keep `improved` indirectly tied to `original`.

Mitigation:

- inspect imports, paths, logs, and config during Batch 8

## Working Rule

We will modify the system batch by batch.

For each batch:

1. implement only that batch's scope
2. run that batch's checks
3. confirm exit criteria
4. only then move to the next batch

## Current Status

- Batch 0 skeleton created under `CA/improved/`
- Minimal Rasa files copied without `.venv`, `.rasa`, `models`, or Neo4j helper files
- `local_runtime/` and `knowledge/` directories created
- Batch 1 initial KG files created under `CA/improved/knowledge/`
- Batch 2 `KnowledgeBase` created under `CA/improved/local_runtime/knowledge_base.py`
- Static `Exhibit Data` references in `actions.py` now read from local KG
- Batch 3 session models created under `CA/improved/local_runtime/models.py`
- Batch 3 in-memory `SessionStore` created under `CA/improved/local_runtime/session_store.py`
- Batch 4 `action_get_actor_id` now creates local sessions through `SessionStore`
- Batch 4 temporarily stores `participant_id` in slot `actorID` and `session_id` in slot `agentID`
- Batch 5 `action_providing_response` now reads current object, AOI, history, and last reply from `SessionStore`
- Batch 5 `action_providing_response` now uses `KnowledgeBase` for static prompt context
- Batch 6 `ConversationLogger` created under `CA/improved/local_runtime/conversation_logger.py`
- Batch 6 `_log_conversation()` methods now write local JSONL instead of using `GRAPH.import_conv(...)`
- `actions.py` still contains old Neo4j references and is not yet migrated
- Next active step: Batch 7 migrate `interactive_guide_interaction`
