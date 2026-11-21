"""The table, and the camera that looks at it.

The three boards never move: they sit exactly like the real game, with board A
upper right, C upper left and B at the bottom, each turned so its starting
lines face its two players. What changes during a turn is the camera:
- "table": the whole table fits the screen (AI turns, watching);
- "pair":  on a human's turn the camera moves in on their two boards;
- "focus": the chosen board fills the screen, with its neighbours around it.

Pure geometry with no UI code, so it can be tested. Table coordinates are in
board widths with the origin at the table centre (y points down); screen
coordinates are pixels from the scene's top-left corner.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from talat.engine import BOARD_PLAYERS

# The boards meet corner to corner, like the real board. Each board is turned to face its own
# direction, so two neighbours' corners meet on the line halfway between them when the centre
# distance is 0.5 + 0.5 / sqrt(3) board widths.
BOARD_DISTANCE = 0.5 + 0.5 / math.sqrt(3)         # table centre -> board centre (0.789)
BOARD_DIRECTION = {"A": -30, "B": 90, "C": 210}    # where each board sits (degrees, clockwise)
BOARD_TURN = {"A": -30, "B": 90, "C": -150}        # rotation so starting lines face their players
_SEAT = 1.15 * math.cos(math.radians(30))         # Black and Grey sit 1.15 out, at 30 and 150 degrees
PLAYER_SPOT = {1: (0.0, -1.18), 2: (_SEAT, 0.575), 3: (-_SEAT, 0.575)}
TABLE_W, TABLE_ABOVE, TABLE_BELOW = 2.80, 1.36, 1.32   # width; height above / below the centre
TOKEN = 0.30                                       # player disc diameter
LETTER_DISTANCE = 0.15                             # board letters, in the gap where the corners meet
NAME_GAP, NAME_W, NAME_H = 0.02, 0.50, 0.16        # a player's name, just under their disc

MARGIN = 1.03            # breathing room around what the camera frames
SIDE_GAP = 12.0          # between the main view and the side area, pixels
SIDE_MIN = 120.0         # the smallest side area worth showing, pixels
MAX_TABLE_ZOOM = 380.0   # pixels per board width: the table never gets bigger than this
MAX_ZOOM = 660.0         # nor does a board when the camera zooms in


def board_centre(name: str) -> tuple[float, float]:
    a = math.radians(BOARD_DIRECTION[name])
    return BOARD_DISTANCE * math.cos(a), BOARD_DISTANCE * math.sin(a)


def board_corners(name: str) -> list[tuple[float, float]]:
    cx, cy = board_centre(name)
    t = math.radians(BOARD_TURN[name])
    return [(cx + x * math.cos(t) - y * math.sin(t), cy + x * math.sin(t) + y * math.cos(t))
            for x, y in ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5))]


def name_box(player: int) -> tuple[float, float, float, float]:
    """(centre x, centre y, width, height) of a player's name label, just under their disc."""
    px, py = PLAYER_SPOT[player]
    return px, py + TOKEN / 2 + NAME_GAP + NAME_H / 2, NAME_W, NAME_H


def letter_spot(name: str) -> tuple[float, float]:
    a = math.radians(BOARD_DIRECTION[name])
    return LETTER_DISTANCE * math.cos(a), LETTER_DISTANCE * math.sin(a)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float


def regions(width: float, height: float) -> tuple[Rect, Rect | None]:
    """Split the scene into the main view, where the table (or the board the camera zooms into)
    is shown as large as it can be, and a side area for the players or a mini table.
    A tall phone keeps a side area above a full-width square. A wide screen (laptop, monitor)
    gives the whole scene to the table, centred, with no players list beside it: the scores sit
    on the table and in the top bar."""
    if height - width - SIDE_GAP >= SIDE_MIN:
        return Rect(0, height - width, width, width), Rect(0, 0, width, height - width - SIDE_GAP)
    return Rect(0, 0, width, height), None


@dataclass(frozen=True)
class Camera:
    x: float        # the table point shown at the centre of the scene
    y: float
    zoom: float     # pixels per board width

    def to_screen(self, point: tuple[float, float], width: float, height: float) -> tuple[float, float]:
        return width / 2 + (point[0] - self.x) * self.zoom, height / 2 + (point[1] - self.y) * self.zoom


# ---------- turning the table (computer screens) ----------
# On a computer screen the whole table turns so that the player whose turn it is sits at the
# bottom, their two boards in front of them and the third board across the table. The towers,
# letters, discs and names turn back so they stay upright.

def rotate_point(point: tuple[float, float], degrees: float) -> tuple[float, float]:
    t = math.radians(degrees)
    x, y = point
    return x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)


def facing_turn(player: int) -> float:
    """How far to turn the table (degrees, clockwise) to bring `player`'s seat to the bottom."""
    x, y = PLAYER_SPOT[player]
    return (90 - math.degrees(math.atan2(y, x))) % 360


def nearest_turn(current: float, target: float) -> float:
    """`target` written as the angle closest to `current`, so the table turns the short way."""
    return current + ((target - current + 180) % 360 - 180)


def name_below(player: int, turn: float = 0.0) -> bool:
    """A player's name goes under their disc, except for the seat at the bottom of the screen,
    whose name goes above it (towards the table) so it doesn't stick out past the table."""
    return rotate_point(PLAYER_SPOT[player], turn)[1] < 1.0


def table_bounds(turn: float) -> tuple[float, float, float, float]:
    """(left, right, top, bottom) of everything on the table once it is turned by `turn` degrees."""
    points = [rotate_point(p, turn) for n in BOARD_TURN for p in board_corners(n)]
    for player, spot in PLAYER_SPOT.items():
        x, y = rotate_point(spot, turn)
        r = TOKEN / 2
        name = y + r + NAME_GAP + NAME_H if name_below(player, turn) else y - r - NAME_GAP - NAME_H
        points += [(x - r, y - r), (x + r, y + r), (x - NAME_W / 2, name), (x + NAME_W / 2, name)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def table_camera(width: float, height: float, turn: float = 0.0) -> Camera:
    """The whole table, as big as the screen allows. Turned tables are framed from their actual
    outline (in turned coordinates), since a turned table is a slightly different shape."""
    if not turn % 360:
        zoom = min(width / TABLE_W, height / (TABLE_ABOVE + TABLE_BELOW), MAX_TABLE_ZOOM)
        return Camera(0.0, (TABLE_BELOW - TABLE_ABOVE) / 2, zoom)
    left, right, top, bottom = table_bounds(turn)
    zoom = min(width / ((right - left) * MARGIN), height / ((bottom - top) * MARGIN), MAX_TABLE_ZOOM)
    return Camera((left + right) / 2, (top + bottom) / 2, zoom)


def _frame(points, width: float, height: float, at_least: float) -> Camera:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    zoom = min(width / ((max(xs) - min(xs)) * MARGIN), height / ((max(ys) - min(ys)) * MARGIN), MAX_ZOOM)
    return Camera((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, max(zoom, at_least))


def pair_camera(player: int, width: float, height: float) -> Camera:
    """Close in on the two boards `player` plays on. If that wouldn't make them meaningfully
    bigger (White's boards already span the width of a phone), keep the whole table in view
    rather than just shifting it and cutting the third board off."""
    table = table_camera(width, height)
    mine = [n for n, pair in BOARD_PLAYERS.items() if player in pair]
    closer = _frame([p for n in mine for p in board_corners(n)], width, height, table.zoom)
    return closer if closer.zoom >= 1.05 * table.zoom else table


def focus_camera(board: str, width: float, height: float) -> Camera:
    """The chosen board as large as the screen allows, at its table angle."""
    return _frame(board_corners(board), width, height, table_camera(width, height).zoom)


def camera(stage: str, player: int, focus: str | None, width: float, height: float) -> Camera:
    if stage == "focus" and focus is not None:
        return focus_camera(focus, width, height)
    if stage == "pair":
        return pair_camera(player, width, height)
    return table_camera(width, height)
