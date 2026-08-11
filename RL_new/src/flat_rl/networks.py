from typing import Dict

import torch
import torch.nn as nn


class FlatPolicyNetwork(nn.Module):
    """
    Simple Actor-Critic network producing a single joint policy over the flat
    action space and a state value estimate.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 256,
        lstm_hidden_dim: int = 128,
        use_lstm: bool = True,
    ):
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.use_lstm = use_lstm

        if use_lstm:
            self.encoder = nn.LSTM(
                input_size=state_dim,
                hidden_size=lstm_hidden_dim,
                num_layers=1,
                batch_first=True,
            )
            encoder_dim = lstm_hidden_dim
        else:
            self.encoder = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
            )
            encoder_dim = hidden_dim

        # Shared torso for policy/value heads
        self.policy_head = nn.Sequential(
            nn.Linear(encoder_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim),
        )

        self.value_head = nn.Sequential(
            nn.Linear(encoder_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

        self.hidden_state = None

    def forward(self, state: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Args:
            state: shape (batch, state_dim) or (batch, seq_len, state_dim)
        """
        if self.use_lstm:
            if state.dim() == 2:
                state = state.unsqueeze(1)

            if self.hidden_state is not None:
                encoded, self.hidden_state = self.encoder(state, self.hidden_state)
            else:
                encoded, self.hidden_state = self.encoder(state)

            encoded = encoded[:, -1, :]
        else:
            encoded = self.encoder(state)

        logits = self.policy_head(encoded)
        values = self.value_head(encoded).squeeze(-1)

        return {
            "action_logits": logits,
            "state_value": values,
        }

    def reset_hidden_state(self):
        self.hidden_state = None


__all__ = ["FlatPolicyNetwork"]


