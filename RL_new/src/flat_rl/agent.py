from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from .networks import FlatPolicyNetwork


class FlatActorCriticAgent:
    """
    Actor-Critic agent for the flat action space variant.

    The agent learns a single policy over all primitive subactions while still
    exposing the same interface expected by the hierarchical training loop
    (option / subaction indices) for compatibility.
    """

    def __init__(
        self,
        state_dim: int,
        options: List[str],
        subactions: Dict[str, List[str]],
        hidden_dim: int = 256,
        lstm_hidden_dim: int = 128,
        use_lstm: bool = True,
        device: str = "cpu",
    ):
        self.device = device
        self.options = options
        self.subactions = subactions
        self.flat_actions: List[Tuple[str, str]] = []
        for option in options:
            for sub in subactions[option]:
                self.flat_actions.append((option, sub))

        self.network = FlatPolicyNetwork(
            state_dim=state_dim,
            action_dim=len(self.flat_actions),
            hidden_dim=hidden_dim,
            lstm_hidden_dim=lstm_hidden_dim,
            use_lstm=use_lstm,
        ).to(device)

        # Cached tensors for efficiency
        self._option_to_index = {opt: idx for idx, opt in enumerate(self.options)}
        self._subaction_to_index = {
            opt: {sub: idx for idx, sub in enumerate(self.subactions[opt])}
            for opt in self.options
        }

    # ------------------------------------------------------------------ #
    # Core API
    # ------------------------------------------------------------------ #
    def select_action(
        self,
        state: np.ndarray,
        available_options: List[str],
        available_subactions_dict: Dict[str, List[str]],
        deterministic: bool = False,
    ) -> Dict[str, Any]:
        """
        Sample (or greedily select) a flat action with masking and return a
        dictionary compatible with the hierarchical training loop.
        """
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

        with torch.no_grad():
            outputs = self.network.forward(state_tensor)
            logits = outputs["action_logits"][0]

        mask = torch.full((len(self.flat_actions),), -1e10, device=self.device)
        for idx, (option, subaction) in enumerate(self.flat_actions):
            if option not in available_options:
                continue
            available_subs = available_subactions_dict.get(option, [])
            if subaction in available_subs:
                mask[idx] = 0.0

        masked_logits = logits + mask
        probs = F.softmax(masked_logits, dim=-1)

        if deterministic:
            action_idx = torch.argmax(probs).item()
        else:
            action_idx = torch.multinomial(probs, 1).item()

        option_name, subaction_name = self.flat_actions[action_idx]
        option_index = self._option_to_index[option_name]
        subaction_index = self._subaction_to_index[option_name][subaction_name]

        return {
            "option": option_index,
            "option_name": option_name,
            "subaction": subaction_index,
            "subaction_name": subaction_name,
            "terminated": False,
            "flat_action": action_idx,
        }

    def reset(self):
        self.network.reset_hidden_state()

    def save(self, path: str):
        torch.save(
            {
                "network": self.network.state_dict(),
                "options": self.options,
                "subactions": self.subactions,
            },
            path,
        )

    def load(self, path: str):
        checkpoint = torch.load(path, map_location=self.device)
        self.network.load_state_dict(checkpoint["network"])

    # ------------------------------------------------------------------ #
    # Utility helpers
    # ------------------------------------------------------------------ #
    def map_option_subaction_to_flat(self, option_idx: int, subaction_idx: int) -> int:
        option_name = self.options[option_idx]
        sub_name = self.subactions[option_name][subaction_idx]
        return self.flat_actions.index((option_name, sub_name))


__all__ = ["FlatActorCriticAgent"]


