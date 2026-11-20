import pytest

from talat.engine import Capture, IllegalAction, Move, Pass, apply, can_capture, legal_actions, tower_actions
from tests.helpers import make_state, t


# ---------- can_capture ----------

@pytest.mark.parametrize("a, b, expected", [
    ("1LH", "2MQ", True),    # one size smaller, any shape
    ("1LT", "2MH", True),
    ("1MQ", "2ST", True),
    ("1LH", "2SH", False),   # two sizes smaller: not allowed
    ("1LQ", "2ST", False),
    ("1SH", "2MT", False),   # smaller never takes larger...
    ("1MH", "2LT", False),
    ("1LH", "2LQ", True),    # same size: more sides wins
    ("1LH", "2LT", True),
    ("1MQ", "2MT", True),
    ("1ST", "2SQ", False),
    ("1SQ", "2SH", False),
    ("1LQ", "2LQ", False),   # identical towers
    ("1ST", "2LH", True),    # ...except David & Goliath
    ("1ST", "2MH", False),
    ("1SQ", "2LH", False),
    ("1MT", "2LH", False),
    ("1ST", "2LQ", False),
    ("1LH", "1MQ", False),   # never your own tower
])
def test_can_capture(a, b, expected):
    assert can_capture(t(a), t(b)) is expected


# ---------- moves ----------

def targets(actions, kind):
    return {a.to for a in actions if isinstance(a, kind)}


def test_top_player_moves_down_straight_or_diagonal():
    state = make_state({"A": {(1, 2): "1MQ"}})
    acts = tower_actions(state.boards["A"], (1, 2))
    assert targets(acts, Move) == {(2, 1), (2, 2), (2, 3)}
    assert targets(acts, Capture) == set()


def test_bottom_player_moves_up():
    state = make_state({"A": {(3, 2): "2MQ"}}, to_move=2)
    assert targets(tower_actions(state.boards["A"], (3, 2)), Move) == {(2, 1), (2, 2), (2, 3)}


def test_edge_column_has_two_moves():
    state = make_state({"A": {(1, 0): "1MQ"}})
    assert targets(tower_actions(state.boards["A"], (1, 0)), Move) == {(2, 0), (2, 1)}


def test_no_sideways_or_backward_moves():
    state = make_state({"A": {(2, 2): "1MQ"}})
    moves = targets(tower_actions(state.boards["A"], (2, 2)), Move)
    for square in [(2, 1), (2, 3), (1, 1), (1, 2), (1, 3)]:
        assert square not in moves


def test_no_jumping_or_moving_onto_towers():
    # Own tower ahead blocks; a stronger enemy ahead blocks; a weaker enemy can be captured.
    state = make_state({"A": {(1, 2): "1MQ", (2, 1): "1SQ", (2, 2): "2LH", (2, 3): "2SQ"}})
    acts = tower_actions(state.boards["A"], (1, 2))
    assert targets(acts, Move) == set()
    assert targets(acts, Capture) == {(2, 3)}


# ---------- captures ----------

def test_capture_straight_and_diagonal():
    state = make_state({"A": {(1, 2): "1LH", (2, 2): "2MT", (2, 1): "2MQ"}})
    assert targets(tower_actions(state.boards["A"], (1, 2)), Capture) == {(2, 1), (2, 2)}


def test_sideways_capture_but_no_sideways_move():
    state = make_state({"A": {(2, 2): "1LH", (2, 3): "2LQ"}})
    acts = tower_actions(state.boards["A"], (2, 2))
    assert targets(acts, Capture) == {(2, 3)}
    assert (2, 1) not in targets(acts, Move)


def test_no_capture_behind():
    state = make_state({"A": {(2, 2): "1LH", (1, 2): "2MQ", (1, 1): "2MQ"}})
    assert targets(tower_actions(state.boards["A"], (2, 2)), Capture) == set()


def test_tower_on_enemy_starting_line_only_captures_sideways():
    # P1 moves down on board A; row 4 is P2's starting line.
    state = make_state({"A": {(4, 2): "1MH", (4, 3): "2MT", (4, 1): "2SQ"}})
    acts = tower_actions(state.boards["A"], (4, 2))
    assert targets(acts, Move) == set()
    assert targets(acts, Capture) == {(4, 1), (4, 3)}


def test_david_and_goliath_on_the_board():
    # P1 is the bottom player on board C and moves up; P3's large hexagon is in front.
    state = make_state({"C": {(1, 2): "3LH", (2, 2): "1ST"}}, to_move=1)
    assert targets(tower_actions(state.boards["C"], (2, 2)), Capture) == {(1, 2)}


# ---------- legal_actions and apply ----------

def test_legal_actions_cover_both_boards_and_list_captures_first():
    state = make_state({"A": {(1, 2): "1MQ", (4, 4): "2ST"}, "C": {(3, 2): "1LH", (2, 2): "3MQ"}})
    acts = legal_actions(state, 1)
    assert {a.board for a in acts} == {"A", "C"}
    assert isinstance(acts[0], Capture)
    assert legal_actions(state, 2) == []  # not P2's turn


def test_apply_capture():
    state = make_state({"A": {(1, 2): "1LH", (2, 2): "2MT"}})
    after = apply(state, Capture("A", (1, 2), (2, 2)))
    assert after.boards["A"][(2, 2)] == t("1LH")
    assert after.boards["A"][(1, 2)] is None
    assert after.captured[1] == (t("2MT"),)
    assert after.to_move == 2
    assert after.action_count == 1
    assert state.boards["A"][(2, 2)] == t("2MT")  # original unchanged


def test_apply_move():
    state = make_state({"A": {(1, 2): "1LH", (4, 0): "2MQ"}})
    after = apply(state, Move("A", (1, 2), (2, 3)))
    assert after.boards["A"][(2, 3)] == t("1LH")
    assert after.boards["A"][(1, 2)] is None
    assert after.to_move == 2


@pytest.mark.parametrize("action", [
    Move("A", (2, 2), (2, 3)),     # sideways
    Move("A", (2, 2), (1, 2)),     # backward
    Move("A", (2, 2), (4, 2)),     # two squares
    Capture("A", (2, 2), (3, 2)),  # nothing to capture
    Move("B", (0, 0), (1, 0)),     # P1 doesn't play on board B
    Move("A", (3, 3), (2, 3)),     # P2's tower, but it's P1's turn
])
def test_illegal_actions_raise(action):
    state = make_state({"A": {(2, 2): "1MQ", (3, 3): "2SQ"}, "B": {(0, 0): "2LH"}})
    with pytest.raises(IllegalAction):
        apply(state, action)


# P1's only tower on board A is boxed in by large towers it can't capture, and
# P1 has no tower on board C. Only board C is frozen, so the game goes on.
BLOCKED = {
    "A": {(1, 0): "1SQ", (2, 0): "2LH", (2, 1): "2LQ", (4, 4): "2MT"},
    "C": {(0, 4): "3MH", (1, 4): "3ST"},
}


def test_pass_only_when_nothing_else_is_possible():
    blocked = make_state(BLOCKED)
    assert legal_actions(blocked, 1) == [Pass()]
    after = apply(blocked, Pass())
    assert after.to_move == 2 and after.passes_in_row == 1

    free = make_state({"A": {(1, 0): "1SQ", (4, 4): "2MT"}})
    assert Pass() not in legal_actions(free, 1)
    with pytest.raises(IllegalAction):
        apply(free, Pass())


def test_a_real_action_resets_the_pass_counter():
    state = apply(make_state(BLOCKED), Pass())
    assert state.passes_in_row == 1
    state = apply(state, Move("B", (0, 4), (1, 4)))  # P2 moves the filler tower on board B
    assert state.passes_in_row == 0
