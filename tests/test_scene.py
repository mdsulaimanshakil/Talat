import math

import pytest

from talat.engine import BOARD_PLAYERS, PLAYERS, boards_of
from talat.scene import (
    BOARD_TURN, PLAYER_SPOT, SIDE_GAP, SIDE_MIN, TABLE_ABOVE, TABLE_BELOW, TABLE_W, TOKEN, board_centre,
    board_corners, camera, focus_camera, name_box, pair_camera, regions, table_camera,
)

SCREENS = {"phone": (388, 560), "phone-landscape": (780, 300), "laptop": (1376, 680)}


def gap(p, q):
    """Separating-axis distance between two convex polygons (> 0 means apart)."""
    best = -math.inf
    for poly in (p, q):
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            nx, ny = y2 - y1, x1 - x2
            length = math.hypot(nx, ny)
            a = [(x * nx + y * ny) / length for x, y in p]
            b = [(x * nx + y * ny) / length for x, y in q]
            best = max(best, min(b) - max(a), min(a) - max(b))
    return best


def on_screen(cam, points, size):
    w, h = size
    return all(-0.5 <= x <= w + 0.5 and -0.5 <= y <= h + 0.5 for x, y in (cam.to_screen(p, w, h) for p in points))


# ---------- the table itself (never changes) ----------

def test_boards_do_not_overlap_and_fit_the_table():
    for a, b in [("A", "B"), ("B", "C"), ("A", "C")]:
        assert gap(board_corners(a), board_corners(b)) > 0.05
    xs = [x for n in BOARD_TURN for x, _ in board_corners(n)]
    ys = [y for n in BOARD_TURN for _, y in board_corners(n)]
    assert max(abs(x) for x in xs) <= TABLE_W / 2 and -min(ys) <= TABLE_ABOVE and max(ys) <= TABLE_BELOW


def test_starting_lines_face_their_players():
    """Each board's top row points at its top player, its bottom row at its bottom player."""
    for name, (top, bottom) in BOARD_PLAYERS.items():
        t = math.radians(BOARD_TURN[name])
        up = (math.sin(t), -math.cos(t))
        cx, cy = board_centre(name)
        for player, sign in ((top, 1), (bottom, -1)):
            px, py = PLAYER_SPOT[player]
            cos = (up[0] * (px - cx) + up[1] * (py - cy)) / math.hypot(px - cx, py - cy)
            assert sign * cos > 0.9


def test_layout_matches_the_physical_game():
    assert board_centre("A")[0] > 0 > board_centre("C")[0]       # A upper right, C upper left
    assert board_centre("B")[1] > board_centre("A")[1]           # B at the bottom
    assert PLAYER_SPOT[1][1] < 0 < PLAYER_SPOT[2][0]             # White at the top, Black on the right


def test_player_discs_are_clear_of_the_boards():
    r = TOKEN / 2
    for px, py in PLAYER_SPOT.values():
        circle = [(px + r * math.cos(math.radians(k)), py + r * math.sin(math.radians(k))) for k in range(0, 360, 10)]
        assert all(gap(circle, board_corners(n)) > 0 for n in BOARD_TURN)


# ---------- the camera ----------

@pytest.mark.parametrize("screen", SCREENS)
def test_table_camera_shows_everything(screen):
    cam = table_camera(*SCREENS[screen])
    points = [p for n in BOARD_TURN for p in board_corners(n)]
    points += [(x, y + d) for x, y in PLAYER_SPOT.values() for d in (-TOKEN / 2, TOKEN / 2)]
    assert on_screen(cam, points, SCREENS[screen])


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("player", PLAYERS)
def test_pair_camera_closes_in_on_my_two_boards(screen, player):
    size = SCREENS[screen]
    table, pair = table_camera(*size), pair_camera(player, *size)
    assert on_screen(pair, [p for n in boards_of(player) for p in board_corners(n)], size)
    assert pair.zoom >= table.zoom                               # never further out than the table


def test_pair_camera_makes_the_boards_bigger_where_the_screen_allows():
    """White's boards (A, C) sit side by side, so a wide screen has room to close in; Black's
    and Grey's are stacked (A or C above B), so a tall phone has room."""
    phone, laptop = SCREENS["phone"], SCREENS["laptop"]
    for player in (2, 3):
        assert pair_camera(player, *phone).zoom > 1.3 * table_camera(*phone).zoom
        assert pair_camera(player, *laptop).zoom > 1.05 * table_camera(*laptop).zoom
    assert pair_camera(1, *laptop).zoom > 1.8 * table_camera(*laptop).zoom


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("board", list(BOARD_TURN))
def test_focus_camera_fills_the_screen_with_the_board(screen, board):
    size = SCREENS[screen]
    focus = focus_camera(board, *size)
    assert on_screen(focus, board_corners(board), size)
    for player in BOARD_PLAYERS[board]:
        assert focus.zoom >= pair_camera(player, *size).zoom
    # it fills one side of the screen (up to the margin)
    xs, ys = zip(*(focus.to_screen(p, *size) for p in board_corners(board)))
    assert max(max(xs) - min(xs), max(ys) - min(ys)) >= min(size) * 0.9


def test_focus_on_a_phone_is_at_least_twice_the_table():
    phone = SCREENS["phone"]
    for board in BOARD_TURN:
        assert focus_camera(board, *phone).zoom >= 2 * table_camera(*phone).zoom


def test_camera_dispatch():
    size = SCREENS["phone"]
    assert camera("table", 1, None, *size) == table_camera(*size)
    assert camera("pair", 2, None, *size) == pair_camera(2, *size)
    assert camera("focus", 3, "B", *size) == focus_camera("B", *size)
    assert camera("focus", 3, None, *size) == table_camera(*size)


# ---------- splitting the screen ----------

def test_tall_phone_gets_a_side_area_above_a_full_width_square():
    main, side = regions(344, 610)
    assert (main.w, main.h) == (344, 344) and main.y + main.h == 610       # square at the bottom
    assert side.y == 0 and side.h == 610 - 344 - SIDE_GAP and side.w == 344


def test_wide_screen_gets_a_side_area_on_the_left():
    main, side = regions(1360, 610)
    assert (main.w, main.h) == (610, 610) and main.x + main.w == 1360
    assert side.x == 0 and side.w == 1360 - 610 - SIDE_GAP


def test_no_side_area_when_there_is_no_room():
    main, side = regions(500, 500 + SIDE_GAP + SIDE_MIN - 1)
    assert side is None and (main.w, main.h) == (500, 500 + SIDE_GAP + SIDE_MIN - 1)


def test_the_square_loses_nothing_on_a_tall_phone():
    """The table and a zoomed board are limited by the width anyway."""
    main, _ = regions(344, 610)
    assert table_camera(main.w, main.h).zoom == pytest.approx(table_camera(344, 610).zoom)
    for board in BOARD_TURN:
        assert focus_camera(board, main.w, main.h).zoom == pytest.approx(focus_camera(board, 344, 610).zoom)


def test_pair_camera_never_just_shifts_the_table():
    """Where closing in can't enlarge the boards, the whole table (all three boards) stays in view."""
    for name, size in SCREENS.items():
        table = table_camera(*size)
        for player in PLAYERS:
            pair = pair_camera(player, *size)
            assert pair == table or pair.zoom >= 1.05 * table.zoom
    assert pair_camera(1, *SCREENS["phone"]) == table_camera(*SCREENS["phone"])


def test_name_labels_fit_on_the_table_and_stay_clear_of_the_boards():
    for p in PLAYERS:
        x, y, w, h = name_box(p)
        rect = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]
        assert all(gap(rect, board_corners(n)) > 0 for n in BOARD_TURN)
        assert abs(x) + w / 2 <= TABLE_W / 2 and y + h / 2 <= TABLE_BELOW and y - h / 2 >= -TABLE_ABOVE
        assert y - h / 2 > PLAYER_SPOT[p][1] + TOKEN / 2                  # below the disc, not on it
