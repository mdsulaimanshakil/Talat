from talat.ai import GreedyAgent, RandomAgent, make_agent
from talat.ai.greedy import heuristic
from talat.cli import play_game
from talat.engine import PLAYERS, Capture, Move, Place, Shape, Size, apply, legal_actions, new_game, winners
from tests.helpers import make_state

# On board A, P1 is the top player and moves down (towards row 4, P2's starting line).


def test_plain_forward_move_scores_1():
    state = make_state({"A": {(1, 2): "1MQ", (4, 0): "2ST"}})
    assert heuristic(state, Move("A", (1, 2), (2, 2)), 1) == 1


def test_forward_capture_scores_capture_plus_forward():
    state = make_state({"A": {(1, 2): "1LH", (2, 2): "2MT"}})
    assert heuristic(state, Capture("A", (1, 2), (2, 2)), 1) == 5 + 1


def test_sideways_capture_does_not_count_as_forward():
    state = make_state({"A": {(2, 2): "1LH", (2, 3): "2LQ"}})
    assert heuristic(state, Capture("A", (2, 2), (2, 3)), 1) == 5


def test_reaching_the_enemy_starting_line():
    state = make_state({"A": {(3, 0): "1LH", (0, 4): "1MQ", (4, 4): "2ST"}})  # MQ/ST keep the board live
    assert heuristic(state, Move("A", (3, 0), (4, 0)), 1) == 3 + 1


def test_moving_into_danger_is_penalised():
    # P2's medium hexagon (moving up) could capture a small square on c3 next turn.
    state = make_state({"A": {(1, 2): "1SQ", (3, 2): "2MH"}})
    assert heuristic(state, Move("A", (1, 2), (2, 2)), 1) == 1 - 5
    assert heuristic(state, Move("A", (1, 2), (2, 1)), 1) == 1 - 5   # diagonal in front of it too
    assert heuristic(state, Move("A", (1, 2), (2, 3)), 1) == 1 - 5


def test_greedy_takes_the_capture():
    state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MT", (4, 0): "2SQ"}})
    assert GreedyAgent(seed=0).choose_action(state, 1) == Capture("A", (1, 2), (2, 3))


def test_greedy_avoids_danger_when_it_can():
    state = make_state({"A": {(1, 0): "1SQ", (3, 0): "2MH"}, "C": {(0, 0): "3MH", (4, 4): "1LQ"}})
    for seed in range(10):
        action = GreedyAgent(seed=seed).choose_action(state, 1)
        assert heuristic(state, action, 1) == 1      # a safe forward move, never -4
        assert action in legal_actions(state, 1)


def test_setup_places_strongest_first_in_the_middle():
    action = GreedyAgent(seed=0).choose_action(new_game(), 1)
    assert isinstance(action, Place)
    assert (action.tower.size, action.tower.shape) == (Size.L, Shape.H)
    assert action.square[1] == 2


def test_setup_spreads_towers_over_both_boards():
    state = new_game()
    agents = {p: GreedyAgent(seed=p) for p in PLAYERS}
    while state.phase == "setup":
        state = apply(state, agents[state.to_move].choose_action(state, state.to_move))
    for p in PLAYERS:
        counts = sorted(sum(t.owner == p for _, t in b.towers()) for b in state.boards.values()
                        if p in (b.top, b.bottom))
        assert counts == [4, 5]


def test_registered_by_name():
    assert isinstance(make_agent("greedy", seed=1), GreedyAgent)


def test_greedy_beats_random():
    """Greedy rotates through all seats against two random agents."""
    games, wins = 30, 0
    for g in range(games):
        seat = g % 3 + 1
        agents = {p: GreedyAgent(seed=g) if p == seat else RandomAgent(seed=100 + 3 * g + p) for p in PLAYERS}
        wins += seat in winners(play_game(agents, show=False))
    assert wins / games > 0.8
