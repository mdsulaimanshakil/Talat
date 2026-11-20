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

BOARD_DISTANCE = 0.86                              # table centre -> board centre
BOARD_DIRECTION = {"A": -30, "B": 90, "C": 210}    # where each board sits (degrees, clockwise)
BOARD_TURN = {"A": -30, "B": 90, "C": -150}        # rotation so starting lines face their players
PLAYER_SPOT = {1: (0.0, -1.30), 2: (1.195, 0.69), 3: (-1.195, 0.69)}
TABLE_W, TABLE_ABOVE, TABLE_BELOW = 2.90, 1.48, 1.38   # width; height above / below the centre
TOKEN = 0.30                                       # player disc diameter
LETTER_DISTANCE = 0.18                             # board letters, out from the centre
NAME_GAP, NAME_W, NAME_H = 0.02, 0.50, 0.16        # a player's name, just under their disc

MARGIN = 1.03            # breathing room around what the camera frames
SIDE_GAP = 12.0          # between the main view and the side area, pixels
SIDE_MIN = 120.0         # the smallest side area worth showing, pixels
MAX_TABLE_ZOOM = 360.0   # pixels per board width: the table never gets bigger than this
MAX_ZOOM = 620.0         # nor does a board when the camera zooms in


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
    """Split the scene into the main view, a square in which the table (or the board the camera
    zooms into) is shown as large as it can be, and a side area for the players or a mini table:
    above the main view on a tall screen, to its left on a wide one; none if there's no room.
    (The table is about as tall as it is wide, so a square loses nothing.)"""
    if height - width - SIDE_GAP >= SIDE_MIN:
        return Rect(0, height - width, width, width), Rect(0, 0, width, height - width - SIDE_GAP)
    if width - height - SIDE_GAP >= SIDE_MIN:
        return Rect(width - height, 0, height, height), Rect(0, 0, width - height - SIDE_GAP, height)
    return Rect(0, 0, width, height), None


@dataclass(frozen=True)
class Camera:
    x: float        # the table point shown at the centre of the scene
    y: float
    zoom: float     # pixels per board width

    def to_screen(self, point: tuple[float, float], width: float, height: float) -> tuple[float, float]:
        return width / 2 + (point[0] - self.x) * self.zoom, height / 2 + (point[1] - self.y) * self.zoom


def table_camera(width: float, height: float) -> Camera:
    zoom = min(width / TABLE_W, height / (TABLE_ABOVE + TABLE_BELOW), MAX_TABLE_ZOOM)
    return Camera(0.0, (TABLE_BELOW - TABLE_ABOVE) / 2, zoom)


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
