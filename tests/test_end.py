import random

import pytest

from talat.engine import (
    MAX_ACTIONS, PLAYERS, IllegalAction, Move, apply, frozen_boards, is_frozen, is_terminal,
    legal_actions, legal_placements, new_game, score_parts, scores, winners,
)
from tests.helpers import make_state, t

# Board B is Black (P2, top) vs Grey (P3, bottom), like the diagrams in the official rules.

# ---------- the three examples from page 5 of the official rules ----------

PDF_EXAMPLE_1 = {  # frozen: towers 1 and 2 are too far apart
    (0, 4): "3SQ", (1, 1): "3LT", (1, 3): "3SH",
    (2, 1): "2SQ",            # tower 2
    (3, 4): "3MH",            # tower 1
    (4, 1): "2MT",
}
PDF_EXAMPLE_2 = {  # frozen: tower 2 too far from tower 3; towers 3 and 4 can't take tower 1
    (0, 0): "2LT", (0, 1): "2LQ", (0, 3): "2SQ",   # towers 3, 4, 5
    (0, 4): "3LT",
    (1, 0): "3ST",            # tower 1
    (2, 4): "3LQ",            # tower 2
    (4, 1): "2MH",
}
PDF_EXAMPLE_3 = {  # live: tower 2 could still take tower 1 (David & Goliath)
    (0, 2): "3SQ", (2, 0): "3LH",
    (2, 2): "2LH",            # tower 1
    (3, 3): "2LT",            # tower 3
    (3, 4): "2LQ",
    (4, 4): "3ST",            # tower 2
}


def board_b(squares):
    return make_state({"B": squares}).boards["B"]


def test_pdf_example_1_is_frozen():
    assert is_frozen(board_b(PDF_EXAMPLE_1))


def test_pdf_example_2_is_frozen():
    assert is_frozen(board_b(PDF_EXAMPLE_2))


def test_pdf_example_3_is_live_until_tower_1_scores():
    assert not is_frozen(board_b(PDF_EXAMPLE_3))
    # Tower 1 steps forward to the X: still live.
    squares = dict(PDF_EXAMPLE_3)
    squares[(3, 2)] = squares.pop((2, 2))
    assert not is_frozen(board_b(squares))
    # Then straight into grey's starting line: now frozen.
    squares[(4, 2)] = squares.pop((3, 2))
    assert is_frozen(board_b(squares))


# ---------- frozen-board rule ----------

def test_towers_that_passed_each_other_are_frozen():
    assert is_frozen(board_b({(3, 2): "2LH", (2, 2): "3MQ"}))


def test_pair_that_can_still_meet_is_live():
    assert not is_frozen(board_b({(0, 0): "2LH", (4, 4): "3MQ"}))   # gap 4, columns 4 apart


def test_column_gap_too_wide_is_frozen():
    assert is_frozen(board_b({(1, 0): "2LH", (2, 4): "3MQ"}))       # gap 1, columns 4 apart


def test_side_by_side_is_live_but_two_apart_is_frozen():
    assert not is_frozen(board_b({(2, 1): "2LH", (2, 2): "3MQ"}))
    assert is_frozen(board_b({(2, 1): "2LH", (2, 3): "3MQ"}))


def test_no_possible_capture_pair_is_frozen():
    assert is_frozen(board_b({(0, 0): "2LH", (4, 0): "3SH", (4, 1): "3LH"}))  # L vs S, identical L-H


def test_no_board_is_frozen_right_after_setup():
    rng = random.Random(3)
    state = new_game()
    while state.phase == "setup":
        state = apply(state, rng.choice(legal_placements(state, state.to_move)))
    assert frozen_boards(state) == []
    assert not is_terminal(state)


# ---------- end of game ----------

def test_one_frozen_board_blocks_play_there_but_game_goes_on():
    state = make_state({"A": {(3, 2): "1LH", (2, 2): "2MQ"}})   # passed each other: frozen
    assert frozen_boards(state) == ["A"]
    assert not is_terminal(state)
    assert all(a.board == "C" for a in legal_actions(state, 1))
    with pytest.raises(IllegalAction):
        apply(state, Move("A", (3, 2), (4, 2)))


def test_two_frozen_boards_end_the_game():
    state = make_state({"A": {(3, 2): "1LH", (2, 2): "2MQ"}, "B": PDF_EXAMPLE_1})
    assert is_terminal(state)
    assert legal_actions(state, 1) == []
    with pytest.raises(IllegalAction):
        apply(state, Move("C", (4, 4), (3, 4)))


def test_three_passes_in_a_row_end_the_game():
    state = make_state({})
    state.passes_in_row = 3
    assert is_terminal(state)


def test_action_limit_ends_the_game():
    state = make_state({})
    state.action_count = MAX_ACTIONS
    assert is_terminal(state)


@pytest.mark.parametrize("seed", range(20))
def test_random_games_always_end(seed):
    rng = random.Random(seed)
    state = new_game()
    while not is_terminal(state):
        state = apply(state, rng.choice(legal_actions(state, state.to_move)))
    assert state.action_count <= MAX_ACTIONS
    assert winners(state)


# ---------- scoring ----------

def test_scoring_captures_and_starting_lines():
    state = make_state({
        "A": {(4, 0): "1MH",   # P1 on P2's line: +3
              (4, 1): "2MH"},  # P2 on its own line: nothing
        "C": {(0, 3): "1ST",   # P1 on P3's line: +3
              (4, 4): "3LH"},  # P3 on P1's line: +3
    }, live_others=False)
    state.captured[1] = (t("2LQ"), t("3SQ"))
    state.captured[2] = (t("1MT"),)
    assert score_parts(state) == {1: (10, 6), 2: (5, 0), 3: (0, 3)}
    assert scores(state) == {1: 16, 2: 5, 3: 3}
    assert winners(state) == [1]


def test_tie_goes_to_the_higher_ranked_capture():
    state = make_state({}, live_others=False)
    state.captured[1] = (t("2MH"),)
    state.captured[2] = (t("3LT"),)    # large beats medium
    state.captured[3] = (t("1LQ"),)    # same size, more sides than P2's triangle
    assert scores(state) == {1: 5, 2: 5, 3: 5}
    assert winners(state) == [3]


def test_full_tie_is_a_shared_win():
    state = make_state({}, live_others=False)
    state.captured[1] = (t("2LH"),)
    state.captured[2] = (t("3LH"),)
    assert winners(state) == [1, 2]


def test_nobody_scores_at_the_start():
    assert scores(new_game()) == {p: 0 for p in PLAYERS}


# ---------- engine speed-ups: cached frozen status, shared boards ----------

def test_frozen_cache_is_cleared_when_a_square_changes():
    board = make_state({"B": {(3, 2): "2LH", (2, 2): "3MQ"}}).boards["B"]
    assert is_frozen(board)                 # passed each other
    board[(0, 0)] = t("2MH")                # a new black tower that can still reach grey's M-Q
    assert not is_frozen(board)


def test_apply_copies_only_the_board_it_changes():
    state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MT"}})
    after = apply(state, Move("A", (1, 2), (2, 2)))
    assert after.boards["B"] is state.boards["B"]      # untouched boards are shared
    assert after.boards["A"] is not state.boards["A"]
    assert state.boards["A"][(1, 2)] == t("1LH")      # the original is unchanged
