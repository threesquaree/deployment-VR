"""
Termination Strategies for Option-Critic Architecture

This module implements different termination strategies for H5:
- Learned: Option-Critic β(s) trained end-to-end (baseline)
- Fixed-3: Options always terminate after exactly 3 turns
- Threshold: Options terminate when dwell drops below 0.5

Usage:
    strategy = FixedDurationTermination(duration=3)
    should_terminate = strategy.should_terminate(
        termination_prob=0.3,  # From network (ignored by fixed strategies)
        steps_in_option=2,
        last_dwell=0.6,
        deterministic=False
    )
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class TerminationStrategy(ABC):
    """Abstract base class for termination strategies."""
    
    @abstractmethod
    def should_terminate(
        self,
        termination_prob: float,
        steps_in_option: int,
        last_dwell: Optional[float] = None,
        deterministic: bool = False
    ) -> bool:
        """
        Determine whether the current option should terminate.
        
        Args:
            termination_prob: Learned termination probability from network β(s)
            steps_in_option: Number of turns spent in current option
            last_dwell: Most recent dwell time (engagement signal)
            deterministic: If True, use deterministic decision
            
        Returns:
            True if option should terminate, False otherwise
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy name for logging."""
        pass


class LearnedTermination(TerminationStrategy):
    """
    Learned termination via Option-Critic β(s).
    
    This is the baseline strategy where termination probability is
    learned end-to-end and sampled stochastically.
    """
    
    def should_terminate(
        self,
        termination_prob: float,
        steps_in_option: int,
        last_dwell: Optional[float] = None,
        deterministic: bool = False
    ) -> bool:
        if deterministic:
            return termination_prob > 0.5
        else:
            return np.random.random() < termination_prob
    
    @property
    def name(self) -> str:
        return "learned"


class FixedDurationTermination(TerminationStrategy):
    """
    Fixed-duration termination: options always terminate after N turns.
    
    This strategy ignores learned termination probabilities and engagement
    signals, terminating strictly based on turn count.
    
    Args:
        duration: Number of turns before termination (default: 3)
    """
    
    def __init__(self, duration: int = 3):
        self.duration = duration
    
    def should_terminate(
        self,
        termination_prob: float,
        steps_in_option: int,
        last_dwell: Optional[float] = None,
        deterministic: bool = False
    ) -> bool:
        # Terminate after exactly `duration` turns
        # steps_in_option is 0-indexed, so terminate when >= duration
        return steps_in_option >= self.duration
    
    @property
    def name(self) -> str:
        return f"fixed-{self.duration}"


class ThresholdTermination(TerminationStrategy):
    """
    Engagement-threshold termination: terminate when dwell drops below threshold.
    
    This strategy is reactive to engagement but not learned. It terminates
    options when the visitor's dwell time falls below a threshold, indicating
    disengagement.
    
    Args:
        threshold: Dwell threshold below which to terminate (default: 0.5)
        min_turns: Minimum turns before threshold can trigger (default: 1)
    """
    
    def __init__(self, threshold: float = 0.5, min_turns: int = 1):
        self.threshold = threshold
        self.min_turns = min_turns
    
    def should_terminate(
        self,
        termination_prob: float,
        steps_in_option: int,
        last_dwell: Optional[float] = None,
        deterministic: bool = False
    ) -> bool:
        # Don't terminate before minimum turns
        if steps_in_option < self.min_turns:
            return False
        
        # If no dwell provided, don't terminate
        if last_dwell is None:
            return False
        
        # Terminate if dwell is below threshold
        return last_dwell < self.threshold
    
    @property
    def name(self) -> str:
        return f"threshold-{self.threshold}"


def get_termination_strategy(strategy_name: str, **kwargs) -> TerminationStrategy:
    """
    Factory function to get termination strategy by name.
    
    Args:
        strategy_name: One of "learned", "fixed-3", "threshold"
        **kwargs: Additional arguments for specific strategies
        
    Returns:
        TerminationStrategy instance
    """
    strategy_name = strategy_name.lower()
    
    if strategy_name == "learned":
        return LearnedTermination()
    elif strategy_name.startswith("fixed"):
        # Parse duration from name like "fixed-3" or use default
        if "-" in strategy_name:
            duration = int(strategy_name.split("-")[1])
        else:
            duration = kwargs.get("duration", 3)
        return FixedDurationTermination(duration=duration)
    elif strategy_name.startswith("threshold"):
        # Parse threshold from name like "threshold-0.5" or use default
        if "-" in strategy_name:
            threshold = float(strategy_name.split("-")[1])
        else:
            threshold = kwargs.get("threshold", 0.5)
        min_turns = kwargs.get("min_turns", 1)
        return ThresholdTermination(threshold=threshold, min_turns=min_turns)
    else:
        raise ValueError(f"Unknown termination strategy: {strategy_name}")

