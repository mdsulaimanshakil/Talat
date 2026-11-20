"""AI 3: Monte Carlo Tree Search with UCB1.

Each iteration runs the four MCTS steps:
1. Selection: from the root, follow the child with the highest
   UCB1 = t_i / n_i + C * sqrt(ln N / n_i) while the node is fully expanded.
2. Expansion: add one untried action as a new child.
3. Simulation (rollout): play quick, mostly random actions. When a capture is
   available it is taken 90% of the time, so rollouts look a bit more like
   real play. The rollout stops after 20 actions (or at the end of the game)
   and the player(s) leading on score count as the winner.
4. Backpropagation: walk back to the root adding the result to every node.

Rewards are a vector, one entry per player (1 for the winner, split on a tie).
Each node stores the reward of the player who moved into it, so every player
in the tree maximises its own result. After the budget runs out, the most
visited root action is played.
"""
from __future__ import annotations

import math
import time

from talat.ai.base import Agent
from talat.ai.greedy import GreedyAgent
from talat.engine import PLAYERS, Action, Capture, GameState, apply, is_terminal, legal_actions, winners

DEFAULT_ITERATIONS = 1000   # used when no time limit is given


class Node:
    """A search-tree node. There is no parent link: backpropagation follows the path
    recorded during selection, so the tree has no cycles and is freed as soon as the
    search ends (instead of whenever Python's garbage collector next runs)."""
    __slots__ = ("state", "action", "mover", "children", "untried", "visits", "reward")

    def __init__(self, state: GameState, action: Action | None = None, mover: int | None = None):
        self.state = state
        self.action = action
        self.mover = mover                  # the player who played `action` to reach this node
        self.children: list[Node] = []
        self.untried: list[Action] | None = None   # filled in on first visit
        self.visits = 0
        self.reward = 0.0                   # total reward for `mover`

    def ucb1(self, c: float, log_parent_visits: float) -> float:
        return self.reward / self.visits + c * math.sqrt(log_parent_visits / self.visits)


def result_vector(state: GameState) -> list[float]:
    """1 for each winner, shared on a tie; 0 for everyone else.
    If the rollout was cut short, the current leader(s) count as winners."""
    win = winners(state)
    return [1.0 / len(win) if p in win else 0.0 for p in PLAYERS]


class MctsAgent(Agent):
    name = "mcts"

    def __init__(self, seed: int | None = None, c: float = math.sqrt(2), iterations: int | None = None,
                 rollout_cap: int = 20, capture_bias: float = 0.9):
        super().__init__(seed)
        self.c = c
        self.iterations = iterations
        self.rollout_cap = rollout_cap
        self.capture_bias = capture_bias   # chance a rollout takes a capture when one exists
        self._setup = GreedyAgent(seed)

    def choose_action(self, state: GameState, player: int, time_limit: float | None = None) -> Action:
        if state.phase == "setup":
            self.last_stats = {"rollouts": 0}
            return self._setup.choose_action(state, player)
        actions = legal_actions(state, player)
        if len(actions) == 1:
            self.last_stats = {"rollouts": 0}
            return actions[0]

        start = time.perf_counter()
        deadline = None if time_limit is None else start + time_limit
        budget = self.iterations if self.iterations is not None else (None if deadline else DEFAULT_ITERATIONS)
        root = Node(state)
        done = 0
        while (budget is None or done < budget) and (deadline is None or time.perf_counter() < deadline):
            self._iterate(root)
            done += 1

        most = max(child.visits for child in root.children)
        best = [child.action for child in root.children if child.visits == most]
        self.last_stats = {"rollouts": done, "seconds": time.perf_counter() - start}
        return self.rng.choice(best)

    def _iterate(self, root: Node) -> None:
        node = root
        path = [root]
        # 1. Selection
        while True:
            if node.untried is None:
                node.untried = [] if is_terminal(node.state) else legal_actions(node.state, node.state.to_move)
                self.rng.shuffle(node.untried)
            if node.untried or not node.children:
                break
            log_n = math.log(node.visits)
            node = max(node.children, key=lambda ch: ch.ucb1(self.c, log_n))
            path.append(node)
        # 2. Expansion
        if node.untried:
            action = node.untried.pop()
            child = Node(apply(node.state, action), action, node.state.to_move)
            node.children.append(child)
            node = child
            path.append(node)
        # 3. Simulation
        reward = self._rollout(node.state)
        # 4. Backpropagation
        for node in path:
            node.visits += 1
            if node.mover is not None:
                node.reward += reward[node.mover - 1]

    def _rollout(self, state: GameState) -> list[float]:
        steps = 0
        while not is_terminal(state) and steps < self.rollout_cap:
            actions = legal_actions(state, state.to_move)
            # legal_actions lists captures first
            if self.capture_bias and isinstance(actions[0], Capture) and self.rng.random() < self.capture_bias:
                actions = [a for a in actions if isinstance(a, Capture)]
            state = apply(state, self.rng.choice(actions))
            steps += 1
        return result_vector(state)
