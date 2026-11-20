"""AI 2: multi-player minimax.

Two modes:
- "maxn": Max^n search. Every node returns a utility vector [U1, U2, U3] and the
  player to move picks the child that maximises its own component.
- "paranoid": the other two players are treated as one opponent who minimises
  the root player's advantage, which turns it into two-player minimax and allows
  alpha-beta pruning.

Both search depth-first to a fixed number of plies (one ply = one player's
action; 3 plies = one full round), using iterative deepening so a time limit
can stop the search early and the last fully searched depth is used.
"""
from __future__ import annotations

import time

from talat.ai.base import Agent
from talat.ai.greedy import GreedyAgent
from talat.engine import (
    BOTTOM_ROW, PLAYERS, Action, Capture, GameState, apply, is_frozen, is_terminal, legal_actions,
    scores, tower_actions, winners,
)

ROW_ADVANCED = 1.0     # per row a tower has moved towards the enemy line
THREATENED = -2.5      # per tower an enemy could capture right now (half a capture)
WIN_BONUS = 50.0       # added at a finished game for the winner(s)


class OutOfTime(Exception):
    pass


def evaluate(state: GameState) -> tuple[float, ...]:
    """Utility vector at a cutoff: the score so far plus the greedy positional terms."""
    pts = scores(state)
    if is_terminal(state):
        win = winners(state)
        return tuple(pts[p] + (WIN_BONUS if p in win else 0.0) for p in PLAYERS)
    u = {p: float(pts[p]) for p in PLAYERS}
    for board in state.boards.values():
        frozen = is_frozen(board)
        threatened: set[tuple[int, int]] = set()
        if not frozen:
            for sq, tower in board.towers():
                threatened.update(a.to for a in tower_actions(board, sq) if isinstance(a, Capture))
        for (r, c), tower in board.towers():
            start = 0 if tower.owner == board.top else BOTTOM_ROW
            u[tower.owner] += ROW_ADVANCED * abs(r - start)
            if (r, c) in threatened:
                u[tower.owner] += THREATENED
    return tuple(u[p] for p in PLAYERS)


class MaxnAgent(Agent):
    name = "maxn"

    def __init__(self, seed: int | None = None, mode: str = "maxn", max_depth: int = 3):
        super().__init__(seed)
        if mode not in ("maxn", "paranoid"):
            raise ValueError("mode must be 'maxn' or 'paranoid'")
        self.mode = mode
        self.max_depth = max_depth
        self.name = mode
        self._setup = GreedyAgent(seed)
        self._deadline: float | None = None
        self._nodes = 0

    def choose_action(self, state: GameState, player: int, time_limit: float | None = None) -> Action:
        if state.phase == "setup":
            self.last_stats = {"nodes": 0, "depth": 0}
            return self._setup.choose_action(state, player)

        actions = legal_actions(state, player)
        start = time.perf_counter()
        self._deadline = None if time_limit is None else start + time_limit
        self._nodes = 0
        best, depth_done = [actions[0]], 0
        if len(actions) > 1:
            for depth in range(1, self.max_depth + 1):
                try:
                    best = self._search_root(state, player, actions, depth)
                    depth_done = depth
                except OutOfTime:
                    break
        self.last_stats = {"nodes": self._nodes, "depth": depth_done, "seconds": time.perf_counter() - start}
        return self.rng.choice(best)

    # ---------- root ----------

    def _search_root(self, state: GameState, player: int, actions: list[Action], depth: int) -> list[Action]:
        """All root actions with the best value (ties are broken randomly by the caller)."""
        values = []
        alpha = float("-inf")
        for action in actions:
            child = apply(state, action)
            if self.mode == "maxn":
                value = self._maxn(child, depth - 1)[player - 1]
            else:
                value = self._paranoid(child, depth - 1, player, alpha, float("inf"))
                alpha = max(alpha, value)
            values.append(value)
        best = max(values)
        return [a for a, v in zip(actions, values) if v == best]

    def _tick(self) -> None:
        self._nodes += 1
        if self._deadline is not None and self._nodes % 16 == 0 and time.perf_counter() > self._deadline:
            raise OutOfTime

    # ---------- Max^n ----------

    def _maxn(self, state: GameState, depth: int) -> tuple[float, ...]:
        self._tick()
        if depth == 0 or is_terminal(state):
            return evaluate(state)
        mover = state.to_move
        best: tuple[float, ...] | None = None
        for action in legal_actions(state, mover):
            value = self._maxn(apply(state, action), depth - 1)
            if best is None or value[mover - 1] > best[mover - 1]:
                best = value
        return best

    # ---------- Paranoid alpha-beta ----------

    @staticmethod
    def _advantage(u: tuple[float, ...], root: int) -> float:
        """Root player's utility minus the average of the other two."""
        others = [u[p - 1] for p in PLAYERS if p != root]
        return u[root - 1] - sum(others) / len(others)

    def _paranoid(self, state: GameState, depth: int, root: int, alpha: float, beta: float) -> float:
        self._tick()
        if depth == 0 or is_terminal(state):
            return self._advantage(evaluate(state), root)
        mover = state.to_move
        if mover == root:
            value = float("-inf")
            for action in legal_actions(state, mover):
                value = max(value, self._paranoid(apply(state, action), depth - 1, root, alpha, beta))
                alpha = max(alpha, value)
                if alpha >= beta:
                    break   # beta cut: the opponents would never allow this line
            return value
        value = float("inf")
        for action in legal_actions(state, mover):
            value = min(value, self._paranoid(apply(state, action), depth - 1, root, alpha, beta))
            beta = min(beta, value)
            if alpha >= beta:
                break       # alpha cut: I already have something better elsewhere
        return value


class ParanoidAgent(MaxnAgent):
    name = "paranoid"

    def __init__(self, seed: int | None = None, max_depth: int = 3):
        super().__init__(seed, mode="paranoid", max_depth=max_depth)
