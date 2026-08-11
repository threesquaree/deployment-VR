"""Verification ladder step 3 (deploy_bundle/HANDOFF.md): free-run action mix.

Reference (frozen 50-episode evals of E_flat_S2): Explain/Recover/Transition =
67.7 / 20.0 / 12.2 %. The scripted visitor here is not sim8, so exact
reproduction is not expected -- but HANDOFF's stated tripwire is hard: if any
single action exceeds 85%, the integration is broken (the frozen-state /
missing-mask collapse reproduces 100% Explain).

Run from RL_new:  ..\\RL\\.venv\\Scripts\\python.exe tests\\test_action_mix.py
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference.rl_runtime import RLMuseumRuntime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

EPISODES = 5
MAX_TURNS = 40

# Roughly sim8-shaped label pool: engaged labels dominate, ~15% disengaged.
LABEL_POOL = (
    ["follow_up_question"] * 22
    + ["acknowledgment"] * 21
    + ["question"] * 15
    + ["statement"] * 13
    + ["confusion"] * 6
    + ["disengaged"] * 15
    + ["silence"] * 4
    + ["clarification_request"] * 4
)


def build_runtime():
    return RLMuseumRuntime(
        checkpoint_path=str(ROOT / "deploy_bundle" / "checkpoint_ep1000_model.pt"),
        knowledge_graph_path=str(ROOT / "KG" / "museum_knowledge_graph.json"),
        summary_path=str(ROOT / "deploy_bundle" / "summary.json"),
        mapping_path=str(ROOT / "KG" / "neo4j_to_rl_mapping.json"),
    )


def least_covered_other(rt, current):
    others = [ex for ex in rt.exhibit_keys if ex != current]
    return min(others, key=lambda ex: len(rt.facts_mentioned[ex]))


def main():
    rng = random.Random(31)
    executed = Counter()
    total_turns = 0

    for episode in range(EPISODES):
        rt = build_runtime()  # fresh session: clean LSTM, clean counters
        exhibit = rt.exhibit_keys[0]
        label = "statement"

        for _ in range(MAX_TURNS):
            disengaged = label == "disengaged"
            decision = rt.decide(exhibit, label, disengaged)
            sub = decision["subaction"]
            executed[sub] += 1
            total_turns += 1

            # World update (mirrors generate_turn's bookkeeping).
            rt.subaction_counts[sub] += 1
            rt.option_counts[decision["option"]] += 1
            rt.turn_number += 1
            if sub == "ExplainNewFact":
                remaining = sorted(rt.exhibit_fact_ids[exhibit] - rt.facts_mentioned[exhibit])
                if remaining:
                    rt.facts_mentioned[exhibit].add(remaining[0])

            if sub == "WrapUp":
                break  # learned termination ends the episode

            # Visitor reaction.
            if sub == "SummarizeAndSuggest":
                # The visitor accepts the suggested transition.
                exhibit = least_covered_other(rt, exhibit)
                label = "acknowledgment"
            elif sub == "RecoverEngagement":
                # Recovery works: the visitor re-engages (training's simulator
                # re-engaged quickly; without this the mask loops on Engage).
                label = rng.choice(["acknowledgment", "follow_up_question"])
            else:
                label = rng.choice(LABEL_POOL)

    explain = executed["ExplainNewFact"] + executed["ClarifyFact"]
    recover = executed["RecoverEngagement"]
    transition = executed["SummarizeAndSuggest"]

    print("executed actions over {0} turns / {1} episodes:".format(total_turns, EPISODES))
    for name, count in executed.most_common():
        print("  {0:<22} {1:>4}  ({2:5.1f}%)".format(name, count, 100.0 * count / total_turns))
    print(
        "Explain/Recover/Transition = {0:.1f} / {1:.1f} / {2:.1f} %   "
        "(reference: 67.7 / 20.0 / 12.2)".format(
            100.0 * explain / total_turns,
            100.0 * recover / total_turns,
            100.0 * transition / total_turns,
        )
    )

    # HANDOFF tripwire: >85% of any single action means the integration is broken.
    for name, count in executed.items():
        share = count / total_turns
        assert share <= 0.85, "{0} at {1:.1f}% (>85%): integration broken".format(name, 100 * share)
    assert 0.50 <= explain / total_turns <= 0.85, "Explain share {0:.1f}% outside [50, 85]".format(
        100.0 * explain / total_turns
    )
    assert recover > 0, "Engage/RecoverEngagement never executed"
    assert transition > 0, "OfferTransition/SummarizeAndSuggest never executed"

    print("test_action_mix: OK")


if __name__ == "__main__":
    main()
