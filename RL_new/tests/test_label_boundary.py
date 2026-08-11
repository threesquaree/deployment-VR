"""Verification ladder step 1 (deploy_bundle/HANDOFF.md): the classifier boundary.

Feeds every label the response-type classifier can emit -- plus the event-only
labels and edge garbage -- through the contract boundary and asserts the mapping
is exactly what the study expects. This test is where the fail-LOUD guarantee
lives: at runtime, an unknown label degrades softly to "statement" (a /turn must
never 500 mid-study), so this test must prove no known classifier output ever
takes that path.

Run from RL_new:  ..\\RL\\.venv\\Scripts\\python.exe tests\\test_label_boundary.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference.bundle_loader import (  # noqa: E402
    BOUNDARY_REMAP,
    RESPONSE_TYPE_LABELS,
    to_contract_label,
)  # BOUNDARY_REMAP is asserted against, not assumed: see main()
from inference.response_type_classifier import SPEECH_LABELS, STATE_LABELS  # noqa: E402


def main():
    # The two label contracts (bundle vs classifier module) must be one and the
    # same list, in the same order -- obs[21:29] is positional.
    assert list(STATE_LABELS) == list(RESPONSE_TYPE_LABELS), (
        "label contract mismatch: classifier STATE_LABELS != bundle "
        "RESPONSE_TYPE_LABELS\n  classifier: {0}\n  bundle:     {1}".format(
            STATE_LABELS, RESPONSE_TYPE_LABELS
        )
    )
    assert RESPONSE_TYPE_LABELS.index("disengaged") == 7, "disengaged must be the last label (obs index 28)"

    # Every contract label validates; those without an explicit remap pass
    # through unchanged, and every remap target is itself a contract label.
    for label in RESPONSE_TYPE_LABELS:
        mapped, ok, err = to_contract_label(label)
        expected = BOUNDARY_REMAP.get(label, label)
        assert ok and mapped == expected and err == "", (label, mapped, expected, ok, err)
    for source, target in BOUNDARY_REMAP.items():
        assert target in RESPONSE_TYPE_LABELS, (source, target)

    # Every label the LLM classifier can emit must validate (possibly via the
    # explicit boundary remap) -- none may fall through to the statement fallback.
    for label in SPEECH_LABELS:
        mapped, ok, err = to_contract_label(label)
        assert ok, "classifier label {0!r} fails the boundary: {1}".format(label, err)
        expected = BOUNDARY_REMAP.get(label, label)
        assert mapped == expected, (label, mapped, expected)

    # The event-only labels (never produced by the LLM) also validate.
    for label in ("silence", "disengaged"):
        mapped, ok, _ = to_contract_label(label)
        assert ok and mapped == label

    # HANDOFF's open decision, as resolved: repeat_request -> confusion.
    assert to_contract_label("repeat_request") == ("confusion", True, "")
    # Never active in training (p_clar: 0.0 in every summary.json), so it must
    # not reach obs[27] live -- see BOUNDARY_REMAP's rationale.
    assert to_contract_label("clarification_request") == ("confusion", True, "")
    # ...but `confusion` itself, and the labels training DID exercise, are untouched.
    for label in ("confusion", "acknowledgment", "follow_up_question", "question",
                  "statement", "silence", "disengaged"):
        assert to_contract_label(label) == (label, True, "")

    # Garbage degrades to statement, flagged not-ok, with a real error message.
    for garbage in ("follow-up", "", None, "Statement ", "REPEAT_REQUEST!", "unknown"):
        mapped, ok, err = to_contract_label(garbage)
        assert mapped == "statement" and not ok and err, (garbage, mapped, ok, err)

    # Leading/trailing whitespace on a valid label is tolerated.
    assert to_contract_label(" confusion ") == ("confusion", True, "")

    print("test_label_boundary: OK")


if __name__ == "__main__":
    main()
