import pytest

from talat.engine import Capture, Move, PLAYERS, is_terminal
from talat.session import PRESETS, SEAT_CHOICES, Session, seat_name
from tests.helpers import make_state, t


def human_session(state=None, seats=("human", "random", "random")) -> Session:
    s = Session(dict(zip(PLAYERS, seats)), seed=1)
    if state is not None:
        s.state = state
    return s


def test_presets_use_known_seats():
    for title, subtitle, seats in PRESETS.values():
        assert title and subtitle
        assert len(seats) == 3 and all(name in SEAT_CHOICES for name in seats)


def test_seat_names():
    assert seat_name("mcts") == "Hard AI" and seat_name("greedy") == "Easy AI"
    assert seat_name("random") == "Random"


def test_human_setup_places_the_chosen_tower():
    s = human_session()
    assert s.is_human_turn()
    assert s.setup_tower() == t("1LH")                  # strongest by default
    s.choose_tower(t("1ST"))
    targets = s.targets()
    assert len(targets) == 10                            # every empty square on P1's two starting lines
    assert {sq[0] for (_, sq) in targets} <= {0, 4}
    assert s.tap("A", (0, 2)) is True
    assert s.state.boards["A"][(0, 2)] == t("1ST")
    assert s.last == ("A", (0, 2))
    assert not s.is_human_turn()                         # P2's turn now (an AI)


def test_select_then_move():
    s = human_session(make_state({"A": {(1, 2): "1LH", (2, 3): "2MT", (4, 0): "2SQ"}}))
    assert s.targets() == {}
    assert s.tap("A", (1, 2)) is False                   # selects the tower
    assert s.selected == ("A", (1, 2))
    assert s.targets()[("A", (2, 3))] == Capture("A", (1, 2), (2, 3))
    assert s.targets()[("A", (2, 2))] == Move("A", (1, 2), (2, 2))
    assert s.tap("A", (2, 3)) is True                    # captures
    assert s.state.captured[1] == (t("2MT"),)
    assert s.selected is None and s.log == ["P1: A:c2xd3"]


def test_tapping_elsewhere_or_twice_clears_the_selection():
    s = human_session(make_state({"A": {(1, 2): "1LH", (4, 0): "2SQ"}}))
    s.tap("A", (1, 2))
    s.tap("A", (1, 2))
    assert s.selected is None
    s.tap("A", (1, 2))
    s.tap("A", (4, 0))                                    # enemy tower: not selectable
    assert s.selected is None


def test_cannot_tap_on_an_ai_turn():
    s = human_session(make_state({"A": {(3, 2): "2MQ", (0, 0): "1LH"}}, to_move=2))
    assert not s.is_human_turn()
    assert s.tap("A", (3, 2)) is False
    assert s.targets() == {}


def test_pass_when_stuck():
    stuck = make_state({"A": {(1, 0): "1SQ", (2, 0): "2LH", (2, 1): "2LQ", (4, 4): "2MT"},
                        "C": {(0, 4): "3MH", (1, 4): "3ST"}})
    s = human_session(stuck)
    assert s.must_pass()
    s.pass_turn()
    assert s.state.to_move == 2 and s.log == ["P1: pass"]


def test_ai_game_runs_to_the_end():
    s = Session({1: "random", 2: "greedy", 3: "random"}, seed=3)
    assert s.has_ai() and not s.is_human_turn()
    while not s.is_over():
        s.play(s.think())
    assert is_terminal(s.state)
    assert len(s.log) == 27 + s.state.action_count


def test_unknown_seat_is_rejected():
    with pytest.raises(ValueError):
        Session({1: "human", 2: "nobody", 3: "mcts"})


def test_playable_boards():
    s = human_session()
    assert s.playable_boards() == ["A", "C"]          # setup: both of P1's starting lines have room
    # Play: P1's tower on C is boxed in; only board A has a move.
    s.state = make_state({"A": {(1, 2): "1LH", (4, 0): "2MQ"},
                          "C": {(4, 0): "1SQ", (3, 0): "3LH", (3, 1): "3LQ", (0, 4): "3MT"}})
    assert s.playable_boards() == ["A"]
    assert human_session(make_state({"A": {(3, 2): "2MQ", (0, 0): "1LH"}}, to_move=2)).playable_boards() == []
