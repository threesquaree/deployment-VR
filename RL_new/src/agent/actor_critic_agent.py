"""
Actor-Critic Agent for Option-Critic Architecture

This implements the agent that uses Actor-Critic learning for hierarchical
dialogue management in museum settings.

The agent learns:
- When to use each high-level option (Explain, Ask, Transition, Conclude)
- When to terminate the current option
- What low-level subactions to take within each option

The LLM (or template system) handles actual utterance generation based on
the agent's strategic decisions.
"""

import torch
import torch.nn.functional as F
import numpy as np
import random
from typing import Dict, List, Tuple, Optional, Any
from .networks import ActorCriticNetwork
from .termination_strategies import TerminationStrategy, LearnedTermination, get_termination_strategy


class ActorCriticAgent:
    """
    Actor-Critic Agent using Option-Critic architecture.
    
    This agent makes hierarchical decisions for museum dialogue:
    - Selects high-level options (dialogue strategies)
    - Selects low-level subactions within options
    - Learns when to terminate options
    - Uses action masking for dialogue coherence
    """
    
    def __init__(
        self,
        state_dim: int,
        options: List[str],
        subactions: Dict[str, List[str]],
        hidden_dim: int = 256,
        lstm_hidden_dim: int = 128,
        use_lstm: bool = True,
        device: str = 'cpu',
        termination_strategy: str = 'learned',
        epsilon_start: float = 0.3,
        epsilon_end: float = 0.05,
        epsilon_decay_episodes: int = 500
    ):
        """
        Initialize Actor-Critic agent.
        
        Args:
            state_dim: State dimension (149 with DialogueBERT)
            options: List of option names
            subactions: Dict mapping options to subaction lists
            hidden_dim: Hidden layer dimension
            lstm_hidden_dim: LSTM hidden dimension
            use_lstm: Use LSTM for temporal modeling
            device: 'cpu' or 'cuda'
            termination_strategy: Termination strategy name ('learned', 'fixed-3', 'threshold')
            epsilon_start: Initial epsilon for epsilon-greedy exploration (default 0.3)
            epsilon_end: Final epsilon after decay (default 0.05)
            epsilon_decay_episodes: Episodes over which to decay epsilon (default 500)
        """
        self.device = device
        self.options = options
        self.subactions = subactions
        self.num_options = len(options)
        self.max_subactions = max(len(subs) for subs in subactions.values())
        
        # Epsilon-greedy exploration parameters
        self.epsilon = epsilon_start
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay_episodes = epsilon_decay_episodes
        self.epsilon_decay_rate = (epsilon_start - epsilon_end) / epsilon_decay_episodes
        self.rng = random.Random()  # For epsilon-greedy sampling
        
        # Create network
        self.network = ActorCriticNetwork(
            state_dim=state_dim,
            num_options=self.num_options,
            num_subactions=self.max_subactions,
            hidden_dim=hidden_dim,
            lstm_hidden_dim=lstm_hidden_dim,
            use_lstm=use_lstm
        ).to(device)
        
        # Termination strategy (H5)
        self.termination_strategy = get_termination_strategy(termination_strategy)
        
        # Current option state
        self.current_option: Optional[int] = None
        self.steps_in_option: int = 0
        self.last_dwell: Optional[float] = None  # Track last dwell for threshold strategy
        
    def select_action(
        self,
        state: np.ndarray,
        available_options: List[str],
        available_subactions_dict: Dict[str, List[str]],
        deterministic: bool = False,
        last_dwell: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Select hierarchical action using Actor-Critic policy.
        
        Args:
            state: State vector (149-d with DialogueBERT)
            available_options: Available option names (for masking)
            available_subactions_dict: Available subactions per option
            deterministic: Use greedy selection if True
            last_dwell: Most recent dwell time (for threshold termination strategy)
            
        Returns:
            Action dictionary with option, subaction, termination info
        """
        # Update last dwell for threshold strategy
        if last_dwell is not None:
            self.last_dwell = last_dwell
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            outputs = self.network.forward(state_tensor)
        
        terminated = False
        
        # ===== OPTION SELECTION =====
        if self.current_option is None:
            # Select new option
            option_idx = self._select_option(
                outputs, available_options, deterministic
            )
            self.current_option = option_idx
            self.steps_in_option = 0
        else:
            # Check termination using configured strategy (H5)
            term_prob = outputs['termination_probs'][0, self.current_option].item()
            
            should_terminate = self.termination_strategy.should_terminate(
                termination_prob=term_prob,
                steps_in_option=self.steps_in_option,
                last_dwell=self.last_dwell,
                deterministic=deterministic
            )
            
            if should_terminate:
                terminated = True
                option_idx = self._select_option(
                    outputs, available_options, deterministic
                )
                self.current_option = option_idx
                self.steps_in_option = 0
            else:
                option_idx = self.current_option
                self.steps_in_option += 1
        
        option_name = self.options[option_idx]
        
        # ===== SUBACTION SELECTION =====
        available_subs = available_subactions_dict.get(option_name, [])
        subaction_idx, subaction_name = self._select_subaction(
            outputs, option_idx, option_name, available_subs, deterministic
        )
        
        return {
            'option': option_idx,
            'option_name': option_name,
            'subaction': subaction_idx,
            'subaction_name': subaction_name,
            'terminated': terminated,
            'steps_in_option': self.steps_in_option,
            'termination_strategy': self.termination_strategy.name
        }
    
    def _select_option(
        self,
        outputs: Dict[str, torch.Tensor],
        available_options: List[str],
        deterministic: bool
    ) -> int:
        """Select option with masking and epsilon-greedy exploration.
        
        Epsilon-greedy exploration forces random option selection with probability
        epsilon, ensuring the agent explores all options even when the policy
        is biased. This is critical for H6 where initial policy bias can cause
        one option to dominate (93% Explain observed without exploration).
        """
        # Get valid option indices for available options
        valid_indices = [self.options.index(opt) for opt in available_options if opt in self.options]
        
        if not valid_indices:
            return 0  # Fallback
        
        # Epsilon-greedy exploration (only in non-deterministic mode)
        if not deterministic and self.rng.random() < self.epsilon:
            # Random exploration: uniformly sample from available options
            return self.rng.choice(valid_indices)
        
        # Normal softmax selection from policy
        option_logits = outputs['option_logits'][0]
        
        # Create mask
        mask = torch.full((self.num_options,), -1e10, device=self.device)
        for opt_name in available_options:
            if opt_name in self.options:
                idx = self.options.index(opt_name)
                mask[idx] = 0.0
        
        masked_logits = option_logits + mask
        probs = F.softmax(masked_logits, dim=-1)
        
        if deterministic:
            return torch.argmax(probs).item()
        else:
            return torch.multinomial(probs, 1).item()
    
    def _select_subaction(
        self,
        outputs: Dict[str, torch.Tensor],
        option_idx: int,
        option_name: str,
        available_subactions: List[str],
        deterministic: bool
    ) -> Tuple[int, str]:
        """Select subaction with masking."""
        subaction_logits = outputs['intra_option_logits'][option_idx][0]
        
        all_subs = self.subactions[option_name]
        
        # Create mask
        mask = torch.full((self.max_subactions,), -1e10, device=self.device)
        for sub_name in available_subactions:
            if sub_name in all_subs:
                idx = all_subs.index(sub_name)
                if idx < self.max_subactions:
                    mask[idx] = 0.0
        
        masked_logits = subaction_logits + mask
        probs = F.softmax(masked_logits, dim=-1)
        
        if deterministic:
            subaction_idx = torch.argmax(probs).item()
        else:
            subaction_idx = torch.multinomial(probs, 1).item()
        
        if subaction_idx < len(all_subs):
            subaction_name = all_subs[subaction_idx]
        else:
            subaction_name = all_subs[0] if all_subs else "Unknown"
        
        return subaction_idx, subaction_name
    
    def get_values(self, state: np.ndarray) -> Dict[str, float]:
        """Get all value estimates for a state."""
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            outputs = self.network.forward(state_tensor)
        
        return {
            'state_value': outputs['state_value'][0].item(),
            'option_values': outputs['option_values'][0].cpu().numpy(),
            'action_values': [av[0].cpu().numpy() for av in outputs['action_values']]
        }
    
    def reset(self):
        """Reset for new episode."""
        self.current_option = None
        self.steps_in_option = 0
        self.network.reset_hidden_state()
    
    def decay_epsilon(self):
        """Decay epsilon for epsilon-greedy exploration.
        
        Should be called once per episode. Linearly decays epsilon from
        epsilon_start to epsilon_end over epsilon_decay_episodes.
        """
        if self.epsilon > self.epsilon_end:
            self.epsilon = max(self.epsilon_end, self.epsilon - self.epsilon_decay_rate)
    
    def get_epsilon(self) -> float:
        """Get current epsilon value for logging."""
        return self.epsilon
    
    def set_epsilon(self, epsilon: float):
        """Manually set epsilon (useful for evaluation or resuming training)."""
        self.epsilon = max(self.epsilon_end, min(self.epsilon_start, epsilon))
    
    def save(self, path: str):
        """Save agent."""
        torch.save({
            'network': self.network.state_dict(),
            'options': self.options,
            'subactions': self.subactions
        }, path)
    
    def load(self, path: str):
        """Load agent."""
        checkpoint = torch.load(path, map_location=self.device)
        self.network.load_state_dict(checkpoint['network'])

