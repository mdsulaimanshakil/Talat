"""Smoke tests for the Flet app: build every screen with a stand-in page (no window).
The board layouts themselves are tested in test_scene.py."""
import pytest

ft = pytest.importorskip("flet")

import math  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from talat.app import FRAME_SHARE, GOLD, SCROLL_GUTTER, TalatApp, shape_points, tower_view  # noqa: E402
from talat.scene import BOARD_TURN  # noqa: E402
from talat.look import FRAMES, THEMES, TOWER_STYLES, Look, Settings  # noqa: E402
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
    """The boards of a table view that glow in the accent colour (the others cast a plain shadow)."""
    return {n for n, box in view.boards.items() if box.shadow is not None and box.shadow.color == GOLD}


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


@pytest.mark.parametrize("width, height", [(412, 860), (600, 860)])     # phones: the camera zooms in
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
    # The table itself is drawn big now (boards corner to corner), so zooming in roughly doubles it.
    assert zoom["pair"] >= zoom["table"] and zoom["focus"] >= 1.9 * zoom["table"]
    # the focused board sits in the middle of the scene
    view, world = app.main_rect, app.main.world
    box, k = app.main.boards["A"], world.scale.scale
    centre = (world.left + k * (box.left + box.width / 2), world.top + k * (box.top + box.height / 2))
    assert centre == pytest.approx((view.w / 2, view.h / 2), abs=1)   # in the middle of the main view
    # towers are turned back so they stand upright on the turned board
    _, holder = app.main.cells[("A", (0, 0))]
    assert math.degrees(holder.rotate.angle) == pytest.approx(-BOARD_TURN["A"])


def test_your_boards_glow_until_you_pick_one():
    page, app = human_game(412, 860)                   # phone: tap a glowing board to zoom in
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


def test_boards_have_a_frame_around_their_squares():
    page, app = phone_game()
    for view in (app.main, app.mini):
        assert 5 * view.cell_px + 2 * view.edge == pytest.approx(view.board_px)
        assert view.edge == pytest.approx(FRAME_SHARE * view.board_px)  # the frame band
    sizes = set()
    for stage in (app.show_table, app.show_pair, lambda: app.focus_board("A")):
        stage()                                                        # boards glow; their size stays put
        sizes |= {(box.width, box.height) for box in app.main.boards.values()}
    assert sizes == {(app.main.board_px, app.main.board_px)}


def test_without_a_frame_boards_get_a_hairline_outline():
    page, app = phone_game()
    app.change(frame="none")
    for view in (app.main, app.mini):
        assert 5 * view.cell_px + 2 * view.edge == pytest.approx(view.board_px)
        assert view.edge <= max(1.0, 0.01 * view.board_px)
        assert {box.border.top.width for box in view.boards.values()} == {view.edge}


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
    page, app = human_game(412, 860, seats=("human", "human", "greedy"))
    assert [app.display_name(p) for p in PLAYERS] == ["Player 1", "Player 2", "Easy AI"]
    assert "Player 1's turn" in texts(page)
    page, app = human_game(412, 860)
    assert "Your turn · choose a board" in texts(page)
    app.session.state = make_state({}, to_move=2)
    app.paused = True
    app.turn_view()
    app.render()
    assert "Paused · Random (Onyx) is next" in texts(page)           # the player's colour, by name


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
    page, app = human_game(412, 860)
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


# ---------- the look: settings, desktop layout, towers ----------

def test_wide_screens_have_no_players_list():
    """On a laptop or monitor the table gets the whole scene, centred; scores are on the table."""
    page, app = human_game(1920, 1080)
    assert app.side_rect is None and app.panel is None and app.mini is None
    assert (app.main_rect.x, app.main_rect.y) == (0, 0) and app.main_rect.w == app.scene_size[0]
    assert "no captures yet" not in texts(page)
    assert all(label.content.value for label in app.main.labels.values())   # names and scores on the table


def test_desktop_home_shows_the_menu_beside_the_table():
    page = FakePage(1920, 1080)
    TalatApp(page)
    canvases = [c for c in find(page, ft.Container) if c.content.__class__.__name__ == "Canvas"]
    assert len(canvases) > 20                                   # the table's towers, drawn in the chosen look
    assert "Solo" in texts(page) and "Appearance" in [b.content for b in find(page, ft.OutlinedButton)]


def test_settings_change_the_look_everywhere_and_are_remembered():
    page = FakePage(1920, 1080)
    app = TalatApp(page)
    app.open_settings()
    assert app.screen == "settings"
    for title in ("Settings", "THEME", "TOWER COLOURS", "TOWER SIZE BORDERS", "BOARD FRAME", "Jade Court"):
        assert title in texts(page)
    app.change(theme="jade", palette="cobalt", towers="rings")
    assert page.bgcolor == THEMES["jade"].bg and app.look.colour_name(2) == "Cobalt"
    app.close_settings()
    assert app.screen == "start"
    again = TalatApp(FakePage(1920, 1080))                        # next time the app opens
    assert again.settings.theme == "jade" and again.look.style == "rings"
    app.reset_settings()
    assert app.settings.theme == "midnight" and TalatApp(FakePage()).settings.theme == "midnight"


def test_settings_from_a_game_return_to_it_in_the_new_look():
    page, app = human_game(1920, 1080)
    s = app.session
    app.open_settings()
    app.change(frame="oxblood", palette="teal")
    app.close_settings()
    assert app.screen == "game" and app.session is s
    assert app.main.look.frame == FRAMES["oxblood"][1] and app.look.colour_name(3) == "Teal"


def test_the_game_waits_while_the_player_is_in_settings():
    page, app = human_game()
    app.session.state = make_state({}, to_move=2)              # an AI is to move
    calls = []
    page.run_thread = lambda handler, *args: calls.append(handler)
    app.open_settings()
    app.maybe_run_ai()
    assert not calls
    app.close_settings()
    assert calls                                               # it carries on when they come back


@pytest.mark.parametrize("style", list(TOWER_STYLES))
def test_towers_show_their_size(style):
    look = Look(Settings(towers=style))
    drawn = {z: len(tower_view(t(f"1{z}H"), 60, look).shapes) for z in "SML"}
    if style == "plain":
        assert drawn["S"] == drawn["M"] == drawn["L"]           # size only
    else:
        assert drawn["S"] < drawn["M"] < drawn["L"]             # 1, 2, 3 outlines


def test_move_hints_can_be_turned_off():
    page, app = human_game()
    app.change(hints=False)
    app.focus_board("A")
    s = app.session
    square = next(sq for (board, sq) in s.targets() if board == "A")
    cell, holder = app.main.cells[("A", square)]
    assert holder.content is None and cell.on_click is not None    # no dot, but still a square you can tap


# ---------- computer screens: the whole table, turned to the player ----------

def turn_mod(angle):
    return round(angle) % 360


def test_desktop_players_play_on_the_whole_table_without_zooming():
    page, app = human_game(1920, 1080)
    s = app.session
    assert app.stage == "table" and glowing(app.main) == {"A", "C"}          # White's boards glow
    assert all(box.on_click is None for box in app.main.boards.values())       # nothing to zoom into
    assert "Your turn · place a tower on your starting line" in texts(page)
    app.focus_board("A")
    assert app.stage == "table"                                                # still the whole table
    board, square = next(iter(s.targets()))
    cell, _ = app.main.cells[(board, square)]
    assert app.main.cells[("B", (2, 2))][0].on_click is None                   # not one of yours
    cell.on_click(None)                                                        # tap your starting line
    assert len(s.log) == 3 and s.to_move == 1                                  # placed; both AIs answered

    s.state = make_state({"A": {(1, 2): "1LH", (2, 3): "2MT", (4, 0): "2SQ"}, "C": {(4, 2): "1SQ"}})
    app.turn_view()
    app.render()
    assert "Your turn · tap one of your towers" in texts(page)
    app.main.cells[("A", (1, 2))][0].on_click(None)                            # select straight on the table
    assert s.selected == ("A", (1, 2)) and "tap a highlighted square" in texts(page)


def test_desktop_table_turns_so_the_player_to_move_sits_at_the_bottom():
    page, app = human_game(1920, 1080, seats=("human", "human", "random"))
    s, view = app.session, app.main
    assert turn_mod(view.turn) == 180                     # White's seat comes to the bottom...
    assert all(turn_mod(math.degrees(holder.rotate.angle)) == turn_mod(-BOARD_TURN[n] - 180)
               for (n, _), (_, holder) in view.cells.items())                  # ...towers stay upright
    assert all(turn_mod(math.degrees(box.rotate.angle)) == 180 for box in view.letters.values())
    assert view.labels[1].top == 0 and view.labels[2].top > 0                  # bottom seat: name above
    before = view.turn
    board, square = next(iter(s.targets()))
    app.human(lambda: s.tap(board, square))
    assert s.to_move == 2 and turn_mod(view.turn) == 60                        # now Black's turn
    assert abs(view.turn - before) == pytest.approx(120)                       # the short way round
    assert app.main is view                                                    # turned, not redrawn


def test_desktop_table_holds_still_while_the_ais_move():
    page, app = human_game(1920, 1080)                    # Solo: you against two AIs
    s = app.session
    board, square = next(iter(s.targets()))
    app.human(lambda: s.tap(board, square))
    assert s.to_move == 1 and turn_mod(app.main.turn) == 180      # still facing you


def test_watching_on_a_desktop_never_turns_the_table():
    page = FakePage(1920, 1080)
    app = TalatApp(page)
    app.seats = {p: "random" for p in PLAYERS}
    app.delay = 0
    app.start()
    assert app.session.is_over() and app.main.turn == 0


@pytest.mark.parametrize("width, height", [(1280, 720), (1920, 1080), (1366, 640)])
def test_desktop_home_fits_one_page_without_scrolling(width, height):
    page = FakePage(width, height)
    app = TalatApp(page)
    assert not [c for c in find(page, ft.Column) if c.scroll]          # nothing scrolls
    click(page, "With a friend")                                        # two humans: the players open...
    assert app.customize and not [c for c in find(page, ft.Column) if c.scroll]
    assert [f.hint_text for f in find(page, ft.TextField)] == ["Player 1", "Player 2"]   # ...beside the menu
    assert "Players" in texts(page) and "Solo" in texts(page)
    next(b for b in find(page, ft.TextButton) if b.content == "Done").on_click(None)
    assert not app.customize


@pytest.mark.parametrize("width, height", [(1280, 720), (1920, 1080), (412, 860)])
def test_the_settings_scrollbar_has_its_own_lane(width, height):
    """The scrolling list is wider than its tiles, so the scrollbar never covers them."""
    page = FakePage(width, height)
    app = TalatApp(page)
    app.open_settings()
    scrolling = [c for c in find(page, ft.Column) if c.scroll]
    assert len(scrolling) == 1 and scrolling[0].width is not None
    widest = max(c.width for c in all_controls(scrolling[0]) if isinstance(c, (ft.Row, ft.Container)) and c.width)
    assert scrolling[0].width - widest >= SCROLL_GUTTER
