"""AI 1: Greedy Best-First Search, f(n) = h(n).

Looks one action ahead: every legal action on both of the player's boards is
scored by the heuristic h of the state it leads to, and the best one is played
(ties broken at random). No lookahead beyond that.
"""
from __future__ import annotations

from talat.ai.base import Agent
from talat.engine import (
    BOARD_SIZE, BOTTOM_ROW, TOP_ROW, Action, Capture, GameState, Move, Place, apply, boards_of,
    is_frozen, legal_actions, tower_actions,
)

CAPTURE = 5
REACH_LINE = 3
FORWARD = 1
DANGER = -5   # the opponent would gain 5 by capturing the tower


def heuristic(state: GameState, action: Action, player: int) -> int:
    """h(n) for the state reached by `action`, from `player`'s point of view."""
    if not isinstance(action, (Move, Capture)):
        return 0
    board = state.boards[action.board]
    forward = board.forward(player)
    enemy_line = BOTTOM_ROW if forward == 1 else TOP_ROW

    h = 0
    if isinstance(action, Capture):
        h += CAPTURE
    if action.to[0] == enemy_line:
        h += REACH_LINE
    if action.to[0] - action.frm[0] == forward:
        h += FORWARD
    if is_threatened(apply(state, action).boards[action.board], action.to, player):
        h += DANGER
    return h


def is_threatened(board, square, player: int) -> bool:
    """Can an enemy tower on this board capture whatever stands on `square`?"""
    if is_frozen(board):
        return False
    for sq, tower in board.towers():
        if tower.owner != player and any(
            isinstance(a, Capture) and a.to == square for a in tower_actions(board, sq)
        ):
            return True
    return False


class GreedyAgent(Agent):
    name = "greedy"

    def choose_action(self, state: GameState, player: int, time_limit: float | None = None) -> Action:
        actions = legal_actions(state, player)
        if state.phase == "setup":
            return self.place(state, player, actions)
        scored = [(heuristic(state, a, player), a) for a in actions]
        self.last_stats = {"nodes": len(scored)}
        best = max(h for h, _ in scored)
        return self.rng.choice([a for h, a in scored if h == best])

    def place(self, state: GameState, player: int, actions: list[Action]) -> Place:
        """Setup: strongest tower first, onto whichever of my boards has fewer of my
        towers, as close to the middle column as possible (it can reach more squares)."""
        tower = max(state.hands[player], key=lambda t: t.rank)
        mine = {
            name: sum(t.owner == player for _, t in state.boards[name].towers())
            for name in boards_of(player)
        }
        options = [a for a in actions if isinstance(a, Place) and a.tower == tower]
        middle = BOARD_SIZE // 2
        best = min((mine[a.board], abs(a.square[1] - middle)) for a in options)
        return self.rng.choice([a for a in options if (mine[a.board], abs(a.square[1] - middle)) == best])
