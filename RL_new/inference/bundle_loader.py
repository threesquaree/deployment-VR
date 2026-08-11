"""Single import point for the parity-tested deploy_bundle study-agent modules.

The active agent is whatever checkpoint + summary.json ship in deploy_bundle/
(currently F2_flat_learn_both, previously E_flat_S2 in deploy_bundle_old/).

The files in deploy_bundle/ (dialogue_masks.py, state_builder_31d.py, agent.py,
networks.py) are the training side's contract and are parity-tested against the
live environment (see deploy_bundle/HANDOFF.md). They must stay byte-identical,
so instead of copying them into inference/ (the drift that produced the stale
158-d state_builder.py and the first VR collapse), this shim puts deploy_bundle/
on sys.path and re-exports the symbols the runtime needs.

Also hosts the classifier-boundary label mapping (`to_contract_label`): the one
place where labels outside the 8-label contract are explicitly mapped before
validation, per HANDOFF's "Label contract" section.
"""
import sys
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "deploy_bundle"
if not BUNDLE_DIR.is_dir():
    raise FileNotFoundError(
        f"deploy_bundle not found at {BUNDLE_DIR}; the E_flat_S2 runtime cannot start without it."
    )
if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

from dialogue_masks import (  # noqa: E402
    DEFAULT_OPTIONS,
    DEFAULT_SUBACTIONS,
    RESPONSE_TYPE_LABELS,
    UnknownResponseType,
    WorldState,
    available_options,
    available_subactions,
    from_summary,
    validate_response_type,
)
from state_builder_31d import STATE_DIM, SUBACTION_ORDER, build_observation  # noqa: E402
from agent import FlatActorCriticAgent  # noqa: E402

# Labels the policy cannot usefully perceive, mapped to the nearest one it can.
# Both entries collapse a fine-grained "I didn't get that" state onto `confusion`,
# which was active in ~6.7% of training turns. The raw label is still what gets
# LOGGED (InteractionRecord.response_type); only the state one-hot is collapsed.
#
#   repeat_request        HANDOFF's open decision, resolved 2026-08-02 (owner:
#                         Nayan). Not in the 8-label contract at all, so it would
#                         raise in the validator; `confusion` is the same "please
#                         go over that again" state.
#   clarification_request IS in the contract, but the simulator never produced it
#                         -- every run's summary.json has p_clar: 0.0, F2 included
#                         -- so obs[27] was zero for ALL of training. Setting it
#                         live puts the observation off-distribution in a dimension
#                         the policy has no experience of. (Restored 2026-08-05
#                         after pilot review; the E_flat migration had dropped this
#                         remap on the grounds that the contract lists the label,
#                         which missed that the label was never exercised.)
BOUNDARY_REMAP = {
    "repeat_request": "confusion",
    "clarification_request": "confusion",
}


def to_contract_label(raw_label):
    """Map a classifier label onto the 8-label contract, failing soft but loud.

    Returns (contract_label, ok, error). On an unknown label the turn must not
    500 (a participant would be left standing in VR with a mute guide), so fall
    back to "statement" -- training's own fallback semantics -- and surface the
    error for logging. The fail-LOUD guarantee lives in
    tests/test_label_boundary.py, which asserts every label the classifier can
    emit passes validation, so this fallback can only fire on hand-typed
    metadata overrides.
    """
    label = (raw_label or "").strip()
    label = BOUNDARY_REMAP.get(label, label)
    try:
        return validate_response_type(label), True, ""
    except UnknownResponseType as exc:
        return "statement", False, str(exc)


__all__ = [
    "BUNDLE_DIR",
    "BOUNDARY_REMAP",
    "DEFAULT_OPTIONS",
    "DEFAULT_SUBACTIONS",
    "RESPONSE_TYPE_LABELS",
    "STATE_DIM",
    "SUBACTION_ORDER",
    "UnknownResponseType",
    "WorldState",
    "FlatActorCriticAgent",
    "available_options",
    "available_subactions",
    "build_observation",
    "from_summary",
    "to_contract_label",
    "validate_response_type",
]
