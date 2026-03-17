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
from prompt.openai_generator import generate_with_openai
from src.utils.dialogue_planner import build_prompt
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
        model_name: str = "gpt-4o-mini",
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.knowledge_graph_path = Path(knowledge_graph_path)
        self.device = device
        self.model_name = model_name

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

    def generate_turn(
        self,
        user_message: str,
        exhibit: str,
        dialogue_history: List[Tuple[str, str, int]],
    ) -> Dict[str, Any]:
        exhibit_key = self.mapping.to_exhibit_key(exhibit)
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
        )

        option = result["option"]
        subaction = result["subaction"]
        self.option_counts[option] += 1

        all_facts = self.knowledge_graph.get_exhibit_facts(exhibit_key)
        mentioned_ids = self.facts_mentioned.get(exhibit_key, set())
        mentioned_facts = [
            f for f in all_facts if self.knowledge_graph.extract_fact_id(f) in mentioned_ids
        ]
        unmentioned_facts = [
            f for f in all_facts if self.knowledge_graph.extract_fact_id(f) not in mentioned_ids
        ]

        facts_for_prompt = unmentioned_facts if option == "Explain" else all_facts
        target_exhibit = None
        if option == "OfferTransition" or subaction in ("SuggestMove", "SummarizeAndSuggest"):
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
            target_exhibit=target_exhibit,
            coverage_dict=self._coverage_dict(),
        )

        response_text = generate_with_openai(
            prompt=prompt,
            subaction=subaction,
            model=self.model_name,
        )
        self._update_facts_from_response(exhibit_key, response_text)
        self.turn_number += 1

        return {
            "action": result["action"],
            "option": option,
            "subaction": subaction,
            "prompt": prompt,
            "response": response_text,
            "target_exhibit": target_exhibit,
            "input_exhibit": exhibit,
            "mapped_exhibit": exhibit_key,
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
