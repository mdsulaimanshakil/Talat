"""Text-mode TALAT, for playing and quick checks.

    python -m talat.cli                                  # you are P1, random agents play P2 and P3
    python -m talat.cli --seats human,human,random
    python -m talat.cli --seats random,random,random --seed 7
    python -m talat.cli --simulate 1000                  # many random games, summary only

Squares are a column letter and a row number, e.g. c1 (rows 1-5, top to bottom).
Actions:  1LH A:c1   place tower 1LH on board A, square c1 (setup)
          A:c2-c3    move or capture on board A from c2 to c3
          pass       only when you have nothing else to do
"""
from __future__ import annotations

import argparse
import collections
import re
import statistics
from typing import Callable

from talat.ai import AGENTS, Agent, RandomAgent, make_agent
from talat.engine import (
    BOARD_SIZE, PLAYER_NAMES, PLAYERS, Action, Board, Capture, GameState, Move, Pass, Place, Shape, Size,
    Square, Tower, apply, end_reason, is_frozen, is_terminal, legal_actions, new_game, score_parts, scores,
    winners,
)

COLS = "abcde"
HELP = """Commands:
  1LH A:c1   place a tower (setup)       A:c2-c3   move or capture on board A
  pass       when nothing else is possible
  ?          list your legal actions       r   play a random legal action       q   quit"""


# ---------- notation ----------

def square_name(square: Square) -> str:
    r, c = square
    return f"{COLS[c]}{r + 1}"


def parse_square(text: str) -> Square:
    return int(text[1]) - 1, COLS.index(text[0])


def format_action(action: Action) -> str:
    if isinstance(action, Place):
        return f"{action.tower.code} {action.board}:{square_name(action.square)}"
    if isinstance(action, Move):
        return f"{action.board}:{square_name(action.frm)}-{square_name(action.to)}"
    if isinstance(action, Capture):
        return f"{action.board}:{square_name(action.frm)}x{square_name(action.to)}"
    return "pass"


def parse_action(text: str, state: GameState) -> Action:
    """Read an action in the notation above. Raises ValueError if it can't."""
    text = text.strip().lower()
    if text == "pass":
        return Pass()
    m = re.fullmatch(r"([1-3])([lms])([hqt])\s+([abc])\s*:\s*([a-e][1-5])", text)
    if m:
        tower = Tower(int(m[1]), Size[m[2].upper()], Shape[m[3].upper()])
        return Place(tower, m[4].upper(), parse_square(m[5]))
    m = re.fullmatch(r"([abc])\s*:\s*([a-e][1-5])\s*[-x]\s*([a-e][1-5])", text)
    if m:
        board, frm, to = m[1].upper(), parse_square(m[2]), parse_square(m[3])
        # Whether it's a capture depends on the board, not on which symbol was typed.
        kind = Capture if state.boards[board][to] is not None else Move
        return kind(board, frm, to)
    raise ValueError(f"Couldn't read {text!r}. Type ? for your legal actions.")


# ---------- drawing ----------

def render_board(board: Board, state: GameState) -> list[str]:
    frozen = state.phase == "play" and is_frozen(board)
    lines = [
        f"Board {board.name}{'  [frozen]' if frozen else ''}",
        f"P{board.top} {PLAYER_NAMES[board.top]} ↓  vs  P{board.bottom} {PLAYER_NAMES[board.bottom]} ↑",
        "     " + "".join(f"{c:^5}" for c in COLS),
    ]
    for r in range(BOARD_SIZE):
        cells = "".join(f"{(t.code if (t := board[(r, c)]) else '·'):^5}" for c in range(BOARD_SIZE))
        owner = board.top if r == 0 else board.bottom if r == BOARD_SIZE - 1 else None
        lines.append(f" {r + 1}   {cells}" + (f"  P{owner} line" if owner else ""))
    return lines


def render(state: GameState) -> str:
    blocks = [render_board(b, state) for b in state.boards.values()]
    width = max(len(line) for block in blocks for line in block)
    rows = ["    ".join(line.ljust(width) for line in parts) for parts in zip(*blocks)]
    if state.phase == "setup":
        rows.append("")
        rows += [f"P{p} hand: {' '.join(t.code for t in state.hands[p]) or '-'}" for p in PLAYERS]
    pts = scores(state)
    rows.append("")
    rows.append("Scores: " + "   ".join(f"P{p} {PLAYER_NAMES[p]} {pts[p]}" for p in PLAYERS))
    if not is_terminal(state):
        rows.append(f"{state.phase.capitalize()} · P{state.to_move} {PLAYER_NAMES[state.to_move]} to play")
    return "\n".join(rows)


def result_text(state: GameState) -> str:
    parts = score_parts(state)
    lines = [f"Game over ({end_reason(state)}) after {state.action_count} actions."]
    for p in PLAYERS:
        cap, line = parts[p]
        lines.append(f"  P{p} {PLAYER_NAMES[p]:<5} {cap + line:>3} points  ({cap} from captures, {line} from starting lines)")
    win = winners(state)
    names = " and ".join(f"P{p} {PLAYER_NAMES[p]}" for p in win)
    lines.append(f"Winner: {names}" if len(win) == 1 else f"Shared win: {names}")
    return "\n".join(lines)


# ---------- playing ----------

def ask_human(state: GameState, player: int, inp: Callable[[str], str], out: Callable[[str], None]) -> Action:
    actions = legal_actions(state, player)
    while True:
        text = inp(f"P{player} {PLAYER_NAMES[player]}> ").strip()
        if text in ("q", "quit"):
            raise SystemExit("Quit.")
        if text in ("?", "help"):
            out(HELP)
            out("Legal: " + ", ".join(format_action(a) for a in actions))
            continue
        if text in ("r", "random"):
            return RandomAgent().rng.choice(actions)
        try:
            action = parse_action(text, state)
        except ValueError as e:
            out(str(e))
            continue
        if action in actions:
            return action
        out(f"{format_action(action)} isn't legal right now. Type ? for your legal actions.")


def play_game(agents: dict[int, Agent | None], show: bool = True,
              inp: Callable[[str], str] = input, out: Callable[[str], None] = print) -> GameState:
    """Play one game. A seat whose agent is None is a human at the keyboard."""
    state = new_game()
    if show and any(a is None for a in agents.values()):
        out(HELP)
    while not is_terminal(state):
        player = state.to_move
        agent = agents[player]
        if agent is None:
            out("\n" + render(state))
            action = ask_human(state, player, inp, out)
        else:
            action = agent.choose_action(state, player)
            if show:
                out(f"P{player} ({agent.name}): {format_action(action)}")
        state = apply(state, action)
    if show:
        out("\n" + render(state))
        out(result_text(state))
    return state


def simulate(n: int, seed: int = 0) -> str:
    """Play n random-vs-random games and summarise how they ended."""
    reasons: collections.Counter[str] = collections.Counter()
    lengths, wins = [], collections.Counter()
    for game in range(n):
        agents = {p: RandomAgent(seed=seed * 1_000_000 + game * 10 + p) for p in PLAYERS}
        state = play_game(agents, show=False)
        reasons[end_reason(state)] += 1
        lengths.append(state.action_count)
        for p in winners(state):
            wins[p] += 1
    return (
        f"{n} games finished.\n"
        f"Endings: {dict(reasons)}\n"
        f"Actions per game: mean {statistics.mean(lengths):.1f}, min {min(lengths)}, max {max(lengths)}\n"
        f"Wins (shared wins count for each): " + ", ".join(f"P{p} {wins[p]}" for p in PLAYERS)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Play TALAT in the terminal.")
    parser.add_argument("--seats", default="human,random,random",
                        help=f"three of: human, {', '.join(AGENTS)} (for P1, P2, P3)")
    parser.add_argument("--seed", type=int, default=None, help="seed for the agents, to replay a game")
    parser.add_argument("--simulate", type=int, metavar="N", help="play N random games and print a summary")
    args = parser.parse_args(argv)

    if args.simulate:
        print(simulate(args.simulate, seed=args.seed or 0))
        return
    seats = [s.strip().lower() for s in args.seats.split(",")]
    if len(seats) != 3:
        parser.error("--seats needs exactly three names, e.g. human,random,random")
    agents = {
        p: None if name == "human" else make_agent(name, None if args.seed is None else args.seed * 10 + p)
        for p, name in zip(PLAYERS, seats)
    }
    play_game(agents)


if __name__ == "__main__":
    main()
