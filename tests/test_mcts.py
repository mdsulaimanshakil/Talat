import random
import time

import pytest

from talat.ai import MctsAgent, make_agent
from talat.ai.mcts import Node, result_vector
from talat.engine import Capture, Place, apply, is_terminal, legal_actions, new_game
from tests.helpers import make_state, t


def mid_game(seed: int, steps: int = 20):
    rng = random.Random(seed)
    state = new_game()
    for _ in range(27 + steps):
        state = apply(state, rng.choice(legal_actions(state, state.to_move)))
    return state


def test_result_vector_rewards_the_winner_and_splits_ties():
    state = make_state({})
    state.captured[2] = (t("1MQ"),)
    assert result_vector(state) == [0.0, 1.0, 0.0]
    state.captured[3] = (t("1MQ"),)
    assert result_vector(state) == [0.0, 0.5, 0.5]


def test_tree_statistics_add_up():
    state = mid_game(1)
    agent = MctsAgent(seed=0)
    root = Node(state)
    for _ in range(300):
        agent._iterate(root)
    assert root.visits == 300
    assert sum(child.visits for child in root.children) == 300
    assert len(root.children) == len(legal_actions(state, state.to_move))   # every root action tried
    for child in root.children:
        assert child.mover == state.to_move
        assert 0 <= child.reward <= child.visits     # rewards are per visit, at most 1 each


def test_takes_a_winning_capture():
    # Capturing P2's large square with the large hexagon is worth 5 and safe; nothing else scores.
    state = make_state({"A": {(1, 2): "1LH", (2, 3): "2LQ", (4, 0): "2SQ"}})
    agent = MctsAgent(seed=0, iterations=600)
    assert agent.choose_action(state, 1) == Capture("A", (1, 2), (2, 3))


def test_iteration_budget_and_stats():
    state = mid_game(2)
    agent = MctsAgent(seed=0, iterations=250)
    action = agent.choose_action(state, state.to_move)
    assert action in legal_actions(state, state.to_move)
    assert agent.last_stats["rollouts"] == 250


def test_same_seed_same_choice():
    state = mid_game(3)
    a = MctsAgent(seed=7, iterations=200).choose_action(state, state.to_move)
    b = MctsAgent(seed=7, iterations=200).choose_action(state, state.to_move)
    assert a == b


def test_respects_the_time_limit():
    state = mid_game(4)
    agent = MctsAgent(seed=0)
    start = time.perf_counter()
    agent.choose_action(state, state.to_move, time_limit=0.2)
    assert time.perf_counter() - start < 0.3
    assert agent.last_stats["rollouts"] > 0


def test_only_one_option_needs_no_search():
    state = make_state({"A": {(1, 0): "1SQ", (2, 0): "2LH", (2, 1): "2LQ", (4, 4): "2MT"},
                        "C": {(0, 4): "3MH", (1, 4): "3ST"}})
    agent = MctsAgent(seed=0)
    action = agent.choose_action(state, 1)
    assert action == legal_actions(state, 1)[0]
    assert agent.last_stats == {"rollouts": 0}


def test_rollouts_finish_or_stop_at_the_cap():
    agent = MctsAgent(seed=0, rollout_cap=5)
    reward = agent._rollout(mid_game(5))
    assert sum(reward) == pytest.approx(1.0)


def test_setup_uses_greedy_placement_and_registered():
    action = MctsAgent(seed=0).choose_action(new_game(), 1)
    assert isinstance(action, Place) and action.tower.code == "1LH"
    assert isinstance(make_agent("mcts"), MctsAgent)
