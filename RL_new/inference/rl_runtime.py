import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

# Allow local package imports when used as a standalone folder.
runtime_dir = Path(__file__).parent
project_root = runtime_dir.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(runtime_dir))

from bundle_loader import (
    DEFAULT_OPTIONS,
    DEFAULT_SUBACTIONS,
    FlatActorCriticAgent,
    WorldState,
    available_options,
    available_subactions,
    build_observation,
    from_summary,
)
from exhibit_mapping import ExhibitMapping
from prompt.openai_generator import generate_judge_json, generate_revision_text, generate_with_openai
from prompt.action_descriptions import get_action_description
from prompt.judge import build_judge_prompt
from prompt.judge_schema import build_fallback_judge_result, parse_and_validate_judge_output
from prompt.revise import build_revise_prompt
from src.utils.dialogue_planner import build_prompt
from src.utils import dialogue_planner as dialogue_planner_module
from src.utils.knowledge_graph import SimpleKnowledgeGraph


class RLMuseumRuntime:
    """
    Minimal runtime for RL inference + prompt planning + OpenAI generation.
    Keeps only deployment-time pieces (no training loop).

    Serves the deploy_bundle study agent (deploy_bundle/HANDOFF.md; currently
    F2_flat_learn_both): flat 31-d observation, 6 actions, masks mirrored from
    the training env, mask flags read from the run's own summary.json,
    deterministic argmax.
    """

    def __init__(
        self,
        checkpoint_path: str,
        knowledge_graph_path: str,
        summary_path: str,
        mapping_path: Optional[str] = None,
        device: str = "cpu",
        model_name: str = "gpt-5.4",
        judge_enabled: bool = False,
        judge_fail_policy: str = "pass",
        exhibit_walk_order: Optional[List[str]] = None,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.knowledge_graph_path = Path(knowledge_graph_path)
        self.summary_path = Path(summary_path)
        self.device = device
        self.model_name = model_name
        self.judge_enabled = bool(judge_enabled)
        self.judge_fail_policy = str(judge_fail_policy or "pass").strip().lower()

        self.knowledge_graph = SimpleKnowledgeGraph(str(self.knowledge_graph_path))
        # Positional: obs[0:6] (focus one-hot) and obs[6:11] (coverage) index into
        # this list in JSON insertion order. Never sort it.
        self.exhibit_keys = self.knowledge_graph.get_exhibit_names()
        self.exhibit_fact_ids = {
            ex: {
                self.knowledge_graph.extract_fact_id(f)
                for f in self.knowledge_graph.get_exhibit_facts(ex)
            }
            for ex in self.exhibit_keys
        }
        # Mask flags come from the training run's own record, never hardcoded
        # (HANDOFF.md "Mask flags"). from_summary raises if provenance is missing,
        # which is the desired startup failure.
        with self.summary_path.open("r", encoding="utf-8-sig") as handle:
            self.mask_flags = from_summary(json.load(handle))

        self.options = list(DEFAULT_OPTIONS)
        self.subactions = {k: list(v) for k, v in DEFAULT_SUBACTIONS.items()}
        self.state_dim = 31
        self.agent = FlatActorCriticAgent(
            state_dim=self.state_dim,
            options=self.options,
            subactions=self.subactions,
            hidden_dim=256,
            lstm_hidden_dim=128,
            use_lstm=True,
            device=device,
        )
        checkpoint = torch.load(str(self.checkpoint_path), map_location=device, weights_only=False)
        # Hard-fails on a wrong checkpoint (missing key / shape mismatch) instead
        # of silently building a default agent.
        self.agent.network.load_state_dict(checkpoint["agent_state"])
        self.agent.network.eval()
        self.checkpoint_episode = checkpoint.get("episode")
        # One runtime == one session == one episode. Training resets the agent at
        # every episode start; the encoder is an LSTM whose hidden state must be
        # clean at session start and then persist across the session's turns.
        self.agent.reset()

        resolved_mapping_path = Path(mapping_path) if mapping_path else project_root / "KG" / "neo4j_to_rl_mapping.json"
        self.mapping = ExhibitMapping(str(resolved_mapping_path))

        # Physical gallery order (B1->B2->B3->C5->C6), used ONLY to pick the
        # TARGET of a transition the policy already chose -- the target never
        # enters the observation, so this is parity-free deployment logic.
        # Without it, suggestions follow KG insertion order and send the
        # visitor zig-zagging across the room.
        if exhibit_walk_order is not None:
            if sorted(exhibit_walk_order) != sorted(self.exhibit_keys):
                raise ValueError(
                    "exhibit_walk_order must be a permutation of the knowledge graph's "
                    f"exhibits {self.exhibit_keys}, got {exhibit_walk_order}"
                )
            self.exhibit_walk_order = list(exhibit_walk_order)
        else:
            self.exhibit_walk_order = None

        self.facts_mentioned = defaultdict(set)
        self.option_counts = defaultdict(int)
        # Per-SUBACTION usage feeds obs[11:17] (actions_used keyed by subaction,
        # normalized by total executed actions).
        self.subaction_counts = defaultdict(int)
        self.turn_number = 0

    def decide(
        self,
        exhibit_key: str,
        state_response_type: str,
        visitor_disengaged: bool,
    ) -> Dict[str, Any]:
        """The pure decision core: WorldState -> masks -> 31-d obs -> argmax.

        Mirrors deploy_bundle/run_agent_example.py exactly. Called on EVERY turn
        (including forced silence turns) so the LSTM hidden state advances one
        step per turn, as it did in training. The network input is the
        observation only, so a forced action overriding the returned choice does
        not corrupt the recurrent state.
        """
        focus = (
            self.exhibit_keys.index(exhibit_key) + 1
            if exhibit_key in self.exhibit_keys
            else 0
        )
        ws = WorldState(
            focus=focus,
            exhibit_keys=self.exhibit_keys,
            facts_mentioned=self.facts_mentioned,
            exhibit_fact_ids=self.exhibit_fact_ids,
            last_response_type=state_response_type,
            visitor_disengaged=bool(visitor_disengaged),
            **self.mask_flags,
        )
        legal_options = available_options(ws)
        legal_subactions = {opt: available_subactions(ws, opt) for opt in legal_options}
        # No gaze-dwell signal is wired from VR; HANDOFF sanctions fixed
        # dwell=0.5/delta=0 (dims 29-30 are reward-irrelevant under utterance_only).
        obs = build_observation(
            ws,
            actions_used=dict(self.subaction_counts),
            dwell=0.5,
            last_delta_dwell=0.0,
        )
        selection = self.agent.select_action(
            obs, legal_options, legal_subactions, deterministic=True
        )
        return {
            "option": selection["option_name"],
            "subaction": selection["subaction_name"],
            "available_options": legal_options,
            "available_subactions": legal_subactions,
            "obs": obs.tolist(),
        }

    def _pick_transition_target(self, current_exhibit: str) -> Optional[str]:
        exhibit_names = self.knowledge_graph.get_exhibit_names()
        if not exhibit_names:
            return None
        others = [x for x in exhibit_names if x != current_exhibit]
        if not others:
            return current_exhibit

        def remaining(ex: str) -> int:
            return len(self.exhibit_fact_ids.get(ex, set()) - self.facts_mentioned.get(ex, set()))

        # Prefer the physically CLOSEST exhibit that still has unseen facts, so
        # the suggested walk follows the gallery instead of criss-crossing it.
        if self.exhibit_walk_order and current_exhibit in self.exhibit_walk_order:
            fresh = [ex for ex in others if remaining(ex) > 0]
            if fresh:
                pos = self.exhibit_walk_order.index(current_exhibit)
                return min(
                    fresh,
                    key=lambda ex: (
                        abs(self.exhibit_walk_order.index(ex) - pos),  # walk distance
                        -remaining(ex),                                # then most left to say
                        self.exhibit_walk_order.index(ex),             # deterministic tie-break
                    ),
                )
        # Fallback (no walk order configured, or everything already exhausted):
        # lowest mentioned fact count, as before.
        return min(others, key=lambda ex: len(self.facts_mentioned.get(ex, set())))

    def _coverage_dict(self) -> Dict[str, Dict[str, float]]:
        out = {}
        for ex in self.knowledge_graph.get_exhibit_names():
            total = len(self.knowledge_graph.get_exhibit_facts(ex))
            mentioned = len(self.facts_mentioned.get(ex, set()))
            coverage = (mentioned / total) if total > 0 else 0.0
            out[ex] = {"mentioned": mentioned, "total": total, "coverage": coverage}
        return out

    def _update_facts_from_response(self, exhibit: str, response: str) -> None:
        fact_ids = re.findall(r"\[([A-Z]{2}_\d{3})\]", response or "")
        if fact_ids:
            self.facts_mentioned[exhibit].update(fact_ids)

    @staticmethod
    def _fact_bearing_selected_ids(
        option: str,
        subaction: str,
        explain_newfact_meta: Dict[str, Any],
        repeatfact_meta: Dict[str, Any],
    ) -> List[str]:
        if option == "Explain" and subaction == "ExplainNewFact":
            return list(explain_newfact_meta.get("selected_fact_ids") or [])
        if option == "Explain" and subaction == "RepeatFact":
            return list(repeatfact_meta.get("selected_fact_ids") or [])
        return []

    def _run_judge(
        self,
        *,
        option: str,
        subaction: str,
        action_description: str,
        exhibit_key: str,
        current_aoi: Optional[str],
        user_message: str,
        history_for_judge: object,
        candidate_response: str,
        selected_fact_ids: List[str],
    ) -> Tuple[Dict[str, Any], bool, str]:
        judge_prompt = build_judge_prompt(
            option=option,
            subaction=subaction,
            action_description=action_description,
            current_exhibit=exhibit_key,
            current_aoi=current_aoi,
            user_input=user_message,
            conversation_history=history_for_judge,
            candidate_response=candidate_response,
            selected_fact_ids=selected_fact_ids,
        )
        try:
            judge_raw = generate_judge_json(
                prompt=judge_prompt,
                model=self.model_name,
            )
            judge_result = parse_and_validate_judge_output(
                judge_raw,
                selected_fact_ids=selected_fact_ids,
            )
            judge_result["raw_text"] = judge_raw
            return judge_result, True, ""
        except Exception as exc:
            judge_error = str(exc)
            judge_result, judge_parse_ok = build_fallback_judge_result(
                self.judge_fail_policy, judge_error
            )
            judge_result["raw_text"] = ""
            return judge_result, judge_parse_ok, judge_error

    def generate_turn(
        self,
        user_message: str,
        exhibit: Optional[str],
        dialogue_history: List[Tuple[str, str, int]],
        current_aoi: Optional[str] = None,
        conversation_history_rows: Optional[List[Dict[str, Any]]] = None,
        response_type: Optional[str] = None,
        state_response_type: Optional[str] = None,
        forced_option: Optional[str] = None,
        forced_subaction: Optional[str] = None,
        visitor_disengaged: bool = False,
        is_silence: bool = False,
    ) -> Dict[str, Any]:
        exhibit_key = self.mapping.to_exhibit_key(exhibit) if exhibit else ""
        # The service validates/maps the raw label onto the 8-label contract
        # (bundle_loader.to_contract_label) before calling us; response_type stays
        # the raw label for logging.
        if state_response_type is None:
            state_response_type = response_type or "statement"

        # The policy runs on EVERY turn -- forced or not -- so the LSTM hidden
        # trajectory sees every step, exactly as in training (HANDOFF turn loop).
        decision = self.decide(exhibit_key, state_response_type, visitor_disengaged)

        if forced_option or forced_subaction:
            # Silence rule only: the executed action is forced, the policy's own
            # choice is kept as a logged counterfactual.
            if not forced_option or not forced_subaction:
                raise ValueError("forced_option and forced_subaction must be provided together.")
            legal_forced = self.subactions.get(forced_option, [])
            if forced_subaction not in legal_forced:
                raise ValueError(
                    f"Invalid forced action '{forced_option}/{forced_subaction}' for the active action space."
                )
            option = forced_option
            subaction = forced_subaction
            policy_action = f"{decision['option']}/{decision['subaction']}"
            resolved_from = "silence_rule_based"
        else:
            option = decision["option"]
            subaction = decision["subaction"]
            policy_action = None
            resolved_from = "rl_policy_argmax"

        result = {
            "action": f"{option}/{subaction}",
            "option": option,
            "subaction": subaction,
            "available_options": decision["available_options"],
            "available_subactions": decision["available_subactions"],
            "obs_31": decision["obs"],
            "policy_action": policy_action,
            "resolved_from": resolved_from,
        }
        self.option_counts[option] += 1
        # Mirror env.py step-time bookkeeping: the EXECUTED action (forced ones
        # included) updates the counters the NEXT turn's observation will see.
        self.subaction_counts[subaction] += 1

        all_facts = self.knowledge_graph.get_exhibit_facts(exhibit_key) if exhibit_key else []
        mentioned_ids = self.facts_mentioned.get(exhibit_key, set()) if exhibit_key else set()
        mentioned_facts = [
            f for f in all_facts if self.knowledge_graph.extract_fact_id(f) in mentioned_ids
        ]
        unmentioned_facts = [
            f for f in all_facts if self.knowledge_graph.extract_fact_id(f) not in mentioned_ids
        ]

        facts_for_prompt = unmentioned_facts if option == "Explain" else all_facts
        auxiliary_context = (
            self.knowledge_graph.get_auxiliary_context(exhibit_key) if exhibit_key else {}
        )
        target_exhibit = None
        if exhibit_key and (option == "OfferTransition" or subaction == "SummarizeAndSuggest"):
            target_exhibit = self._pick_transition_target(exhibit_key)

        prompt = build_prompt(
            option=option,
            subaction=subaction,
            ex_id=exhibit_key,
            last_utt=user_message,
            facts_all=facts_for_prompt,
            facts_used=mentioned_facts,
            selected_fact=None,
            dialogue_history=dialogue_history,
            exhibit_names=self.knowledge_graph.get_exhibit_names(),
            knowledge_graph=self.knowledge_graph,
            auxiliary_context=auxiliary_context,
            target_exhibit=target_exhibit,
            coverage_dict=self._coverage_dict(),
            current_aoi=current_aoi,
            conversation_history_rows=conversation_history_rows,
            is_silence=is_silence,
        )
        explain_newfact_meta = {}
        repeatfact_meta = {}
        transition_meta = {}
        if option == "Explain" and subaction == "ExplainNewFact":
            explain_newfact_meta = dict(
                getattr(dialogue_planner_module, "LAST_EXPLAIN_NEWFACT_META", {}) or {}
            )
        if option == "Explain" and subaction == "RepeatFact":
            repeatfact_meta = dict(
                getattr(dialogue_planner_module, "LAST_REPEATFACT_META", {}) or {}
            )
        if option == "OfferTransition" and subaction == "SummarizeAndSuggest":
            transition_meta = dict(
                getattr(dialogue_planner_module, "LAST_TRANSITION_META", {}) or {}
            )
        selected_fact_ids = self._fact_bearing_selected_ids(
            option,
            subaction,
            explain_newfact_meta,
            repeatfact_meta,
        )

        response_text = generate_with_openai(
            prompt=prompt,
            subaction=subaction,
            model=self.model_name,
        )
        draft_response = response_text
        judge_result = {}
        judge_parse_ok = True
        judge_error = ""
        revised_response = None
        revised_once = 0
        final_response_source = "draft"

        if self.judge_enabled:
            action_description = get_action_description(subaction)
            history_for_judge = (
                list(reversed(conversation_history_rows[-10:]))
                if conversation_history_rows
                else dialogue_history[-10:]
            )
            judge_result, judge_parse_ok, judge_error = self._run_judge(
                option=option,
                subaction=subaction,
                action_description=action_description,
                exhibit_key=exhibit_key,
                current_aoi=current_aoi,
                user_message=user_message,
                history_for_judge=history_for_judge,
                candidate_response=draft_response,
                selected_fact_ids=selected_fact_ids,
            )

            if judge_result.get("decision") == "revise":
                revise_prompt = build_revise_prompt(
                    option=option,
                    subaction=subaction,
                    action_description=action_description,
                    original_prompt=prompt,
                    draft_response=draft_response,
                    revision_instruction=str(judge_result.get("revision_instruction", "")),
                )
                revised_response = generate_revision_text(
                    prompt=revise_prompt,
                    model=self.model_name,
                )
                if revised_response:
                    response_text = revised_response
                    revised_once = 1
                    final_response_source = "revised"
                    judge_result, judge_parse_ok, judge_error = self._run_judge(
                        option=option,
                        subaction=subaction,
                        action_description=action_description,
                        exhibit_key=exhibit_key,
                        current_aoi=current_aoi,
                        user_message=user_message,
                        history_for_judge=history_for_judge,
                        candidate_response=response_text,
                        selected_fact_ids=selected_fact_ids,
                    )

        if exhibit_key:
            realized_fact_ids = list((judge_result or {}).get("realized_fact_ids") or [])
            if selected_fact_ids:
                if realized_fact_ids:
                    self.facts_mentioned[exhibit_key].update(realized_fact_ids)
            else:
                self._update_facts_from_response(exhibit_key, response_text)
        self.turn_number += 1

        return {
            "action": result["action"],
            "option": option,
            "subaction": subaction,
            "prompt": prompt,
            "response": response_text,
            "draft_response": draft_response,
            "revised_response": revised_response,
            "revised_once": revised_once,
            "final_response_source": final_response_source,
            "judge_result": judge_result,
            "judge_parse_ok": 1 if judge_parse_ok else 0,
            "judge_error": judge_error,
            "selected_fact_ids": selected_fact_ids,
            "target_exhibit": target_exhibit,
            "input_exhibit": exhibit,
            "mapped_exhibit": exhibit_key,
            "explain_newfact_meta": explain_newfact_meta,
            "repeatfact_meta": repeatfact_meta,
            "transition_meta": transition_meta,
            "response_type": response_type,
            # What actually entered the obs[21:29] one-hot; differs from
            # response_type only when the boundary mapped/rejected a label.
            "state_response_type": state_response_type,
            # The masked legal set the policy chose from -- makes the stall and
            # forced-recovery masks auditable in the session logs.
            "available_options": result.get("available_options"),
            "obs_31": result.get("obs_31"),
            # On forced (silence) turns: what the policy would have done instead.
            "policy_action": result.get("policy_action"),
            "resolved_from": result.get("resolved_from"),
        }

    def get_state_snapshot(self) -> Dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "facts_mentioned": {
                exhibit: sorted(list(fact_ids))
                for exhibit, fact_ids in self.facts_mentioned.items()
            },
            "option_counts": dict(self.option_counts),
            "subaction_counts": dict(self.subaction_counts),
            "coverage": self._coverage_dict(),
        }
