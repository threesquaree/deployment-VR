"""Verification ladder step 2 (deploy_bundle/HANDOFF.md): the anti-collapse test.

"Acting is only half a turn": if the observation is not rebuilt from the updated
world state before every decision, the policy stares at a frozen vector and
collapses to its modal action -- the exact failure that broke the first VR
deployment. This scripted episode drives the real checkpoint through
RLMuseumRuntime.decide() (no LLM calls) with simulated visitor reactions and
asserts the observation changes every turn and encodes exactly what was injected.

Run from RL_new:  ..\\RL\\.venv\\Scripts\\python.exe tests\\test_frozen_state.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from inference.bundle_loader import RESPONSE_TYPE_LABELS  # noqa: E402
from inference.rl_runtime import RLMuseumRuntime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build_runtime():
    return RLMuseumRuntime(
        checkpoint_path=str(ROOT / "deploy_bundle" / "checkpoint_ep1000_model.pt"),
        knowledge_graph_path=str(ROOT / "KG" / "museum_knowledge_graph.json"),
        summary_path=str(ROOT / "deploy_bundle" / "summary.json"),
        mapping_path=str(ROOT / "KG" / "neo4j_to_rl_mapping.json"),
    )


def main():
    rt = build_runtime()
    exhibit = rt.exhibit_keys[0]

    # Fixed script: (label, disengaged) per HANDOFF step 7, covering 6 of the 8
    # labels including one disengaged turn (index 5).
    script = [
        ("statement", False),
        ("follow_up_question", False),
        ("acknowledgment", False),
        ("question", False),
        ("confusion", False),
        ("disengaged", True),
        ("acknowledgment", False),
        ("silence", False),
        ("clarification_request", False),
        ("statement", False),
    ]

    prev_obs = None
    prev_coverage = np.zeros(5, dtype=np.float32)
    for turn, (label, disengaged) in enumerate(script):
        decision = rt.decide(exhibit, label, disengaged)
        obs = np.asarray(decision["obs"], dtype=np.float32)
        assert obs.shape == (31,), obs.shape

        # The response-type one-hot must encode exactly the injected label.
        onehot = obs[21:29]
        expected_idx = RESPONSE_TYPE_LABELS.index(label)
        assert onehot[expected_idx] == 1.0 and onehot.sum() == 1.0, (
            "turn {0}: obs[21:29]={1} does not encode {2!r}".format(turn, onehot.tolist(), label)
        )

        # Coverage ratios never decrease.
        coverage = obs[6:11]
        assert np.all(coverage >= prev_coverage - 1e-6), (
            "turn {0}: coverage regressed {1} -> {2}".format(turn, prev_coverage, coverage)
        )
        prev_coverage = coverage

        # Mask rule 7: a disengaged visitor collapses the legal set to ["Engage"]
        # and the policy's argmax must recover.
        if disengaged:
            assert decision["available_options"] == ["Engage"], decision["available_options"]
            assert decision["option"] == "Engage" and decision["subaction"] == "RecoverEngagement"

        # THE test: the observation must differ from the previous turn's.
        if prev_obs is not None:
            assert not np.array_equal(obs, prev_obs), (
                "turn {0}: observation FROZEN (identical to turn {1}) -- the state "
                "update between decisions is missing".format(turn, turn - 1)
            )
        prev_obs = obs

        # Simulate the world update generate_turn performs after acting: the
        # executed action enters the counters, ExplainNewFact delivers one fact.
        executed = decision["subaction"]
        rt.subaction_counts[executed] += 1
        rt.option_counts[decision["option"]] += 1
        if executed == "ExplainNewFact":
            remaining = sorted(rt.exhibit_fact_ids[exhibit] - rt.facts_mentioned[exhibit])
            if remaining:
                rt.facts_mentioned[exhibit].add(remaining[0])
        rt.turn_number += 1

    print("test_frozen_state: OK ({0} turns, obs changed every turn)".format(len(script)))


if __name__ == "__main__":
    main()
