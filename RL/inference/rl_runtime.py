import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow local package imports when used as a standalone folder.
runtime_dir = Path(__file__).parent
project_root = runtime_dir.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(runtime_dir))

from model_loader import create_agent_from_checkpoint, load_model_checkpoint
from exhibit_mapping import ExhibitMapping
from state_builder import get_projection_matrix
from prompt.openai_generator import generate_judge_json, generate_revision_text, generate_with_openai
from prompt.action_descriptions import get_action_description
from prompt.judge import build_judge_prompt
from prompt.judge_schema import build_fallback_judge_result, parse_and_validate_judge_output
from prompt.revise import build_revise_prompt
from src.utils.dialogue_planner import build_prompt
from src.utils import dialogue_planner as dialogue_planner_module
from src.utils.dialoguebert_intent_recognizer import get_dialoguebert_recognizer
from src.utils.knowledge_graph import SimpleKnowledgeGraph
from test_model import get_agent_response


class RLMuseumRuntime:
    """
    Minimal runtime for RL inference + prompt planning + OpenAI generation.
    Keeps only deployment-time pieces (no training loop).
    """

    def __init__(
        self,
        checkpoint_path: str,
        knowledge_graph_path: str,
        mapping_path: Optional[str] = None,
        device: str = "cpu",
        model_name: str = "gpt-5.4",
        judge_enabled: bool = False,
        judge_fail_policy: str = "pass",
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.knowledge_graph_path = Path(knowledge_graph_path)
        self.device = device
        self.model_name = model_name
        self.judge_enabled = bool(judge_enabled)
        self.judge_fail_policy = str(judge_fail_policy or "pass").strip().lower()

        self.knowledge_graph = SimpleKnowledgeGraph(str(self.knowledge_graph_path))
        self.checkpoint = load_model_checkpoint(str(self.checkpoint_path), device=device)
        self.agent, self.model_type, self.metadata = create_agent_from_checkpoint(self.checkpoint, device=device)

        self.options = self.metadata["options"]
        self.subactions = self.metadata["subactions"]
        self.state_dim = self.metadata["state_dim"]
        self.projection_matrix = get_projection_matrix()
        self.bert_recognizer = get_dialoguebert_recognizer()
        resolved_mapping_path = Path(mapping_path) if mapping_path else project_root / "KG" / "neo4j_to_rl_mapping.json"
        self.mapping = ExhibitMapping(str(resolved_mapping_path))

        self.facts_mentioned = defaultdict(set)
        self.option_counts = defaultdict(int)
        self.turn_number = 0

    def _pick_transition_target(self, current_exhibit: str) -> Optional[str]:
        exhibit_names = self.knowledge_graph.get_exhibit_names()
        if not exhibit_names:
            return None
        others = [x for x in exhibit_names if x != current_exhibit]
        if not others:
            return current_exhibit
        # Prefer exhibits with lowest mentioned fact count.
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
        forced_option: Optional[str] = None,
        forced_subaction: Optional[str] = None,
    ) -> Dict[str, Any]:
        exhibit_key = self.mapping.to_exhibit_key(exhibit) if exhibit else ""
        if forced_option or forced_subaction:
            if not forced_option or not forced_subaction:
                raise ValueError("forced_option and forced_subaction must be provided together.")
            available_subactions = self.subactions.get(forced_option, [])
            if forced_subaction not in available_subactions:
                raise ValueError(
                    f"Invalid forced action '{forced_option}/{forced_subaction}' for the active action space."
                )
            option = forced_option
            subaction = forced_subaction
            result = {
                "action": f"{option}/{subaction}",
                "option": option,
                "subaction": subaction,
                "state_vector": None,
                "action_dict": None,
            }
        else:
            result = get_agent_response(
                agent=self.agent,
                user_message=user_message,
                exhibit=exhibit_key,
                dialogue_history=dialogue_history,
                knowledge_graph=self.knowledge_graph,
                options=self.options,
                subactions=self.subactions,
                facts_mentioned=self.facts_mentioned,
                option_counts=self.option_counts,
                turn_number=self.turn_number,
                projection_matrix=self.projection_matrix,
                bert_recognizer=self.bert_recognizer,
                state_dim=self.state_dim,
                response_type=response_type,
            )

            option = result["option"]
            subaction = result["subaction"]
        self.option_counts[option] += 1

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
        }

    def get_state_snapshot(self) -> Dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "facts_mentioned": {
                exhibit: sorted(list(fact_ids))
                for exhibit, fact_ids in self.facts_mentioned.items()
            },
            "option_counts": dict(self.option_counts),
            "coverage": self._coverage_dict(),
        }
