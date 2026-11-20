"""One game as the app sees it: who sits where, what a human has selected, which
squares they can tap, and running AI turns. No UI code, so it can be tested."""
from __future__ import annotations

from talat.ai import make_agent
from talat.cli import format_action
from talat.engine import (
    Action, Capture, GameState, Move, Pass, Square, Tower, apply, is_terminal, legal_actions,
    legal_placements, new_game,
)

# Seat choices shown in the app: game-style names, with the algorithm behind each.
SEAT_CHOICES = {
    "human": "Human",
    "greedy": "Easy AI · Greedy",
    "paranoid": "Medium AI · Paranoid α-β",
    "maxn": "Medium AI · Max-n",
    "mcts": "Hard AI · MCTS",
}
SHORT_NAMES = {"human": "Human", "greedy": "Easy AI", "paranoid": "Medium AI", "maxn": "Medium AI", "mcts": "Hard AI"}

# Game modes: (title, subtitle, seats for P1, P2, P3)
PRESETS = {
    "solo": ("Solo", "You against two AIs", ("human", "paranoid", "mcts")),
    "friend": ("With a friend", "Two players against one AI", ("human", "human", "mcts")),
    "all": ("Pass & play", "Three players on one phone", ("human", "human", "human")),
    "watch": ("Watch", "Three AIs battle it out", ("greedy", "paranoid", "mcts")),
}


def seat_name(seat: str) -> str:
    """Short in-game name for a seat (any agent name works, e.g. 'random' in tests)."""
    return SHORT_NAMES.get(seat, seat.capitalize())


class Session:
    def __init__(self, seats: dict[int, str], time_limit: float = 1.0, seed: int | None = None):
        self.seats = dict(seats)
        self.time_limit = time_limit
        self.agents = {
            p: None if name == "human" else make_agent(name, None if seed is None else seed * 10 + p)
            for p, name in self.seats.items()
        }
        self.state: GameState = new_game()
        self.selected: tuple[str, Square] | None = None   # a human's tower picked during play
        self.selected_tower: Tower | None = None          # a human's tower picked during setup
        self.last: tuple[str, Square] | None = None       # where the last action landed
        self.log: list[str] = []

    # ---------- questions the UI asks ----------

    @property
    def to_move(self) -> int:
        return self.state.to_move

    def is_over(self) -> bool:
        return is_terminal(self.state)

    def is_human_turn(self) -> bool:
        return not self.is_over() and self.agents[self.state.to_move] is None

    def has_ai(self) -> bool:
        return any(agent is not None for agent in self.agents.values())

    def setup_tower(self) -> Tower | None:
        """The tower a human is about to place (their pick, or the strongest left)."""
        hand = self.state.hands[self.to_move]
        if self.selected_tower in hand:
            return self.selected_tower
        return max(hand, key=lambda t: t.rank) if hand else None

    def targets(self) -> dict[tuple[str, Square], Action]:
        """Squares a human can tap right now, and the action each one plays."""
        if not self.is_human_turn():
            return {}
        player = self.to_move
        if self.state.phase == "setup":
            tower = self.setup_tower()
            return {(a.board, a.square): a for a in legal_placements(self.state, player) if a.tower == tower}
        if self.selected is None:
            return {}
        board, square = self.selected
        return {
            (a.board, a.to): a for a in legal_actions(self.state, player)
            if isinstance(a, (Move, Capture)) and a.board == board and a.frm == square
        }

    def selectable(self, board: str, square: Square) -> bool:
        """Is this one of the human's towers that can do something?"""
        if not self.is_human_turn() or self.state.phase != "play":
            return False
        return any(
            isinstance(a, (Move, Capture)) and a.board == board and a.frm == square
            for a in legal_actions(self.state, self.to_move)
        )

    def playable_boards(self) -> list[str]:
        """The boards where the human to move can do something right now."""
        if not self.is_human_turn():
            return []
        if self.state.phase == "setup":
            return sorted({a.board for a in legal_placements(self.state, self.to_move)})
        return sorted({a.board for a in legal_actions(self.state, self.to_move) if isinstance(a, (Move, Capture))})

    def must_pass(self) -> bool:
        return self.is_human_turn() and legal_actions(self.state, self.to_move) == [Pass()]

    # ---------- things the UI does ----------

    def tap(self, board: str, square: Square) -> bool:
        """Handle a tap on a square. Returns True if an action was played."""
        if not self.is_human_turn():
            return False
        targets = self.targets()
        if (board, square) in targets:
            self.play(targets[(board, square)])
            return True
        if self.selectable(board, square):
            self.selected = None if self.selected == (board, square) else (board, square)
        else:
            self.selected = None
        return False

    def choose_tower(self, tower: Tower) -> None:
        if self.is_human_turn() and self.state.phase == "setup" and tower in self.state.hands[self.to_move]:
            self.selected_tower = tower

    def pass_turn(self) -> None:
        if self.must_pass():
            self.play(Pass())

    def think(self) -> Action:
        """Ask the AI whose turn it is for an action (slow; the app calls this off the UI thread)."""
        player = self.to_move
        return self.agents[player].choose_action(self.state, player, time_limit=self.time_limit)

    def play(self, action: Action) -> None:
        player = self.to_move
        self.state = apply(self.state, action)
        self.log.append(f"P{player}: {format_action(action)}")
        self.selected = None
        if hasattr(action, "square"):
            self.last = (action.board, action.square)
        elif hasattr(action, "to"):
            self.last = (action.board, action.to)
