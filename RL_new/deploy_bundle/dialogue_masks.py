"""Action masks for deployment — a dependency-free mirror of `env._get_available_options()`
and `env._get_available_subactions()`.

WHY THIS FILE EXISTS. The trained network contains none of the behaviour the evaluation
measured. Masking lives entirely in the environment: the policy emits logits over all options
and the env deletes the inadmissible ones. Measured on the flagship's 36,153 training turns,
the policy ALONE proposes Explain 91.42% of the time; after masking, executed Explain is
68.04%, with OfferTransition +11.11 pp and Engage +10.84 pp supplied entirely by the stall
mask and forced recovery. The VR study shipped the checkpoint without the masks and reproduced
100% ExplainNewFact — not a deployment bug, but half a system.

So the deployed agent is `policy + masks`, and both halves must ship. This module is the
second half, with no torch, no gym and no simulator import, so it can run in the VR pipeline.

FIDELITY IS TESTED, NOT ASSUMED. `tests/test_inference_mask_parity.py` replays real logged
states through both this module and the live `MuseumEnvironment` and asserts identical output.
That test is what would have caught the VR collapse.

Everything is a pure function of an explicit `WorldState`, so the caller must supply what the
env tracks internally. The seven rules, in the order env.py applies them:

  1. Conclude masked until `min_facts_before_conclude` facts have been shared
  2. Conclude masked until `min_exhibits_before_conclude` exhibits have been touched
  3. Explain masked when the exhibit is exhausted AND Explain has only ExplainNewFact
  4. Explain masked when it has no available subactions at all
  5. stall mask      (mask_stall_on_exhausted): exhausted + engaged + fresh exhibits remain
                     -> remove AskQuestion and Engage
  6. rescue-only     (engage_rescue_only): Engage masked while the visitor is engaged
  7. forced recovery (force_recover_on_disengage): disengaged -> ["Engage"], overrides all
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# The observation's response-type one-hot, in index order. Positional: the VR classifier must
# emit exactly these strings. env.py silently maps anything unknown to "statement" -- that
# fallback is why a -0.3 `repeat_request` penalty once reached the agent on turns its own
# observation called "statement". Deployment fails loudly instead; see validate_response_type.
RESPONSE_TYPE_LABELS: List[str] = [
    "acknowledgment", "follow_up_question", "question", "statement",
    "confusion", "silence", "clarification_request", "disengaged",
]

DEFAULT_OPTIONS: List[str] = ["Explain", "AskQuestion", "OfferTransition", "Conclude", "Engage"]
DEFAULT_SUBACTIONS: Dict[str, List[str]] = {
    "Explain": ["ExplainNewFact", "ClarifyFact"],
    "AskQuestion": ["AskOpinion"],
    "OfferTransition": ["SummarizeAndSuggest"],
    "Conclude": ["WrapUp"],
    "Engage": ["RecoverEngagement"],
}
# Subactions that DO satisfy a clarification request, per env.py's mask_clarify_misfire rule.
CLARIFY_CUES = ("confusion", "clarification_request", "repeat_request")


class UnknownResponseType(ValueError):
    """Raised when the classifier emits a label the observation cannot encode."""


def validate_response_type(rtype: str) -> str:
    """Fail loudly on an unknown label rather than silently defaulting to 'statement'.

    env.py's fallback is fine for training (the simulator's vocabulary is fixed and known) but
    dangerous in deployment: a classifier that emits 'follow-up' or 'repeat_request' would be
    read as 'statement', and the agent would perceive an engaged visitor as neutral with no
    error anywhere. `disengaged` in particular is the single dimension the whole recovery
    behaviour keys on.
    """
    if rtype not in RESPONSE_TYPE_LABELS:
        raise UnknownResponseType(
            f"response type {rtype!r} is not one of {RESPONSE_TYPE_LABELS}. "
            f"Map it explicitly at the classifier boundary; do not let it fall through."
        )
    return rtype


@dataclass
class WorldState:
    """Everything the mask rules read. The caller owns this; nothing is inferred."""
    focus: int                                   # 1-based index into exhibit_keys; 0 = no focus
    exhibit_keys: List[str]
    facts_mentioned: Dict[str, Set[str]]         # exhibit -> set of fact ids already delivered
    exhibit_fact_ids: Dict[str, Set[str]]        # exhibit -> set of ALL fact ids
    last_response_type: str = "statement"
    visitor_disengaged: bool = False

    options: List[str] = field(default_factory=lambda: list(DEFAULT_OPTIONS))
    subactions: Dict[str, List[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_SUBACTIONS.items()})

    # thresholds (env.py defaults)
    min_facts_before_conclude: int = 3
    min_exhibits_before_conclude: int = 2
    # intervention flags -- must match the flags the chosen checkpoint was TRAINED with,
    # which are recorded in that run's summary.json under "interventions"
    mask_stall_on_exhausted: bool = False
    engage_rescue_only: bool = False
    force_recover_on_disengage: bool = False
    mask_clarify_misfire: bool = False

    def current_exhibit(self) -> Optional[str]:
        return self.exhibit_keys[self.focus - 1] if 0 < self.focus <= len(self.exhibit_keys) else None

    def is_exhausted(self, exhibit: Optional[str]) -> bool:
        if exhibit is None or exhibit not in self.facts_mentioned:
            return False
        return not (self.exhibit_fact_ids.get(exhibit, set()) - self.facts_mentioned[exhibit])


def available_subactions(ws: WorldState, option: str) -> List[str]:
    """Mirror of env._get_available_subactions."""
    if option not in ws.subactions:
        return []
    subs = list(ws.subactions[option])
    if option == "Explain":
        current = ws.current_exhibit()
        if current:
            remaining = ws.exhibit_fact_ids.get(current, set()) - ws.facts_mentioned.get(current, set())
            if not remaining and "ExplainNewFact" in subs:
                subs.remove("ExplainNewFact")
        if (ws.mask_clarify_misfire
                and ws.last_response_type not in CLARIFY_CUES
                and "ClarifyFact" in subs):
            subs.remove("ClarifyFact")
    return subs


def available_options(ws: WorldState) -> List[str]:
    """Mirror of env._get_available_options. Rule order matters and matches env.py."""
    opts = list(ws.options)

    total_facts = sum(len(v) for v in ws.facts_mentioned.values())
    if total_facts < ws.min_facts_before_conclude and "Conclude" in opts:
        opts.remove("Conclude")

    covered = sum(1 for v in ws.facts_mentioned.values() if len(v) > 0)
    if covered < ws.min_exhibits_before_conclude and "Conclude" in opts:
        opts.remove("Conclude")

    if "Explain" in opts and ws.subactions.get("Explain", []) == ["ExplainNewFact"]:
        cur = ws.current_exhibit()
        if cur and ws.is_exhausted(cur):
            opts.remove("Explain")

    if "Explain" in opts and not available_subactions(ws, "Explain"):
        opts.remove("Explain")

    if ws.mask_stall_on_exhausted and not ws.visitor_disengaged:
        cur = ws.current_exhibit()
        if cur and ws.is_exhausted(cur):
            fresh = any(not ws.is_exhausted(e) for e in ws.exhibit_keys if e != cur)
            if fresh:
                for stall in ("AskQuestion", "Engage"):
                    if stall in opts:
                        opts.remove(stall)

    if ws.engage_rescue_only and not ws.visitor_disengaged and "Engage" in opts:
        opts.remove("Engage")

    if ws.force_recover_on_disengage and ws.visitor_disengaged and "Engage" in ws.options:
        return ["Engage"]

    return opts


def from_summary(summary: dict) -> dict:
    """Pull the intervention flags a checkpoint was trained with out of its summary.json.

    The deployed masks MUST match the training masks: a policy trained under forced recovery
    has never had to choose Engage for itself, so deploying it without that mask changes its
    behaviour entirely. Runs from git rev 90cfe2d onward record these under "interventions".
    """
    iv = summary.get("interventions") or {}
    missing = [k for k in ("mask_stall_on_exhausted", "engage_rescue_only",
                           "force_recover_on_disengage", "mask_clarify_misfire") if k not in iv]
    if missing:
        raise KeyError(
            f"summary.json has no intervention record for {missing}. Runs before rev 90cfe2d "
            f"did not record them; recover them from the launch script and pass explicitly.")
    return {
        "mask_stall_on_exhausted": bool(iv["mask_stall_on_exhausted"]),
        "engage_rescue_only": bool(iv["engage_rescue_only"]),
        "force_recover_on_disengage": bool(iv["force_recover_on_disengage"]),
        "mask_clarify_misfire": bool(iv["mask_clarify_misfire"]),
    }
