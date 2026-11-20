import random

import pytest

from talat.engine import (
    BOARD_PLAYERS, PLAYERS, IllegalAction, Place, Shape, Size, Tower,
    apply, legal_placements, new_game, starting_squares,
)


def play_random_setup(seed: int = 0):
    rng = random.Random(seed)
    state = new_game()
    while state.phase == "setup":
        state = apply(state, rng.choice(legal_placements(state, state.to_move)))
    return state


def test_each_player_gets_nine_unique_towers():
    state = new_game()
    for p in PLAYERS:
        hand = state.hands[p]
        assert len(hand) == 9
        assert len(set(hand)) == 9
        assert {(t.size, t.shape) for t in hand} == {(s, sh) for s in Size for sh in Shape}
        assert all(t.owner == p for t in hand)


def test_starting_lines_match_board_layout():
    state = new_game()
    expected = {
        1: {("A", 0), ("C", 4)},
        2: {("A", 4), ("B", 0)},
        3: {("B", 4), ("C", 0)},
    }
    for p in PLAYERS:
        squares = starting_squares(state, p)
        assert len(squares) == 10
        assert {(name, sq[0]) for name, sq in squares} == expected[p]


def test_placements_only_on_own_starting_lines():
    state = new_game()
    own = set(starting_squares(state, 1))
    moves = legal_placements(state, 1)
    assert len(moves) == 9 * 10
    assert all((m.board, m.square) in own for m in moves)


def test_cannot_place_on_someone_elses_line():
    state = new_game()
    tower = state.hands[1][0]
    with pytest.raises(IllegalAction):
        apply(state, Place(tower, "B", (0, 2)))  # P1 doesn't play on board B
    with pytest.raises(IllegalAction):
        apply(state, Place(tower, "A", (4, 2)))  # P2's line on board A
    with pytest.raises(IllegalAction):
        apply(state, Place(tower, "A", (2, 2)))  # middle of the board


def test_cannot_place_out_of_turn_or_twice():
    state = new_game()
    with pytest.raises(IllegalAction):
        apply(state, Place(state.hands[2][0], "B", (0, 0)))  # P2 before P1
    tower = state.hands[1][0]
    state = apply(state, Place(tower, "A", (0, 0)))
    state = apply(state, Place(state.hands[2][0], "B", (0, 0)))
    state = apply(state, Place(state.hands[3][0], "B", (4, 0)))
    with pytest.raises(IllegalAction):
        apply(state, Place(tower, "A", (0, 1)))  # already placed
    with pytest.raises(IllegalAction):
        apply(state, Place(state.hands[1][0], "A", (0, 0)))  # square taken


def test_apply_does_not_change_the_original_state():
    state = new_game()
    move = legal_placements(state, 1)[0]
    after = apply(state, move)
    assert state.boards[move.board][move.square] is None
    assert len(state.hands[1]) == 9
    assert after.boards[move.board][move.square] == move.tower


def test_setup_turn_order():
    rng = random.Random(1)
    state = new_game()
    order = []
    while state.phase == "setup":
        order.append(state.to_move)
        state = apply(state, rng.choice(legal_placements(state, state.to_move)))
    assert order == [1, 2, 3] * 9


@pytest.mark.parametrize("seed", range(5))
def test_after_setup_one_empty_starting_square_each(seed):
    state = play_random_setup(seed)
    assert state.phase == "play"
    assert state.to_move == 1
    assert all(not hand for hand in state.hands.values())
    placed = [t for b in state.boards.values() for _, t in b.towers()]
    assert len(placed) == 27
    for p in PLAYERS:
        empty = [sq for name, sq in starting_squares(state, p) if state.boards[name][sq] is None]
        assert len(empty) == 1
        mine = [t for name in BOARD_PLAYERS for _, t in state.boards[name].towers() if t.owner == p]
        assert len(mine) == 9


def test_no_placements_after_setup():
    state = play_random_setup()
    assert legal_placements(state, 1) == []
    with pytest.raises(IllegalAction):
        apply(state, Place(Tower(1, Size.L, Shape.H), "A", (0, 0)))
