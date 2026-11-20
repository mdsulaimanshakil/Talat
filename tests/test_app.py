"""Smoke tests for the Flet app: build every screen with a stand-in page (no window).
The board layouts themselves are tested in test_scene.py."""
import pytest

ft = pytest.importorskip("flet")

import math  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from talat.app import GOLD, TalatApp, shape_points, tower_view  # noqa: E402
from talat.scene import BOARD_TURN  # noqa: E402
from talat.engine import PLAYERS, Shape  # noqa: E402
from tests.helpers import make_state, t  # noqa: E402


class FakePage:
    """Just enough of ft.Page for the app. AI turns run immediately instead of in a thread."""

    def __init__(self, width=1300, height=900):
        self.width, self.height = width, height
        self.controls, self.dialogs, self.updates = [], [], 0

    def update(self):
        self.updates += 1

    def run_thread(self, handler, *args):
        handler(*args)

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.dialogs.pop()


def all_controls(control):
    """Every control in a tree (to look for texts)."""
    yield control
    for attr in ("controls", "content"):
        child = getattr(control, attr, None)
        for c in (child if isinstance(child, list) else [child] if child is not None else []):
            if isinstance(c, ft.Control):
                yield from all_controls(c)


def texts(page):
    return " ".join(c.value for root in page.controls for c in all_controls(root)
                    if isinstance(c, ft.Text) and isinstance(c.value, str))


def degrees(box):
    return math.degrees(box.rotate.angle) % 360


def glowing(view):
    """The boards of a table view that glow gold."""
    return {n for n, box in view.boards.items() if box.shadow is not None and box.shadow.color != "#000000"}


def click(page, label):
    """Tap the card or button that shows `label`."""
    for root in page.controls:
        for c in all_controls(root):
            if getattr(c, "on_click", None) and any(isinstance(x, ft.Text) and x.value == label
                                                     for x in all_controls(c)):
                c.on_click(None)
                return
    raise AssertionError(f"nothing to tap shows {label!r}")


def find(page, kind):
    return [c for root in page.controls for c in all_controls(root) if isinstance(c, kind)]


def type_into(field, text):
    field.value = text
    field.on_change(SimpleNamespace(control=field))


def human_game(width=1300, height=900, seats=(("human", "random", "random"))):
    page = FakePage(width=width, height=height)
    app = TalatApp(page)
    app.seats = dict(zip(PLAYERS, seats))
    app.delay = 0
    app.start()
    return page, app


def test_tower_shapes():
    assert len(shape_points(Shape.H, 0, 0, 1)) == 6
    assert len(shape_points(Shape.Q, 0, 0, 1)) == 4
    assert len(shape_points(Shape.T, 0, 0, 1)) == 3
    assert tower_view(t("2MT"), 50).width == 50


def test_start_screen():
    page = FakePage()
    TalatApp(page)
    assert "Talat" in texts(page) and "Solo" in texts(page) and "Pass & play" in texts(page)
    assert "CSE" not in texts(page) and "LAB" not in texts(page).upper()   # no course text in the game


@pytest.mark.parametrize("width, height", [(1300, 900), (412, 860)])     # laptop and phone
def test_human_turn_pair_then_focus_then_back(width, height):
    """Human's turn: their two boards come forward; they pick one, play on it, then the next turn."""
    page, app = human_game(width, height)
    s = app.session
    assert app.stage == "pair" and "choose a board" in texts(page)
    app.focus_board("B")                              # not one of White's boards: ignored
    assert app.stage == "pair"
    app.focus_board("A")
    assert app.stage == "focus" and app.focus == "A" and "place a tower" in texts(page)
    square = next(sq for (board, sq) in s.targets() if board == "A")
    app.human(lambda: s.tap("A", square))             # White places; the two random AIs answer at once
    assert s.state.to_move == 1 and len(s.log) == 3
    assert app.stage == "pair" and app.focus is None  # back to choosing a board

    # Play phase: select a tower on the big board, then look around.
    s.state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MT", (4, 0): "2SQ"}})
    app.turn_view()
    app.focus_board("A")
    app.human(lambda: s.tap("A", (1, 2)))
    assert app.stage == "focus" and "tap a highlighted square" in texts(page)
    app.show_pair()                                   # the back arrow
    assert app.stage == "pair" and s.selected is None
    app.show_table()                                  # peek at the whole table
    assert app.stage == "table" and "tap one of your boards" in texts(page)


def test_camera_zooms_in_while_the_boards_keep_their_table_angles():
    page, app = human_game(412, 860)
    zoom = {}
    for stage in ("table", "pair", "focus"):
        if stage == "focus":
            app.focus_board("A")
        elif stage == "table":
            app.show_table()
        else:
            app.show_pair()
        zoom[stage] = app.main.world.scale.scale
        for name, box in app.main.boards.items():      # the table never changes: same angles, all boards shown
            assert degrees(box) == pytest.approx(BOARD_TURN[name] % 360)
            assert box.opacity > 0
    assert zoom["pair"] >= zoom["table"] and zoom["focus"] >= 2 * zoom["table"]
    # the focused board sits in the middle of the scene
    view, world = app.main_rect, app.main.world
    box, k = app.main.boards["A"], world.scale.scale
    centre = (world.left + k * (box.left + box.width / 2), world.top + k * (box.top + box.height / 2))
    assert centre == pytest.approx((view.w / 2, view.h / 2), abs=1)   # in the middle of the main view
    # towers are turned back so they stand upright on the turned board
    _, holder = app.main.cells[("A", (0, 0))]
    assert math.degrees(holder.rotate.angle) == pytest.approx(-BOARD_TURN["A"])


def test_your_boards_glow_until_you_pick_one():
    page, app = human_game()
    boards = app.main.boards
    assert glowing(app.main) == {"A", "C"}             # White's two boards
    assert boards["A"].on_click is not None and boards["B"].on_click is None
    boards["A"].on_click(None)                        # tapping a glowing board zooms in on it
    assert app.stage == "focus" and app.focus == "A"
    assert boards["C"].on_click is not None           # the other one can still be picked
    assert boards["A"].opacity == 1.0 and boards["B"].opacity < boards["C"].opacity < 1.0
    # zoomed in, the table's letters, discs and names fade out; the status names the board
    marks = list(app.main.letters.values()) + list(app.main.discs.values()) + list(app.main.labels.values())
    assert all(c.opacity == 0 for c in marks)
    assert "Board A ·" in texts(page)
    app.show_table()
    assert all(c.opacity == 1 for c in marks)


def test_board_controls_persist_so_the_camera_can_animate():
    page, app = human_game()
    world, boxes = app.main.world, dict(app.main.boards)
    s = app.session
    app.focus_board("A")
    square = next(sq for (board, sq) in s.targets() if board == "A")
    app.human(lambda: s.tap("A", square))
    assert app.main.world is world and all(app.main.boards[n] is boxes[n] for n in boxes)
    assert world.animate_position and world.animate_scale


def test_ai_game_plays_to_the_end_and_shows_the_result():
    page = FakePage()
    app = TalatApp(page)
    app.seats = {p: "random" for p in PLAYERS}
    app.delay = 0
    app.start()
    assert app.session.is_over() and app.stage == "table"
    assert "Game over" in texts(page)
    assert len(page.dialogs) == 1


def test_frozen_board_and_pass_button():
    page, app = human_game()
    app.session.state = make_state({"A": {(1, 0): "1SQ", (2, 0): "2LH", (2, 1): "2LQ", (4, 4): "2MT"},
                                    "C": {(0, 4): "3MH", (1, 4): "3ST"}})
    app.turn_view()
    app.render()                                      # White is stuck: pass
    assert any(isinstance(c, ft.FilledButton) and c.content == "No moves: pass"
               for root in page.controls for c in all_controls(root))
    assert app.main.boards["C"].opacity == 0.4        # frozen
    app.show_table()
    assert sorted(b.opacity for b in app.main.boards.values()) == [0.4, 1.0, 1.0]


def test_new_game_returns_to_the_start_screen():
    page, app = human_game()
    app.new_game()
    assert app.session is None and app.scene is None and "Solo" in texts(page)


def test_table_gets_all_the_room_between_the_bars():
    """On a 360 x 800 phone with a 30 dp status bar and a 20 dp gesture bar."""
    page = FakePage(360, 800)
    page.media = SimpleNamespace(padding=SimpleNamespace(top=30, bottom=20))
    app = TalatApp(page)
    app.seats = {1: "human", 2: "random", 3: "random"}
    app.delay = 0
    app.start()
    pad, gaps, top_bar = 2 * 8, 2 * 8, 56
    assert app.scene_size == (360 - pad, 800 - pad - 30 - 20 - top_bar - 140 - gaps)   # room for the tray
    s = app.session
    while s.state.phase == "setup":                     # White places all 9 towers (the AIs answer)
        board = s.playable_boards()[0]
        app.focus_board(board)
        square = next(sq for (b, sq) in s.targets() if b == board)
        app.human(lambda: s.tap(board, square))
    assert app.scene_size == (360 - pad, 800 - pad - 30 - 20 - top_bar - 52 - gaps)    # the tray's room is used



def phone_game(seats=("human", "random", "random")):
    page = FakePage(360, 800)
    page.media = SimpleNamespace(padding=SimpleNamespace(top=30, bottom=20))
    app = TalatApp(page)
    app.seats = dict(zip(PLAYERS, seats))
    app.delay = 0
    app.start()
    return page, app


def test_phone_uses_the_space_above_the_table():
    page, app = phone_game()
    main, side = app.main_rect, app.side_rect
    assert main.w == main.h == app.scene_size[0]                  # the table: a full-width square...
    assert side is not None and side.y == 0 and side.h > 120      # ...with room above it
    # table / your turn: the players panel shows there
    assert app.panel.opacity == 1.0 and app.mini.frame.opacity == 0.0
    assert "You" in texts(page) and "Hard AI" not in texts(page)  # Solo here is against two random agents
    assert "no captures yet" in texts(page)
    # zoomed in: a mini table keeps all three boards in view, the chosen one glowing
    app.focus_board("A")
    assert app.mini.frame.opacity == 1.0 and app.panel.opacity == 0.0
    assert glowing(app.mini) == {"A"}
    assert app.mini.boards["C"].on_click is not None and app.mini.boards["A"].on_click is None
    app.mini.boards["C"].on_click(None)                           # switch boards from the mini table
    assert app.focus == "C"


def test_captured_towers_show_in_the_players_panel():
    page, app = phone_game()
    app.session.state = make_state({"A": {(1, 2): "1LH", (4, 0): "2SQ"}})
    app.session.state.captured[1] = (t("2MQ"), t("3ST"))
    app.turn_view()
    app.render()
    canvases = [c for c in all_controls(app.panel) if c.__class__.__name__ == "Canvas"]
    assert len(canvases) == 2                                      # White's two captured towers


def test_watching_needs_no_mini_table():
    page, app = phone_game(seats=("random", "random", "random"))
    assert app.mini is None and app.panel is not None


def test_boards_have_no_frame_so_the_squares_get_the_room():
    page, app = phone_game()
    for view in (app.main, app.mini):
        assert 5 * view.cell_px + 2 * view.edge == pytest.approx(view.board_px)
        assert view.edge <= max(1.0, 0.01 * view.board_px)             # just a hairline outline
    for stage in (app.show_table, app.show_pair, lambda: app.focus_board("A")):
        stage()                                                        # boards glow; the outline stays put
        assert {box.border.top.width for box in app.main.boards.values()} == {app.main.edge}


def test_pass_and_play_names_every_player():
    page = FakePage(360, 800)
    app = TalatApp(page)
    click(page, "Pass & play")
    assert set(app.seats.values()) == {"human"} and app.customize    # the name fields open by themselves
    assert not find(page, ft.Slider)                                  # no AI, so no AI thinking time
    names = find(page, ft.TextField)
    assert [f.hint_text for f in names] == ["Player 1", "Player 2", "Player 3"]
    type_into(names[0], "Alif")
    type_into(names[1], " Rafi ")
    app.delay = 0
    app.start()
    s = app.session
    assert "Alif's turn · choose a board" in texts(page)
    assert "Rafi" in texts(page) and "Player 3" in texts(page)          # in the panel and on the table
    labels = app.main.labels
    assert [labels[p].content.value for p in PLAYERS] == ["Alif", "Rafi", "Player 3"]
    assert labels[1].content.color == GOLD and labels[2].content.color != GOLD
    app.focus_board("A")
    assert "Alif · place a tower on your starting line" in texts(page)
    square = next(sq for (board, sq) in s.targets() if board == "A")
    app.human(lambda: s.tap("A", square))
    assert s.to_move == 2 and "Rafi's turn · choose a board" in texts(page)
    assert labels[2].content.color == GOLD


def test_a_human_seat_gets_a_name_field():
    page = FakePage(360, 800)
    app = TalatApp(page)
    app.toggle_customize()
    assert [f.hint_text for f in find(page, ft.TextField)] == ["You"]      # Solo: just you
    seat = find(page, ft.Dropdown)[1]                                      # Black: make it a human
    seat.value = "human"
    seat.on_select(SimpleNamespace(control=seat))
    assert [f.hint_text for f in find(page, ft.TextField)] == ["Player 1", "Player 2"]


def test_names_in_the_status():
    page, app = human_game(seats=("human", "human", "greedy"))
    assert [app.display_name(p) for p in PLAYERS] == ["Player 1", "Player 2", "Easy AI"]
    assert "Player 1's turn" in texts(page)
    page, app = human_game()
    assert "Your turn · choose a board" in texts(page)
    app.session.state = make_state({}, to_move=2)
    app.paused = True
    app.turn_view()
    app.render()
    assert "Paused · Random (Black) is next" in texts(page)


@pytest.mark.parametrize("seats, names, winner, title", [
    (("human", "random", "random"), {}, 1, "You win"),
    (("human", "human", "random"), {2: "Rafi"}, 2, "Rafi wins"),
    (("human", "human", "random"), {}, 3, "Random wins"),
])
def test_the_result_names_the_winner(seats, names, winner, title):
    page, app = human_game(seats=seats)
    app.names.update(names)
    app.session.state = make_state({})
    app.session.state.captured[winner] = (t(f"{winner % 3 + 1}MQ"),)
    app.show_result()
    assert page.dialogs[-1].title.value == title


def test_the_tray_shows_your_towers_through_the_whole_setup_turn():
    page, app = human_game()
    s = app.session
    tray = app.bottom.content.controls[-1]
    assert app.stage == "pair" and len(tray.controls) == 9 and tray.controls[0].on_click is not None
    app.paused = True                                  # hold the AIs, to look at the tray on their turn
    app.focus_board("A")
    square = next(sq for (board, sq) in s.targets() if board == "A")
    app.human(lambda: s.tap("A", square))
    tray = app.bottom.content.controls[-1]
    assert s.to_move == 2 and len(tray.controls) == 8  # still your towers, dimmed, while an AI places
    assert tray.opacity < 1 and tray.controls[0].on_click is None
