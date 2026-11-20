import random
import time

import pytest

from talat.ai import MaxnAgent, ParanoidAgent, make_agent
from talat.ai.maxn import ROW_ADVANCED, THREATENED, WIN_BONUS, evaluate
from talat.engine import PLAYERS, Capture, Place, apply, is_terminal, legal_actions, new_game, scores, winners
from tests.helpers import make_state


def mid_game(seed: int, steps: int = 30):
    rng = random.Random(seed)
    state = new_game()
    for _ in range(27 + steps):
        state = apply(state, rng.choice(legal_actions(state, state.to_move)))
    return state


# ---------- evaluation ----------

def test_evaluate_counts_score_rows_and_threats():
    # Board A: P1 L-H two rows down (row 2), P2 M-Q one row up (row 3), and the hexagon threatens it.
    # Boards B and C get the default far-apart pairs (still on their starting lines, so they add 0).
    state = make_state({"A": {(2, 2): "1LH", (3, 2): "2MQ"}})
    state.captured[1] = (make_state({}).boards["B"][(0, 4)],)   # one captured tower: 5 points
    u = evaluate(state)
    assert u[0] == 5 + 2 * ROW_ADVANCED
    assert u[1] == 1 * ROW_ADVANCED + THREATENED
    assert u[2] == 0


def test_evaluate_finished_game_uses_scores_and_win_bonus():
    state = make_state({}, live_others=False)   # no towers: every board frozen
    state.captured[2] = (make_state({}).boards["B"][(0, 4)],)
    assert is_terminal(state)
    pts = scores(state)
    assert evaluate(state) == tuple(pts[p] + (WIN_BONUS if p in winners(state) else 0) for p in PLAYERS)


# ---------- search ----------

@pytest.mark.parametrize("cls", [MaxnAgent, ParanoidAgent])
def test_takes_a_free_capture(cls):
    state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MT", (4, 0): "2SQ"}})
    assert cls(seed=0).choose_action(state, 1) == Capture("A", (1, 2), (2, 3))


@pytest.mark.parametrize("cls", [MaxnAgent, ParanoidAgent])
def test_always_legal(cls):
    agent = cls(seed=1, max_depth=2)
    for seed in range(5):
        state = mid_game(seed)
        assert agent.choose_action(state, state.to_move) in legal_actions(state, state.to_move)


def plain_paranoid(state, depth, root):
    """Paranoid minimax without pruning, to check that alpha-beta returns the same value."""
    if depth == 0 or is_terminal(state):
        return ParanoidAgent._advantage(evaluate(state), root)
    values = [plain_paranoid(apply(state, a), depth - 1, root) for a in legal_actions(state, state.to_move)]
    return max(values) if state.to_move == root else min(values)


@pytest.mark.parametrize("seed", range(4))
def test_alpha_beta_matches_plain_minimax(seed):
    state = mid_game(seed, steps=20)
    root = state.to_move
    agent = ParanoidAgent(seed=0)
    for depth in (1, 2, 3):
        assert agent._paranoid(state, depth, root, float("-inf"), float("inf")) == pytest.approx(
            plain_paranoid(state, depth, root))


def test_alpha_beta_searches_fewer_nodes_than_maxn():
    state = mid_game(4, steps=12)
    maxn, paranoid = MaxnAgent(seed=0), ParanoidAgent(seed=0)
    maxn.choose_action(state, state.to_move)
    paranoid.choose_action(state, state.to_move)
    assert paranoid.last_stats["nodes"] < maxn.last_stats["nodes"] / 2


@pytest.mark.parametrize("cls", [MaxnAgent, ParanoidAgent])
def test_respects_the_time_limit(cls):
    state = mid_game(4, steps=12)
    agent = cls(seed=0, max_depth=6)
    start = time.perf_counter()
    action = agent.choose_action(state, state.to_move, time_limit=0.2)
    assert time.perf_counter() - start < 0.4
    assert action in legal_actions(state, state.to_move)
    assert 1 <= agent.last_stats["depth"] < 6


def test_setup_uses_greedy_placement():
    action = MaxnAgent(seed=0).choose_action(new_game(), 1)
    assert isinstance(action, Place) and action.tower.code == "1LH"


def test_registered_by_name():
    assert make_agent("maxn").mode == "maxn"
    assert make_agent("paranoid").mode == "paranoid"
    with pytest.raises(ValueError):
        MaxnAgent(mode="other")
