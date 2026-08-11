"""Transition targets must follow the physical gallery (B1->B2->B3->C5->C6),
not knowledge-graph insertion order.

Regression for the 2026-08-03 pilot session, where the suggested route was
Diego_Bemba -> King_Caspar -> Turban -> Dom_Miguel (criss-crossing the room).

Run from RL_new:  ..\\RL\\.venv\\Scripts\\python.exe tests\\test_transition_target.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference.rl_runtime import RLMuseumRuntime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WALK_ORDER = ["Diego_Bemba", "Dom_Miguel", "Pedro_Sunda", "Turban", "King_Caspar"]


def build_runtime(walk_order=WALK_ORDER):
    return RLMuseumRuntime(
        checkpoint_path=str(ROOT / "deploy_bundle" / "checkpoint_ep1000_model.pt"),
        knowledge_graph_path=str(ROOT / "KG" / "museum_knowledge_graph.json"),
        summary_path=str(ROOT / "deploy_bundle" / "summary.json"),
        mapping_path=str(ROOT / "KG" / "neo4j_to_rl_mapping.json"),
        exhibit_walk_order=walk_order,
    )


def exhaust(rt, exhibit):
    rt.facts_mentioned[exhibit] |= rt.exhibit_fact_ids[exhibit]


def main():
    # Pilot-session replay: standing at an exhausted Diego_Bemba, everything
    # else fresh -> the neighbour Dom_Miguel, NOT King_Caspar (old KG-order pick).
    rt = build_runtime()
    exhaust(rt, "Diego_Bemba")
    assert rt._pick_transition_target("Diego_Bemba") == "Dom_Miguel", (
        rt._pick_transition_target("Diego_Bemba")
    )

    # Walk continues along the wall as exhibits exhaust.
    exhaust(rt, "Dom_Miguel")
    assert rt._pick_transition_target("Dom_Miguel") == "Pedro_Sunda"
    exhaust(rt, "Pedro_Sunda")
    assert rt._pick_transition_target("Pedro_Sunda") == "Turban"
    exhaust(rt, "Turban")
    assert rt._pick_transition_target("Turban") == "King_Caspar"

    # Equidistant neighbours: from Pedro_Sunda (middle), Dom_Miguel and Turban
    # are both 1 step away; the one with more unseen facts wins (Turban has 6,
    # Dom_Miguel exhausted here -> filtered out entirely).
    rt2 = build_runtime()
    exhaust(rt2, "Pedro_Sunda")
    exhaust(rt2, "Dom_Miguel")
    assert rt2._pick_transition_target("Pedro_Sunda") == "Turban"

    # Fresh session at Pedro_Sunda: both neighbours fresh (6 facts each) ->
    # deterministic tie-break on walk-order position -> Dom_Miguel.
    rt3 = build_runtime()
    exhaust(rt3, "Pedro_Sunda")
    others = rt3._pick_transition_target("Pedro_Sunda")
    assert others == "Dom_Miguel", others

    # Everything exhausted -> falls back to least-mentioned (never None/crash).
    rt4 = build_runtime()
    for ex in rt4.exhibit_keys:
        exhaust(rt4, ex)
    assert rt4._pick_transition_target("Diego_Bemba") in rt4.exhibit_keys

    # No walk order configured -> legacy least-covered behaviour still works.
    rt5 = build_runtime(walk_order=None)
    exhaust(rt5, "Diego_Bemba")
    assert rt5._pick_transition_target("Diego_Bemba") == "King_Caspar"  # KG order

    # Bad config is rejected at startup.
    try:
        build_runtime(walk_order=["Diego_Bemba", "Dom_Miguel"])
    except ValueError:
        pass
    else:
        raise AssertionError("partial exhibit_walk_order must raise")

    print("test_transition_target: OK")


if __name__ == "__main__":
    main()
