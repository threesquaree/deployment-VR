# CA Improved

This directory is the new working area for the improved CA line.

Current intent:

- keep the Rasa project structure
- remove online Neo4j dependency in staged batches
- avoid importing runtime code from `CA/original/`
- avoid copying the full original project tree

Current state:

- Batch 0 through Batch 8 are complete
- minimal Rasa files were copied from `CA/original/`
- `local_runtime/` and `knowledge/` are in active use
- `actions.py` no longer depends on online Neo4j for runtime reads or writes

Do not add:

- `.venv`
- `.rasa`
- `models/`
- generated caches

Do not import runtime modules from `CA/original/`.
