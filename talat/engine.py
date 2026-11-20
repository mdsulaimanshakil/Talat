"""TALAT game engine: towers, boards, game state and rules.

Board coordinates are (row, col), both 0-4. Row 0 is the top player's starting
line and row 4 the bottom player's. States are never changed in place:
`apply` returns a new state, so the AIs can search freely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Union

PLAYERS = (1, 2, 3)
PLAYER_NAMES = {1: "White", 2: "Black", 3: "Grey"}
BOARD_SIZE = 5
TOP_ROW, BOTTOM_ROW = 0, BOARD_SIZE - 1
MAX_ACTIONS = 300        # safety limit on play-phase actions
CAPTURE_POINTS = 5
STARTING_LINE_POINTS = 3

# Board name -> (top player, bottom player)
BOARD_PLAYERS = {"A": (1, 2), "B": (2, 3), "C": (3, 1)}

Square = tuple[int, int]


class Size(IntEnum):
    S = 1
    M = 2
    L = 3


class Shape(IntEnum):
    """The value is the number of sides."""
    T = 3
    Q = 4
    H = 6


@dataclass(frozen=True)
class Tower:
    owner: int
    size: Size
    shape: Shape

    @property
    def code(self) -> str:
        """Short name such as '1LH' (player 1, large hexagon)."""
        return f"{self.owner}{self.size.name}{self.shape.name}"

    @property
    def rank(self) -> tuple[int, int]:
        """Strength used for tie-breaks: size first, then number of sides."""
        return (self.size, self.shape)

    def __repr__(self) -> str:
        return self.code


def full_set(owner: int) -> tuple[Tower, ...]:
    """The 9 towers a player starts with: every size and shape, strongest first."""
    return tuple(Tower(owner, size, shape) for size in reversed(Size) for shape in reversed(Shape))


# ---------- Actions ----------

@dataclass(frozen=True)
class Place:
    """Setup phase: put a tower from your hand on your own starting line."""
    tower: Tower
    board: str
    square: Square


@dataclass(frozen=True)
class Move:
    """Move a tower one square forward (straight or diagonal) to an empty square."""
    board: str
    frm: Square
    to: Square


@dataclass(frozen=True)
class Capture:
    """Capture the enemy tower on `to`; your tower moves onto that square."""
    board: str
    frm: Square
    to: Square


@dataclass(frozen=True)
class Pass:
    """Only allowed when the player has no other legal action."""


Action = Union[Place, Move, Capture, Pass]


class IllegalAction(ValueError):
    pass


# ---------- Board ----------

@dataclass
class Board:
    name: str
    top: int
    bottom: int
    grid: list[list[Tower | None]]
    # Cached result of is_frozen(); cleared whenever a square changes.
    _frozen: bool | None = field(default=None, repr=False, compare=False)

    @classmethod
    def empty(cls, name: str) -> Board:
        top, bottom = BOARD_PLAYERS[name]
        return cls(name, top, bottom, [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)])

    def copy(self) -> Board:
        # Towers are immutable, so copying the rows is enough.
        return Board(self.name, self.top, self.bottom, [row[:] for row in self.grid], self._frozen)

    def __getitem__(self, square: Square) -> Tower | None:
        r, c = square
        return self.grid[r][c]

    def __setitem__(self, square: Square, tower: Tower | None) -> None:
        r, c = square
        self.grid[r][c] = tower
        self._frozen = None

    def starting_row(self, player: int) -> int:
        if player == self.top:
            return TOP_ROW
        if player == self.bottom:
            return BOTTOM_ROW
        raise ValueError(f"Player {player} does not play on board {self.name}")

    def forward(self, player: int) -> int:
        """Row direction a player's towers move in: +1 (down) or -1 (up)."""
        return 1 if player == self.top else -1

    def opponent(self, player: int) -> int:
        return self.bottom if player == self.top else self.top

    def towers(self) -> list[tuple[Square, Tower]]:
        return [((r, c), t) for r, row in enumerate(self.grid) for c, t in enumerate(row) if t is not None]


def boards_of(player: int) -> list[str]:
    """The two boards a player plays on."""
    return [name for name, pair in BOARD_PLAYERS.items() if player in pair]


# ---------- Game state ----------

@dataclass
class GameState:
    boards: dict[str, Board]
    phase: str                              # "setup" or "play"
    to_move: int
    hands: dict[int, tuple[Tower, ...]]     # towers not yet placed
    captured: dict[int, tuple[Tower, ...]]  # towers each player has captured
    action_count: int = 0                   # actions taken in the play phase
    passes_in_row: int = 0

    def copy(self) -> GameState:
        """Shallow copy: boards are shared with the original. Use `edit_board`
        before changing one, so the original state is never modified."""
        return GameState(
            boards=dict(self.boards),
            phase=self.phase,
            to_move=self.to_move,
            hands=dict(self.hands),
            captured=dict(self.captured),
            action_count=self.action_count,
            passes_in_row=self.passes_in_row,
        )

    def edit_board(self, name: str) -> Board:
        """Give this state its own copy of a board and return it, ready to change."""
        board = self.boards[name] = self.boards[name].copy()
        return board


def new_game() -> GameState:
    """Empty boards, every player holding 9 towers, P1 to place first."""
    return GameState(
        boards={name: Board.empty(name) for name in BOARD_PLAYERS},
        phase="setup",
        to_move=1,
        hands={p: full_set(p) for p in PLAYERS},
        captured={p: () for p in PLAYERS},
    )


def next_player(player: int) -> int:
    return player % len(PLAYERS) + 1


def starting_squares(state: GameState, player: int) -> list[tuple[str, Square]]:
    """All 10 squares on a player's two starting lines, empty or not."""
    out = []
    for name in boards_of(player):
        row = state.boards[name].starting_row(player)
        out.extend((name, (row, c)) for c in range(BOARD_SIZE))
    return out


def legal_placements(state: GameState, player: int) -> list[Place]:
    if state.phase != "setup" or player != state.to_move:
        return []
    empty = [(name, sq) for name, sq in starting_squares(state, player) if state.boards[name][sq] is None]
    return [Place(tower, name, sq) for tower in state.hands[player] for name, sq in empty]


def can_capture(attacker: Tower, defender: Tower) -> bool:
    """Official capture rules (size first, then sides, plus David & Goliath)."""
    if attacker.owner == defender.owner:
        return False
    if attacker.size - defender.size == 1:
        return True
    if attacker.size == defender.size:
        return attacker.shape > defender.shape
    return (attacker.size, attacker.shape) == (Size.S, Shape.T) and (defender.size, defender.shape) == (Size.L, Shape.H)


def _in_bounds(r: int, c: int) -> bool:
    return 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE


def tower_actions(board: Board, square: Square) -> list[Move | Capture]:
    """Moves and captures for the tower on `square` (whoever owns it)."""
    tower = board[square]
    if tower is None:
        return []
    r, c = square
    f = board.forward(tower.owner)
    actions: list[Move | Capture] = []
    # Forward and diagonally forward: move to an empty square, or capture.
    for dc in (-1, 0, 1):
        to = (r + f, c + dc)
        if not _in_bounds(*to):
            continue
        target = board[to]
        if target is None:
            actions.append(Move(board.name, square, to))
        elif can_capture(tower, target):
            actions.append(Capture(board.name, square, to))
    # Sideways: capture only, never a plain move.
    for dc in (-1, 1):
        to = (r, c + dc)
        if _in_bounds(*to) and board[to] is not None and can_capture(tower, board[to]):
            actions.append(Capture(board.name, square, to))
    return actions


def is_frozen(board: Board) -> bool:
    """True when no capture can ever happen on this board again.

    Towers only move forward, so a top tower and a bottom tower can still meet
    only if they haven't passed each other and their column gap can close in
    time. Blocking by other towers is ignored: if a capture is still
    theoretically possible, the board stays live (as the official rules say).
    The answer is cached on the board until one of its squares changes.
    """
    if board._frozen is None:
        board._frozen = _compute_frozen(board)
    return board._frozen


def _compute_frozen(board: Board) -> bool:
    tops = [(sq, t) for sq, t in board.towers() if t.owner == board.top]
    bottoms = [(sq, t) for sq, t in board.towers() if t.owner == board.bottom]
    for (rt, ct), t in tops:
        for (ru, cu), u in bottoms:
            if not (can_capture(t, u) or can_capture(u, t)):
                continue
            if rt <= ru and abs(ct - cu) <= (ru - rt) + 1:
                return False
    return True


def frozen_boards(state: GameState) -> list[str]:
    return [name for name, b in state.boards.items() if is_frozen(b)]


def is_terminal(state: GameState) -> bool:
    if state.phase != "play":
        return False
    return (
        len(frozen_boards(state)) >= 2
        or state.passes_in_row >= len(PLAYERS)
        or state.action_count >= MAX_ACTIONS
    )


def end_reason(state: GameState) -> str | None:
    """Why the game ended, or None while it is still going."""
    if not is_terminal(state):
        return None
    if len(frozen_boards(state)) >= 2:
        return "two boards frozen"
    if state.passes_in_row >= len(PLAYERS):
        return "everyone passed"
    return "action limit reached"


def score_parts(state: GameState) -> dict[int, tuple[int, int]]:
    """Per player: (points from captures, points from towers on enemy starting lines)."""
    line_towers = {p: 0 for p in PLAYERS}
    for board in state.boards.values():
        for (r, _), tower in board.towers():
            enemy_line = BOTTOM_ROW if tower.owner == board.top else TOP_ROW
            if r == enemy_line:
                line_towers[tower.owner] += 1
    return {
        p: (CAPTURE_POINTS * len(state.captured[p]), STARTING_LINE_POINTS * line_towers[p])
        for p in PLAYERS
    }


def scores(state: GameState) -> dict[int, int]:
    return {p: sum(parts) for p, parts in score_parts(state).items()}


def winners(state: GameState) -> list[int]:
    """Highest score wins. Tie: whoever captured the higher-ranked towers (compared
    strongest first). Still tied: everyone tied wins."""
    pts = scores(state)

    def key(p: int):
        return (pts[p], sorted((t.rank for t in state.captured[p]), reverse=True))

    best = max(key(p) for p in PLAYERS)
    return [p for p in PLAYERS if key(p) == best]


def legal_actions(state: GameState, player: int) -> list[Action]:
    """Everything `player` may do now. Captures come first (useful for move ordering)."""
    if player != state.to_move or is_terminal(state):
        return []
    if state.phase == "setup":
        return list(legal_placements(state, player))
    actions: list[Move | Capture] = []
    for name in boards_of(player):
        board = state.boards[name]
        if is_frozen(board):
            continue
        for square, tower in board.towers():
            if tower.owner == player:
                actions.extend(tower_actions(board, square))
    if not actions:
        return [Pass()]
    actions.sort(key=lambda a: not isinstance(a, Capture))
    return actions


def apply(state: GameState, action: Action) -> GameState:
    """Return the state after `action`. Raises IllegalAction if it isn't allowed."""
    if isinstance(action, Place):
        return _apply_place(state, action)
    if state.phase != "play":
        raise IllegalAction("Moves, captures and passes happen after setup")
    if is_terminal(state):
        raise IllegalAction("The game is over")
    if isinstance(action, Pass):
        return _apply_pass(state)
    if isinstance(action, (Move, Capture)):
        return _apply_move_or_capture(state, action)
    raise IllegalAction(f"Unknown action {action!r}")


def _apply_move_or_capture(state: GameState, action: Move | Capture) -> GameState:
    player = state.to_move
    if action.board not in boards_of(player):
        raise IllegalAction(f"P{player} does not play on board {action.board}")
    board = state.boards[action.board]
    if is_frozen(board):
        raise IllegalAction(f"Board {action.board} is frozen")
    tower = board[action.frm]
    if tower is None or tower.owner != player:
        raise IllegalAction(f"P{player} has no tower on {action.board}{action.frm}")
    if action not in tower_actions(board, action.frm):
        raise IllegalAction(f"{tower.code} cannot {type(action).__name__.lower()} to {action.board}{action.to}")

    new = state.copy()
    nb = new.edit_board(action.board)
    if isinstance(action, Capture):
        new.captured[player] = new.captured[player] + (nb[action.to],)
    nb[action.to] = tower
    nb[action.frm] = None
    new.action_count += 1
    new.passes_in_row = 0
    new.to_move = next_player(player)
    return new


def _apply_pass(state: GameState) -> GameState:
    if legal_actions(state, state.to_move) != [Pass()]:
        raise IllegalAction("You may only pass when you have no other legal action")
    new = state.copy()
    new.action_count += 1
    new.passes_in_row += 1
    new.to_move = next_player(state.to_move)
    return new


def _apply_place(state: GameState, action: Place) -> GameState:
    player = state.to_move
    if state.phase != "setup":
        raise IllegalAction("Towers can only be placed during setup")
    if action.tower.owner != player:
        raise IllegalAction(f"It is P{player}'s turn, not P{action.tower.owner}'s")
    if action.tower not in state.hands[player]:
        raise IllegalAction(f"{action.tower.code} is not in P{player}'s hand")
    if (action.board, action.square) not in starting_squares(state, player):
        raise IllegalAction(f"{action.board}{action.square} is not on P{player}'s starting lines")
    if state.boards[action.board][action.square] is not None:
        raise IllegalAction(f"{action.board}{action.square} is already occupied")

    new = state.copy()
    new.edit_board(action.board)[action.square] = action.tower
    hand = list(new.hands[player])
    hand.remove(action.tower)
    new.hands[player] = tuple(hand)

    if all(not h for h in new.hands.values()):
        new.phase, new.to_move = "play", 1
    else:
        new.to_move = next_player(player)
    return new
