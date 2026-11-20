"""The interface every TALAT agent implements, plus a random baseline."""
from __future__ import annotations

import random
from abc import ABC, abstractmethod

from talat.engine import Action, GameState, legal_actions


class Agent(ABC):
    """An AI player. Works in both phases: setup (placing towers) and play.

    Each agent owns a seeded random generator so games can be replayed exactly.
    """

    name = "agent"

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.last_stats: dict[str, float] = {}   # search effort of the last decision, for the metrics

    @abstractmethod
    def choose_action(self, state: GameState, player: int, time_limit: float | None = None) -> Action:
        """Return one of `legal_actions(state, player)`. `time_limit` is in seconds."""


class RandomAgent(Agent):
    """Picks any legal action uniformly at random."""

    name = "random"

    def choose_action(self, state: GameState, player: int, time_limit: float | None = None) -> Action:
        return self.rng.choice(legal_actions(state, player))
