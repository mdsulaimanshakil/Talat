import random

import pytest

from talat.ai import RandomAgent, make_agent
from talat.cli import format_action, main, parse_action, play_game, render, simulate
from talat.engine import PLAYERS, Capture, Move, Pass, apply, is_terminal, legal_actions, new_game
from tests.helpers import make_state


def mid_game_state(seed: int = 4, steps: int = 40):
    rng = random.Random(seed)
    state = new_game()
    for _ in range(27 + steps):
        state = apply(state, rng.choice(legal_actions(state, state.to_move)))
    return state


# ---------- agents ----------

def test_random_agent_only_picks_legal_actions():
    state, agent = mid_game_state(), RandomAgent(seed=1)
    for _ in range(20):
        assert agent.choose_action(state, state.to_move) in legal_actions(state, state.to_move)


def test_same_seed_same_game():
    def game(seed):
        return play_game({p: RandomAgent(seed=seed + p) for p in PLAYERS}, show=False)
    assert game(5).boards == game(5).boards
    assert game(5).boards != game(6).boards


def test_make_agent():
    assert isinstance(make_agent("random", seed=1), RandomAgent)
    with pytest.raises(ValueError):
        make_agent("nobody")


# ---------- notation ----------

def test_notation_round_trip_in_setup_and_play():
    for state in (new_game(), mid_game_state()):
        for action in legal_actions(state, state.to_move):
            assert parse_action(format_action(action), state) == action


def test_parse_examples():
    state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MQ"}})
    assert parse_action("A:c2-c3", state) == Move("A", (1, 2), (2, 2))
    assert parse_action("a: c2 x d3", state) == Capture("A", (1, 2), (2, 3))
    assert parse_action("A:c2-d3", state) == Capture("A", (1, 2), (2, 3))  # symbol doesn't matter
    assert parse_action("PASS", state) == Pass()
    for bad in ["", "A:z9-a1", "D:a1-a2", "hello"]:
        with pytest.raises(ValueError):
            parse_action(bad, state)


# ---------- playing ----------

def test_render_shows_boards_scores_and_frozen():
    text = render(make_state({"A": {(3, 2): "1LH", (2, 2): "2MQ"}}))
    for part in ["Board A  [frozen]", "Board B", "Board C", "Scores:", "1LH", "P1 line"]:
        assert part in text


def test_human_game_with_typed_commands():
    """A human P1 who types junk, asks for help, then plays randomly, still finishes."""
    script = iter(["hello", "?", "A:a1-a2"] + ["r"] * 1000)
    lines = []
    state = play_game({1: None, 2: RandomAgent(seed=2), 3: RandomAgent(seed=3)},
                      inp=lambda prompt: next(script), out=lines.append)
    assert is_terminal(state)
    assert any("Couldn't read" in line for line in lines)
    assert any("Game over" in line for line in lines)


def test_quit():
    with pytest.raises(SystemExit):
        play_game({1: None, 2: RandomAgent(), 3: RandomAgent()}, inp=lambda p: "q", out=lambda s: None)


def test_simulate_summary():
    text = simulate(20)
    assert "20 games finished" in text
    assert "two boards frozen" in text


def test_main_with_three_random_seats(capsys):
    main(["--seats", "random,random,random", "--seed", "3"])
    assert "Game over" in capsys.readouterr().out
