"""TALAT app (Flet): desktop, web and phone.

    flet run                 # desktop window (uses main.py and the assets/ folder)
    flet run --android       # on an Android phone, via the Flet app
    flet build apk           # installable Android app

The boards sit on a table exactly like the real game, corner to corner, and never move or
turn; a camera zooms and pans over the table (see talat/scene.py):
- table: the whole table, while the AIs play;
- pair:  on a human's turn the camera closes in on their two boards, which glow;
- focus: the chosen board fills the screen, its neighbours still around it.
After a move the camera glides back to the whole table. On a wide screen the table gets the
whole screen, centred; on a tall phone a players panel sits above it, and while zoomed in a
mini table keeps all three boards in view.

How everything looks (theme, tower colours, how towers show their size, the board frame) is
the player's choice, under Settings; see talat/look.py.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):          # started as a script (flet run talat/app.py)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft
import flet.canvas as cv

from talat.engine import (
    BOARD_PLAYERS, BOARD_SIZE, PLAYERS, Board, GameState, Shape, Size, Square, Tower, boards_of, end_reason,
    is_frozen, scores, winners,
)
from talat.look import (
    FRAMES, PALETTES, SPEEDS, THEMES, TOWER_STYLES, Frame, Look, Settings, inset, load_settings, save_settings,
)
from talat.scene import (
    BOARD_TURN, NAME_GAP, PLAYER_SPOT, TOKEN, Camera, Rect, board_centre, camera, facing_turn, focus_camera,
    letter_spot, name_below, name_box, nearest_turn, regions, table_camera,
)
from talat.session import PRESETS, SEAT_CHOICES, Session, seat_name

# ---------- fixed parts of the look (the rest comes from the player's Look) ----------
GOLD = "#C9973A"         # the default accent
SELECT, CAPTURE = "#3D7BE0", "#E53935"
SERIF = "Talat Serif"    # Libre Baskerville Italic, bundled in assets/fonts (OFL licence)
AI_DELAY = 0.5           # pause between AI moves, so people can follow ("Normal" speed)
MOTION_SECONDS = 0.45
MOTION = ft.Animation(int(MOTION_SECONDS * 1000), ft.AnimationCurve.EASE_IN_OUT)   # every move between layouts
TOP_BAR = 56
PAGE_PAD = 8             # space around the whole screen
GAP = 8                  # between the top bar, the table and the status line
FRAME_SHARE = 0.06       # the board frame takes this much of a board's width on each side
WIDE = 900               # from this width a screen is laid out as a computer screen
WORLD_RADIUS = 1.65      # board widths from the table centre to the edge of everything on it
MENU_HEIGHT = 780        # the home menu's full height; on a shorter computer window it shrinks to fit
SCROLL_GUTTER = 18       # room kept beside scrolling lists for the scrollbar, so it never covers them
DEFAULT_LOOK = Look()

# Tower drawings are made on a 100-unit square, then scaled: small, medium, large.
RADIUS = {Size.S: 26, Size.M: 36, Size.L: 46}
OUTLINES = {Size.S: 1, Size.M: 2, Size.L: 3}


# ---------- drawing towers ----------

def shape_points(shape: Shape, cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    if shape == Shape.H:
        return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    if shape == Shape.Q:
        h = r * 0.78
        return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    cy += r * 0.15                                  # a triangle looks centred when nudged down
    return [(cx, cy - r), (cx + r * 0.95, cy + r * 0.62), (cx - r * 0.95, cy + r * 0.62)]


def polygon(points, color: str, stroke: float | None = None, round_joins: bool = False) -> cv.Path:
    (x0, y0), *rest = points
    elements = [cv.Path.MoveTo(x=x0, y=y0)] + [cv.Path.LineTo(x=x, y=y) for x, y in rest] + [cv.Path.Close()]
    style = ft.PaintingStyle.STROKE if stroke else ft.PaintingStyle.FILL
    return cv.Path(elements, paint=ft.Paint(color=color, style=style, stroke_width=stroke or 0,
                                            stroke_join=ft.StrokeJoin.ROUND if round_joins else ft.StrokeJoin.MITER))


def grown(points, by: float, color: str) -> list[cv.Path]:
    """The shape grown outward by `by` with rounded corners, as one solid patch of `color`."""
    out = [polygon(points, color)]
    if by > 0:
        out.append(polygon(points, color, 2 * by, round_joins=True))
    return out


def tower_view(tower: Tower, size: float, look: Look | None = None, ground: str | None = None) -> cv.Canvas:
    """A tower seen from above, in its player's colour. Its size shows twice: in its footprint and
    in its outlines, small 1, medium 2, large 3 (the player picks the style under Settings).
    `ground` is the colour under the tower, needed for the gaps between outer borders."""
    look = look or DEFAULT_LOOK
    colour, k, c = look.colour(tower.owner), size / 100, size / 2
    n, r = OUTLINES[tower.size], RADIUS[tower.size] * k
    body = shape_points(tower.shape, c, c, r)
    shapes: list[cv.Path] = []
    if look.style == "tiers":                       # storeys seen from above; the edge is the first outline
        tiers = look.tiers(tower.owner)
        for i in range(n):
            step = inset(body, i * 7.5 * k)
            shapes += [polygon(step, tiers[i]), polygon(step, colour.edge, (2.3 if i else 2.9) * k)]
    elif look.style == "rings":                     # a faint edge, then 1-3 bold rings inside
        shapes += [polygon(body, colour.fill), polygon(body, "#80" + colour.edge[1:], 1.5 * k)]   # #AARRGGBB
        shapes += [polygon(inset(body, i * 5.6 * k), colour.top, 2.7 * k) for i in range(1, n + 1)]
    elif look.style == "outer":                     # the usual body, framed by 1-3 two-tone borders
        ground = ground or look.theme.square
        body = shape_points(tower.shape, c, c, 22 * k)
        for i in range(n, 0, -1):                   # outermost first; each later patch covers the middle
            d, halo, core = (4.8 + (i - 1) * 7.4) * k, 2.6 * k, 1.4 * k
            shapes += grown(body, d + halo, colour.edge) + grown(body, d + core, colour.fill)
            shapes += grown(body, d - core, colour.edge) + grown(body, d - halo, ground)
        shapes += [polygon(body, colour.fill), polygon(body, colour.edge, 3 * k),
                   polygon(shape_points(tower.shape, c, c, 22 * 0.48 * k), colour.top, 2.4 * k)]
    else:                                           # plain: size only, solid body with a hollow top
        shapes += [polygon(body, colour.fill), polygon(body, colour.edge, 4.1 * k),
                   polygon(shape_points(tower.shape, c, c, r * 0.48), colour.top, 3.1 * k)]
    return cv.Canvas(shapes=shapes, width=size, height=size)


def frame_view(width: float, band: float, frame: Frame, board_turn: float, labels: bool) -> cv.Canvas:
    """The frame around a board's squares: a brass inlay along the squares, a diamond facing every
    row and column, a dot in each corner, and (if wanted) A-E along the bottom and 1-5 up the
    left. The labels turn against the board so they always read upright."""
    T, f = width, band
    g, s, il = (T - 2 * f) / BOARD_SIZE, max(1.0, f * 0.26), max(0.8, f * 0.12)
    fill = lambda color: ft.Paint(color=color, style=ft.PaintingStyle.FILL)
    shapes: list[cv.Control] = [
        cv.Rect(x=0, y=0, width=T, height=T, border_radius=max(1.0, f * 0.1), paint=fill(frame.wood)),
        cv.Rect(x=0.5, y=0.5, width=T - 1, height=T - 1, border_radius=max(1.0, f * 0.1),
                paint=ft.Paint(color=frame.rim, style=ft.PaintingStyle.STROKE, stroke_width=1)),
        cv.Rect(x=f - il / 2, y=f - il / 2, width=T - 2 * f + il, height=T - 2 * f + il,
                paint=ft.Paint(color=frame.inlay, style=ft.PaintingStyle.STROKE, stroke_width=il)),
    ]

    def diamond(x, y):
        return polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], frame.mark)

    text = ft.TextStyle(size=f * 0.72, weight=ft.FontWeight.BOLD, color=frame.mark)
    for i in range(BOARD_SIZE):
        p = f + g * (i + 0.5)
        shapes += [diamond(p, f / 2), diamond(T - f / 2, p)]                   # top and right
        if labels:
            for x, y, value in ((p, T - f / 2, "ABCDE"[i]), (f / 2, f + g * (BOARD_SIZE - 0.5 - i), str(i + 1))):
                shapes.append(cv.Text(x=x, y=y, value=value, style=text, alignment=ft.Alignment.CENTER,
                                      rotate=math.radians(-board_turn)))
        else:
            shapes += [diamond(p, T - f / 2), diamond(f / 2, p)]
    for x, y in ((f / 2, f / 2), (T - f / 2, f / 2), (f / 2, T - f / 2), (T - f / 2, T - f / 2)):
        shapes.append(cv.Circle(x=x, y=y, radius=s * 0.8, paint=fill(frame.mark)))
    return cv.Canvas(shapes=shapes, width=T, height=T)


def disc(player: int, size: float, label: str = "", glow: bool = False, look: Look | None = None) -> ft.Container:
    look = look or DEFAULT_LOOK
    box = ft.Container(width=size, height=size, border_radius=size / 2, bgcolor=look.colour(player).fill,
                       alignment=ft.Alignment.CENTER)
    style_disc(box, player, label, glow, look)
    return box


def style_disc(box: ft.Container, player: int, label: str, glow: bool, look: Look | None = None) -> None:
    look = look or DEFAULT_LOOK
    size, accent = box.width, look.theme.accent
    box.bgcolor = look.colour(player).fill
    box.border = ft.Border.all(3 if glow else 1.5, accent)
    box.shadow = ft.BoxShadow(blur_radius=size * 0.6, spread_radius=1, color=accent) if glow else None
    box.content = ft.Text(label, size=size * 0.36, weight=ft.FontWeight.BOLD,
                          color=look.colour(player).ink) if label else None


def serif(text: str, size: float, color: str = GOLD) -> ft.Text:
    return ft.Text(text, size=size, color=color, font_family=SERIF, italic=True, weight=ft.FontWeight.BOLD)


def turn(degrees: float) -> ft.Rotate:
    return ft.Rotate(angle=math.radians(degrees), alignment=ft.Alignment.CENTER)


# ---------- a fixed position, to show off a look without a game ----------

PREVIEW = {
    "A": "01W1TM 03W1HL 11G3QL 13W1QS 22W1TL 24B2HM 30W1QM 32B2TS 34B2HS 41B2QL 43B2HL",
    "B": "00B2HL 02B2QM 04B2TS 13G3TM 21B2HM 23W1QS 30G3HS 41G3QL 42G3TL 44G3HM",
    "C": "00G3QM 03G3HL 12G3TS 20B2TL 23W1HM 31G3QS 40W1TS 42W1QL 44W1HS",
}


class Preview:
    """Enough of a Session for TableView.refresh: a fixed mid-game position."""
    selected = last = None
    to_move = 1

    def __init__(self):
        boards = {name: Board.empty(name) for name in BOARD_PLAYERS}
        for name, codes in PREVIEW.items():
            for code in codes.split():
                boards[name][(int(code[0]), int(code[1]))] = Tower(int(code[3]), Size[code[5]], Shape[code[4]])
        self.state = GameState(boards=boards, phase="play", to_move=1, hands={p: () for p in PLAYERS},
                               captured={p: () for p in PLAYERS})

    def targets(self) -> dict:
        return {}

    def is_over(self) -> bool:
        return False


# ---------- the table, drawn once and then only filmed ----------

class TableView:
    """One drawing of the table: the three boards exactly as in the real game, their letters and
    (optionally) the players' discs, inside a 'world' that a camera zooms and pans within a
    clipped window. After it is built, only the camera and the squares' contents change, which
    is what lets Flutter animate it."""

    def __init__(self, board_px: float, window: Rect, discs: bool = True, animate: bool = True,
                 look: Look | None = None):
        look = self.look = look or DEFAULT_LOOK
        b = self.board_px = board_px
        self.window = window
        self.turn = 0.0                                              # how far the table is turned
        # A square world centred on the table, big enough for anything on it at any turn.
        width = height = 2 * WORLD_RADIUS * b
        ox, oy = self.origin = (width / 2, height / 2)               # the table centre
        # With a frame, the squares sit inside it; without one, a hairline outline keeps the edge
        # visible where a black starting line meets a dark background.
        self.edge = b * FRAME_SHARE if look.frame else max(1.0, b * 0.005)
        self.cell_px = (b - 2 * self.edge) / BOARD_SIZE
        self.boards: dict[str, ft.Container] = {}
        self.cells: dict[tuple[str, Square], tuple[ft.Container, ft.Container]] = {}
        self.drawn: dict[tuple[str, Square], object] = {}
        self.frames: dict[str, ft.Stack] = {}
        spin = MOTION if animate else None
        for name in BOARD_PLAYERS:
            upright = turn(-BOARD_TURN[name])          # towers stand upright on a turned board
            rows = []
            for r in range(BOARD_SIZE):
                row = []
                for c in range(BOARD_SIZE):
                    holder = ft.Container(width=self.cell_px, height=self.cell_px, alignment=ft.Alignment.CENTER,
                                          rotate=upright, animate_rotation=spin)
                    cell = ft.Container(width=self.cell_px, height=self.cell_px, alignment=ft.Alignment.CENTER,
                                        content=holder)
                    self.cells[(name, (r, c))] = (cell, holder)
                    row.append(cell)
                rows.append(ft.Row(row, spacing=0))
            squares = ft.Column(rows, spacing=0)
            cx, cy = board_centre(name)
            box = ft.Container(width=b, height=b, left=ox + cx * b - b / 2, top=oy + cy * b - b / 2,
                               rotate=turn(BOARD_TURN[name]), animate_opacity=MOTION)
            if look.frame:
                box.border_radius = max(1.0, self.edge * 0.1)
                box.content = self.frames[name] = ft.Stack([
                    self.frame_drawing(name),
                    ft.Container(left=self.edge, top=self.edge, content=squares),
                ], width=b, height=b)
            else:
                box.border = ft.Border.all(self.edge, look.theme.accent)
                box.content = squares
            self.boards[name] = box
        letter = 0.36 * b
        self.letters = {}
        for name in BOARD_PLAYERS:
            lx, ly = letter_spot(name)
            self.letters[name] = ft.Container(width=letter, height=letter, alignment=ft.Alignment.CENTER,
                                              left=ox + lx * b - letter / 2, top=oy + ly * b - letter / 2,
                                              animate_opacity=MOTION, animate_rotation=spin)
        # Each player's disc with their name under it, in one holder centred on the disc, so the
        # pair can turn back upright as one when the table turns.
        d = TOKEN * b
        _, _, name_w, name_h = name_box(1)
        hold_w, hold_h = max(d, name_w * b), d + 2 * (NAME_GAP + name_h) * b
        self.discs, self.labels, self.seats = {}, {}, {}
        for p, (px, py) in (PLAYER_SPOT.items() if discs else ()):
            self.discs[p] = ft.Container(width=d, height=d, border_radius=d / 2, alignment=ft.Alignment.CENTER,
                                         left=(hold_w - d) / 2, top=(hold_h - d) / 2, animate_opacity=MOTION)
            self.labels[p] = ft.Container(width=name_w * b, height=name_h * b, left=(hold_w - name_w * b) / 2,
                                          alignment=ft.Alignment.CENTER, animate_opacity=MOTION)
            self.seats[p] = ft.Container(
                width=hold_w, height=hold_h, left=ox + px * b - hold_w / 2, top=oy + py * b - hold_h / 2,
                animate_rotation=spin, content=ft.Stack([self.discs[p], self.labels[p]], width=hold_w, height=hold_h))
        self.place_names()
        motion = MOTION if animate else None
        layers = list(self.boards.values()) + list(self.letters.values()) + list(self.seats.values())
        # The turntable turns about the table centre; the world around it zooms and pans.
        self.turntable = ft.Container(width=width, height=height, animate_rotation=spin,
                                      content=ft.Stack(layers, width=width, height=height))
        self.world = ft.Container(
            width=width, height=height, animate_position=motion, animate_scale=motion,
            content=ft.Stack([self.turntable], width=width, height=height),
        )
        self.frame = ft.Container(
            left=window.x, top=window.y, width=window.w, height=window.h, clip_behavior=ft.ClipBehavior.HARD_EDGE,
            animate_opacity=MOTION, content=ft.Stack([self.world], width=window.w, height=window.h),
        )

    def look_at(self, cam: Camera) -> None:
        """Show table point (cam.x, cam.y) at the centre of the window, `cam.zoom` pixels per board."""
        b = self.board_px
        k = cam.zoom / b
        ox, oy = self.origin
        self.world.left = self.window.w / 2 - k * (ox + cam.x * b)
        self.world.top = self.window.h / 2 - k * (oy + cam.y * b)
        self.world.scale = ft.Scale(scale=k, alignment=ft.Alignment.TOP_LEFT)

    def frame_drawing(self, name: str) -> cv.Canvas:
        """A board's frame; its A-E / 1-5 labels are drawn upright for the current table turn."""
        return frame_view(self.board_px, self.edge, self.look.frame, BOARD_TURN[name] + self.turn,
                          self.look.coords and self.edge >= 6)

    def place_names(self) -> None:
        """Names under their discs, except the seat at the bottom of the screen: above it."""
        for p, label in self.labels.items():
            hold_h = self.seats[p].height
            label.top = hold_h - label.height if name_below(p, self.turn) else 0

    def set_turn(self, degrees: float) -> None:
        """Turn the whole table (degrees, clockwise) about its centre. Everything that must read
        upright (towers, board letters, discs, names, the frame labels) turns back by as much."""
        if degrees == self.turn:
            return
        self.turn = degrees
        self.turntable.rotate = turn(degrees)
        for (name, _), (_, holder) in self.cells.items():
            holder.rotate = turn(-BOARD_TURN[name] - degrees)
        for box in list(self.letters.values()) + list(self.seats.values()):
            box.rotate = turn(-degrees)
        for name, stack in self.frames.items():
            stack.controls[0] = self.frame_drawing(name)
        self.place_names()

    def refresh(self, s: Session, *, opacity: dict[str, float], glow: set[str], clicks: dict, tap=None,
                interactive: str | set[str] | None = None, marks: float = 1.0, highlights: bool = True,
                names: dict[int, str] | None = None) -> None:
        """`interactive`: the board (or boards) whose squares can be tapped."""
        b, look, theme = self.board_px, self.look, self.look.theme
        targets = s.targets() if highlights else {}
        playing_on = {interactive} if isinstance(interactive, str) else set(interactive or ())
        for name, box in self.boards.items():
            box.opacity = opacity[name]
            # The board never changes size (that would shift the squares); a glow marks a board.
            box.shadow = (ft.BoxShadow(blur_radius=b * 0.12, spread_radius=b * 0.015, color=theme.accent)
                          if name in glow else
                          ft.BoxShadow(blur_radius=b * 0.07, offset=ft.Offset(0, b * 0.02), color=theme.shadow))
            box.on_click = clicks.get(name)
            self.refresh_cells(s, name, targets, tap if name in playing_on else None, highlights)
        for name, label in self.letters.items():
            frozen = s.state.phase == "play" and is_frozen(s.state.boards[name])
            label.content = serif(name, b * 0.16, look.frozen if frozen else theme.accent)
            label.opacity = marks
        pts = scores(s.state)
        for p, box in self.discs.items():
            box.opacity = marks
            style_disc(box, p, str(pts[p]), glow=not s.is_over() and s.to_move == p, look=look)
            box.tooltip = f"{(names or {}).get(p, look.colour_name(p))} · {pts[p]} points"
        for p, label in self.labels.items():
            current = not s.is_over() and s.to_move == p
            label.opacity = marks
            label.content = ft.Text((names or {}).get(p, look.colour_name(p)), size=b * 0.095, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER,
                                    color=theme.accent if current else theme.muted,
                                    weight=ft.FontWeight.BOLD if current else ft.FontWeight.NORMAL)

    def refresh_cells(self, s: Session, name: str, targets: dict, tap, highlights: bool) -> None:
        """Update one board's squares; only squares whose contents changed are redrawn."""
        board, look, theme = s.state.boards[name], self.look, self.look.theme
        size = self.cell_px
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                sq = (r, c)
                cell, holder = self.cells[(name, sq)]
                tower = board[sq]
                ground = (look.colour(board.top).line if r == 0 else look.colour(board.bottom).line
                          if r == BOARD_SIZE - 1 else theme.square)
                cell.bgcolor = ground
                border, dot = ft.Border.all(max(0.3, min(theme.grid_width, size * 0.02)), theme.grid), False
                if highlights and s.selected == (name, sq):
                    border = ft.Border.all(max(2.0, size * 0.07), SELECT)
                elif (name, sq) in targets:
                    if tower is not None:
                        border = ft.Border.all(max(2.0, size * 0.07), CAPTURE)
                    else:
                        dot = look.hints               # the square can still be tapped without the dot
                elif s.last == (name, sq):
                    border = ft.Border.all(max(1.0, size * 0.05), theme.accent)
                cell.border = border
                if self.drawn.get((name, sq)) != (tower, dot):
                    self.drawn[(name, sq)] = (tower, dot)
                    holder.content = (tower_view(tower, size, look, ground) if tower else
                                      ft.Container(width=size * 0.3, height=size * 0.3, bgcolor=SELECT,
                                                   border_radius=size) if dot else None)
                cell.on_click = (lambda e, n=name, q=sq: tap(n, q)) if tap else None


def still_table(width: float, height: float, look: Look, discs: bool = False) -> ft.Stack:
    """The whole table in a box, showing a fixed position: for the home screen and Settings."""
    cam = table_camera(width, height)
    view = TableView(cam.zoom, Rect(0, 0, width, height), discs=discs, animate=False, look=look)
    view.look_at(cam)
    view.refresh(Preview(), opacity={n: 1.0 for n in BOARD_PLAYERS}, glow=set(), clicks={})
    return ft.Stack([view.frame], width=width, height=height)


# ---------- the app ----------

class TalatApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.session: Session | None = None
        self.settings: Settings = load_settings()
        self.look = Look(self.settings)
        self.screen = "start"                       # "start", "game" or "settings"
        self.back_to = "start"                      # where Settings returns to
        self.mode = "solo"
        self.seats = dict(zip(PLAYERS, PRESETS[self.mode][2]))
        self.time_limit = 1.0
        self.delay = self.look.ai_delay
        self.customize = False
        self.names = {p: "" for p in PLAYERS}       # names typed in for human players
        self.paused = False
        self.thinking = False
        self.stage, self.focus = "table", None      # see turn_view()
        self.table_turn = 0.0                       # computer screens: how far the table is turned
        self.scene: ft.Stack | None = None          # built once per game; then only the camera moves
        self.lock = threading.RLock()

        page.title = "Talat"
        page.fonts = {SERIF: "fonts/LibreBaskerville-Italic.ttf"}
        page.padding = 0                            # the backdrop paints to the edges and pads itself
        page.on_resize = lambda e: self.render()
        self.apply_theme()
        self.render()

    # ---------- look ----------

    def apply_theme(self) -> None:
        t = self.look.theme
        self.page.bgcolor = t.bg
        self.page.theme_mode = ft.ThemeMode.LIGHT if t.light else ft.ThemeMode.DARK
        # Scrollbars in the theme's colours: a slim rounded thumb in the accent on a faint track,
        # a little wider while the pointer is over it.
        track = "#14000000" if t.light else "#14FFFFFF"      # #AARRGGBB: a faint shade of the room
        scrollbar = ft.ScrollbarTheme(
            thumb_visibility=True, track_visibility=True, interactive=True, radius=4,
            thickness={ft.ControlState.HOVERED: 10, ft.ControlState.DEFAULT: 6},
            thumb_color={ft.ControlState.HOVERED: t.accent, ft.ControlState.DRAGGED: t.accent,
                         ft.ControlState.DEFAULT: "#99" + t.accent[1:]},
            track_color=track, track_border_color="#00000000", cross_axis_margin=2, main_axis_margin=6)
        scheme = ft.Theme(color_scheme_seed=t.accent, scrollbar_theme=scrollbar,
                          color_scheme=ft.ColorScheme(primary=t.accent, on_primary=self.look.ink))
        self.page.theme = self.page.dark_theme = scheme

    def backdrop(self, content: ft.Control) -> ft.Container:
        """The room: the theme's colour, a little lighter in the middle where the table stands."""
        t = self.look.theme
        return ft.Container(expand=True, padding=PAGE_PAD, content=content, bgcolor=t.bg,
                            gradient=ft.RadialGradient(colors=[t.bg2, t.bg], center=ft.Alignment(0, 0.1), radius=0.9))

    def change(self, **values) -> None:
        """A choice made under Settings: remember it and redraw everything in the new look."""
        for key, value in values.items():
            setattr(self.settings, key, value)
        save_settings(self.settings)
        self.look = Look(self.settings)
        self.delay = self.look.ai_delay
        self.scene = None                           # the game's table is redrawn in the new look
        self.apply_theme()
        self.render()

    def reset_settings(self) -> None:
        defaults = Settings()
        self.change(**{k: getattr(defaults, k) for k in vars(defaults)})

    def open_settings(self) -> None:
        if self.screen != "settings":
            self.back_to = self.screen
        self.screen = "settings"
        self.render()

    def close_settings(self) -> None:
        self.screen = "game" if self.back_to == "game" and self.session else "start"
        self.render()
        self.maybe_run_ai()

    # ---------- screens ----------

    def render(self) -> None:
        with self.lock:
            if self.screen == "settings":
                self.page.controls[:] = [self.backdrop(ft.SafeArea(expand=True, content=self.settings_view()))]
            elif self.session is None:
                self.scene = None
                # SafeArea keeps the content clear of the phone's status bar and notch; the
                # start screen scrolls inside it.
                self.page.controls[:] = [self.backdrop(ft.SafeArea(expand=True, content=self.start_view()))]
            else:
                if self.scene is None or self.scene_size != self.scene_dims():
                    self.build_scene()
                self.refresh_scene()
            self.page.update()

    def size(self) -> tuple[float, float]:
        return (self.page.width or 400), (self.page.height or 800)

    def wide(self) -> bool:
        w, h = self.size()
        return w >= WIDE and w >= h

    def insets(self) -> tuple[float, float]:
        """The phone's status bar and gesture bar (top, bottom), which SafeArea keeps clear."""
        padding = getattr(getattr(self.page, "media", None), "padding", None)
        if padding is None:
            return 0.0, 0.0
        return float(padding.top or 0), float(padding.bottom or 0)

    def icon_button(self, icon, tooltip: str, on_click) -> ft.IconButton:
        return ft.IconButton(icon, icon_color=self.look.theme.accent, tooltip=tooltip, on_click=on_click)

    # ----- start screen -----

    def start_view(self) -> ft.Control:
        t = self.look.theme
        w, h = self.size()
        wide = self.wide()
        width = 440 if wide else min(440, w - 2 * PAGE_PAD)
        # On a computer screen the whole menu fits the window, never scrolling: it shrinks a little
        # on a short window. (A phone keeps sizes readable and scrolls instead.)
        k = max(0.6, min(1.0, (h - 2 * PAGE_PAD) / MENU_HEIGHT)) if wide else 1.0

        def pick_mode(key):
            def handler(e):
                self.mode = key
                self.seats = dict(zip(PLAYERS, PRESETS[key][2]))
                if list(self.seats.values()).count("human") > 1:
                    self.customize = True      # more than one human: show the name fields
                self.render()
            return handler

        def mode_card(key: str) -> ft.Control:
            title, subtitle, _ = PRESETS[key]
            chosen = key == self.mode
            icon = {"solo": ft.Icons.PERSON, "friend": ft.Icons.PEOPLE, "all": ft.Icons.GROUPS,
                    "watch": ft.Icons.VISIBILITY}[key]
            return ft.Container(
                width=width, padding=ft.Padding.symmetric(horizontal=18, vertical=14 * k), border_radius=14,
                bgcolor=self.look.card_on if chosen else t.card,
                border=ft.Border.all(1.5 if chosen else 1, t.accent if chosen else t.line),
                on_click=pick_mode(key),
                content=ft.Row(spacing=16, controls=[
                    ft.Icon(icon, color=t.accent if chosen else t.muted, size=26 * k),
                    ft.Column(spacing=2 * k, tight=True, controls=[
                        ft.Text(title, size=max(14, 17 * k), weight=ft.FontWeight.BOLD, color=t.text),
                        ft.Text(subtitle, size=max(11.5, 13 * k), color=t.muted),
                    ]),
                ]),
            )

        controls: list[ft.Control] = [
            ft.Container(height=12 * k),
            ft.Row([tower_view(Tower(p, Size.L, sh), 46 * k, self.look) for p, sh in ((1, Shape.H), (2, Shape.Q), (3, Shape.T))],
                   alignment=ft.MainAxisAlignment.CENTER, spacing=14 * k),
            ft.Text("Talat", size=76 * k, font_family=SERIF, italic=True, weight=ft.FontWeight.BOLD, color=t.text,
                    text_align=ft.TextAlign.CENTER),
            serif("The Power of Three", 20 * k, t.accent),
            ft.Container(height=14 * k),
            *[mode_card(key) for key in PRESETS],
            ft.TextButton("Hide players" if self.customize else "Customize players",
                          on_click=lambda e: self.toggle_customize(), style=ft.ButtonStyle(color=t.muted)),
        ]
        if self.customize and not wide:             # a computer screen shows the players beside the menu
            controls.append(self.customize_panel(width))
        controls += [
            ft.Container(height=6 * k),
            ft.FilledButton("Play", width=width, height=54 * k, on_click=lambda e: self.start(),
                            style=ft.ButtonStyle(bgcolor=t.accent, color=self.look.ink,
                                                 text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
                                                 shape=ft.RoundedRectangleBorder(radius=14))),
            ft.OutlinedButton("Appearance", icon=ft.Icons.PALETTE_OUTLINED, width=width, height=46 * k,
                              on_click=lambda e: self.open_settings(),
                              style=ft.ButtonStyle(color=t.text, icon_color=t.accent,
                                                   side=ft.BorderSide(1, t.line),
                                                   shape=ft.RoundedRectangleBorder(radius=14))),
            ft.Container(height=12 * k),
        ]
        gear = ft.Row([self.icon_button(ft.Icons.SETTINGS_ROUNDED, "Settings", lambda e: self.open_settings())],
                      alignment=ft.MainAxisAlignment.END)
        if not wide:
            return ft.Column([gear] + controls, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                             width=w - 2 * PAGE_PAD, scroll=ft.ScrollMode.AUTO, expand=True)
        # A computer screen, all on one page: the menu on the left; on the right the table in the
        # chosen look, or, while the players are being customised, who plays which colour.
        room_w, room_h = w - 2 * PAGE_PAD, h - 2 * PAGE_PAD
        menu_w = max(width + 80, min(640, room_w * 0.4))
        menu = ft.Column(controls, spacing=10 * k, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                         width=menu_w, height=room_h, alignment=ft.MainAxisAlignment.CENTER)
        side_w = room_w - menu_w
        if self.customize:
            side = ft.Container(width=side_w, height=room_h, alignment=ft.Alignment.CENTER, content=ft.Container(
                width=width + 40, padding=20, border_radius=18, bgcolor=t.card, border=ft.Border.all(1, t.line),
                content=ft.Column(tight=True, spacing=16, controls=[
                    ft.Row([serif("Players", 28, t.accent),
                            ft.TextButton("Done", on_click=lambda e: self.toggle_customize(),
                                          style=ft.ButtonStyle(color=t.accent))],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.customize_panel(width),
                ])))
        else:
            side = still_table(side_w, room_h, self.look)
        return ft.Stack([
            ft.Container(left=0, top=0, content=menu),
            ft.Container(left=menu_w, top=0, content=side),
            ft.Container(right=0, top=0, content=gear),
        ], width=room_w, height=room_h)

    def toggle_customize(self) -> None:
        self.customize = not self.customize
        self.render()

    def customize_panel(self, width: float) -> ft.Control:
        t = self.look.theme

        def set_seat(p):
            def handler(e):
                self.seats[p] = e.control.value
                self.render()                  # show or hide the name field
            return handler

        def set_name(p):
            def handler(e):
                self.names[p] = e.control.value
            return handler

        def set_time(e):
            self.time_limit = round(e.control.value, 1)
            time_label.value = f"AI thinking time · {self.time_limit:.1f} s"
            time_label.update()

        time_label = ft.Text(f"AI thinking time · {self.time_limit:.1f} s", size=13, color=t.muted)
        rows = []
        for p in PLAYERS:
            human = self.seats[p] == "human"
            room = width - 42                  # beside the disc
            controls = [
                disc(p, 30, look=self.look),
                ft.Dropdown(value=self.seats[p], width=room * 0.48 if human else room, menu_width=room,
                            label=self.look.colour_name(p), border_color=t.line, focused_border_color=t.accent,
                            on_select=set_seat(p),
                            options=[ft.DropdownOption(key=k, text=v) for k, v in SEAT_CHOICES.items()]),
            ]
            if human:                          # a human gets a name (blank: "You" or "Player 2")
                controls.append(ft.TextField(
                    value=self.names[p], label="Name", hint_text=self.default_name(p, self.seats),
                    max_length=12, counter="", width=room * 0.52 - 12, border_color=t.line,
                    focused_border_color=t.accent, capitalization=ft.TextCapitalization.WORDS,
                    on_change=set_name(p)))
            rows.append(ft.Row(spacing=12, controls=controls))
        if any(seat != "human" for seat in self.seats.values()):
            rows += [time_label, ft.Slider(min=0.2, max=3.0, divisions=14, value=self.time_limit, width=width,
                                           active_color=t.accent, on_change=set_time)]
        return ft.Column(rows, spacing=12, width=width)

    # ----- settings -----

    def settings_view(self) -> ft.Control:
        """Every choice about the look, each shown as it will appear, with a live preview."""
        t, s, look = self.look.theme, self.settings, self.look
        w, h = self.size()
        wide = self.wide()
        room_w, room_h = w - 2 * PAGE_PAD, h - 2 * PAGE_PAD
        list_w = min(720, room_w * 0.42) if wide else room_w
        cols = 3 if list_w >= 600 else 2
        inner_w = list_w - 16 - SCROLL_GUTTER         # the tiles stop short of the scrollbar
        tile_w = (inner_w - 8 * (cols - 1)) / cols

        def tile(key: str, value: str, body: list[ft.Control], name: str, tag: str = "", width: float = tile_w):
            chosen = getattr(s, key) == value
            return ft.Container(
                width=width, padding=10, border_radius=12, bgcolor=look.card_on if chosen else t.card,
                border=ft.Border.all(2 if chosen else 1, t.accent if chosen else t.line),
                on_click=lambda e: self.change(**{key: value}), tooltip=name,
                content=ft.Column(spacing=7, tight=True, controls=body + [ft.Row([
                    ft.Text(name, size=13.5, weight=ft.FontWeight.W_600, color=t.text, expand=True, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(tag.upper(), size=9.5, weight=ft.FontWeight.BOLD, color=t.accent) if tag else ft.Container(),
                ], spacing=6)]),
            )

        def strip(colors: list[str]) -> ft.Control:
            return ft.Container(height=18, border_radius=6, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                                border=ft.Border.all(1, "#40808080"),
                                content=ft.Row([ft.Container(bgcolor=c, expand=True) for c in colors], spacing=0))

        def towers_on_board(towers: list[Tower], tile_look: Look) -> ft.Control:
            return ft.Container(bgcolor=t.square, border_radius=6, padding=3, content=ft.Row(
                [tower_view(tw, 30, tile_look, t.square) for tw in towers], spacing=2, tight=True))

        def section(title: str, tiles: list[ft.Control]) -> ft.Control:
            return ft.Column([ft.Text(title.upper(), size=12, weight=ft.FontWeight.W_600, color=t.accent),
                              ft.Row(tiles, wrap=True, spacing=8, run_spacing=8, width=inner_w)], spacing=10)

        def switch(key: str, title: str, sub: str) -> ft.Control:
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=12, bgcolor=t.card,
                border=ft.Border.all(1, t.line), width=inner_w,
                content=ft.Row([ft.Column([ft.Text(title, size=14, color=t.text),
                                           ft.Text(sub, size=12.5, color=t.muted)], spacing=0, expand=True),
                                ft.Switch(value=getattr(s, key), active_color=t.accent,
                                          on_change=lambda e: self.change(**{key: bool(e.control.value)}))]))

        def speed_chip(key: str) -> ft.Control:
            chosen = s.speed == key
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=6), border_radius=10,
                bgcolor=t.accent if chosen else t.card, border=ft.Border.all(1, t.accent if chosen else t.line),
                on_click=lambda e: self.change(speed=key),
                content=ft.Text(SPEEDS[key][0], size=13, color=look.ink if chosen else t.muted,
                                weight=ft.FontWeight.BOLD if chosen else ft.FontWeight.NORMAL))

        themes = [tile("theme", k, [strip([v.bg, v.bg2, v.square, v.frame.wood, v.accent])], v.name, v.tag)
                  for k, v in THEMES.items()]
        pair_w = (inner_w - 8) / 2
        palettes = [tile("palette", k, [towers_on_board([Tower(1, Size.L, Shape.H), Tower(2, Size.L, Shape.Q),
                                                         Tower(3, Size.L, Shape.T)], Look(Settings(**{**vars(s), "palette": k})))],
                         v.name, v.tag, width=pair_w) for k, v in PALETTES.items()]
        styles = [tile("towers", k, [towers_on_board([Tower(1, z, Shape.H) for z in (Size.S, Size.M, Size.L)],
                                                     Look(Settings(**{**vars(s), "towers": k})))],
                       name, tag, width=pair_w) for k, (name, tag) in TOWER_STYLES.items()]
        frames = []
        for k, (name, frame) in FRAMES.items():
            colors = (t.frame if k == "theme" else frame)
            frames.append(tile("frame", k, [strip([colors.wood, colors.rim, colors.inlay] if colors else [t.square])],
                               name))
        options = ft.Column([
            section("Theme", themes),
            section("Tower colours", palettes),
            section("Tower size borders", styles),
            section("Board frame", frames),
            ft.Column([ft.Text("BOARD", size=12, weight=ft.FontWeight.W_600, color=t.accent),
                       switch("coords", "Show A–E and 1–5", "Square names on the frame"),
                       switch("hints", "Show where a tower can go", "Blue dots on free squares"),
                       ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=12,
                                    bgcolor=t.card, border=ft.Border.all(1, t.line), width=inner_w,
                                    content=ft.Row([ft.Column([ft.Text("AI speed", size=14, color=t.text),
                                                               ft.Text("Pause between AI moves", size=12.5, color=t.muted)],
                                                              spacing=0, expand=True),
                                                    ft.Row([speed_chip(k) for k in SPEEDS], spacing=6)]))],
                      spacing=10),
            ft.TextButton("Reset to defaults", on_click=lambda e: self.reset_settings(),
                          style=ft.ButtonStyle(color=t.muted)),
        ], spacing=22, scroll=ft.ScrollMode.AUTO, expand=True,
            width=inner_w + SCROLL_GUTTER)             # the scrollbar runs in the empty lane right of the tiles
        header = ft.Row([self.icon_button(ft.Icons.ARROW_BACK_ROUNDED, "Back", lambda e: self.close_settings()),
                         ft.Text("Settings", size=24 if wide else 20, weight=ft.FontWeight.BOLD, color=t.text)],
                        spacing=6, height=TOP_BAR)
        preview_box = lambda pw, ph: ft.Container(
            width=pw, height=ph, border_radius=14, border=ft.Border.all(1, t.line), clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Stack([still_table(pw, ph, look, discs=pw > 500),
                              ft.Container(left=12, top=8, content=ft.Text("PREVIEW", size=11, color=t.muted))]))
        if wide:
            return ft.Row([
                ft.Column([header, ft.Container(content=options, padding=ft.Padding.only(left=8), expand=True)],
                          width=list_w, height=room_h, spacing=4),
                preview_box(room_w - list_w - 24, room_h),
            ], spacing=24, vertical_alignment=ft.CrossAxisAlignment.START)
        return ft.Column([header, preview_box(room_w, 200), ft.Container(content=options, expand=True)],
                         spacing=10, expand=True)

    # ----- the game scene -----

    def bottom_height(self) -> float:
        """Room under the table: the status line, plus the tower tray while a human still has
        towers to place. When setup ends the table is rebuilt once to use that room too."""
        s = self.session
        placing = s is not None and s.state.phase == "setup" and any(a is None for a in s.agents.values())
        return 140.0 if placing else 52.0

    def scene_dims(self) -> tuple[float, float]:
        """The scene gets every pixel between the top bar and the status line."""
        w, h = self.size()
        top, bottom = self.insets()
        free = h - 2 * PAGE_PAD - top - bottom - TOP_BAR - self.bottom_height() - 2 * GAP
        return w - 2 * PAGE_PAD, max(240.0, free)

    def build_scene(self) -> None:
        """Create the game screen once per game (and on resize or a new look): the main view of
        the table, and, on a tall phone, the players panel / mini table above it."""
        s = self.session
        width, height = self.scene_size = self.scene_dims()
        self.main_rect, self.side_rect = main, side = regions(width, height)
        humans = [p for p in PLAYERS if s.agents[p] is None]
        # The main table is drawn once at the largest zoom its camera will use, then scaled down.
        if self.whole_table():          # computer screen: the whole table, turned to each human in turn
            zoom = max([table_camera(main.w, main.h).zoom] +
                       [table_camera(main.w, main.h, facing_turn(p)).zoom for p in humans])
        else:                           # phone: the camera zooms in on a board
            zoom = max([table_camera(main.w, main.h).zoom] +
                       [focus_camera(n, main.w, main.h).zoom for p in humans for n in boards_of(p)])
        self.main = TableView(zoom, main, look=self.look)
        self.main.set_turn(self.table_turn)
        self.main.look_at(table_camera(main.w, main.h, self.table_turn))   # every game opens on the whole table
        layers: list[ft.Control] = []
        self.mini, self.panel = None, None
        if side is not None:
            self.panel = ft.Container(left=side.x, top=side.y, width=side.w, height=side.h,
                                      alignment=ft.Alignment.CENTER, animate_opacity=MOTION)
            layers.append(self.panel)
            if humans:               # the mini table only appears while a human zooms in on a board
                mini_cam = table_camera(side.w, side.h)
                self.mini = TableView(mini_cam.zoom, side, discs=False, animate=False, look=self.look)
                self.mini.look_at(mini_cam)
                self.mini.frame.opacity = 0.0
                layers.append(self.mini.frame)
        layers.append(self.main.frame)
        self.scene = ft.Stack(layers, width=width, height=height)
        self.top = ft.Container(height=TOP_BAR)
        self.bottom = ft.Container(height=self.bottom_height(), width=width, alignment=ft.Alignment.TOP_CENTER)
        self.page.controls[:] = [self.backdrop(ft.SafeArea(expand=True, content=ft.Column(
            [self.top, ft.Row([self.scene], alignment=ft.MainAxisAlignment.CENTER), self.bottom],
            spacing=GAP, expand=True)))]

    def refresh_scene(self) -> None:
        s = self.session
        main = self.main_rect
        playable = s.playable_boards()               # empty unless a human is to move
        if self.whole_table():
            # Every board stays in view; the table turns to the human whose turn it is, and they
            # play straight on it: tap a tower on either of their boards, then a highlighted square.
            self.main.set_turn(self.table_turn)
            self.main.look_at(table_camera(main.w, main.h, self.table_turn))
            frozen = {n: s.state.phase == "play" and is_frozen(s.state.boards[n]) for n in BOARD_PLAYERS}
            self.main.refresh(
                s, opacity={n: 0.4 if frozen[n] else 1.0 for n in BOARD_PLAYERS}, glow=set(playable), clicks={},
                tap=self.tap_square, interactive=set(playable), names={p: self.display_name(p) for p in PLAYERS},
            )
            self.top.content = self.top_bar()
            self.bottom.content = self.bottom_bar()
            return
        self.main.look_at(camera(self.stage, s.to_move, self.focus, main.w, main.h))
        zoomed = self.stage == "focus"
        frozen = {n: s.state.phase == "play" and is_frozen(s.state.boards[n]) for n in BOARD_PLAYERS}

        def main_opacity(n: str) -> float:
            if frozen[n]:
                return 0.4
            if self.stage == "pair":
                return 1.0 if n in playable else 0.55
            if zoomed:
                return 1.0 if n == self.focus else 0.75 if n in playable else 0.45
            return 1.0

        clicks = {n: (lambda e, n=n: self.focus_board(n)) for n in playable if not (zoomed and n == self.focus)}
        self.main.refresh(
            s, opacity={n: main_opacity(n) for n in BOARD_PLAYERS},
            glow=set() if zoomed else set(playable), clicks=clicks,
            tap=self.tap_square, interactive=self.focus if zoomed else None,
            # zoomed in, the table's letters, discs and names would only peek in cut off at the edges
            marks=0.0 if zoomed else 1.0, names={p: self.display_name(p) for p in PLAYERS},
        )
        if self.mini is not None:
            self.mini.frame.opacity = 1.0 if zoomed else 0.0
            self.mini.refresh(       # faded like the main view, so the board you're on stands out
                s, opacity={n: main_opacity(n) for n in BOARD_PLAYERS},
                glow={self.focus} if zoomed else set(), clicks=clicks if zoomed else {}, highlights=False,
            )
        if self.panel is not None:
            self.panel.opacity = 0.0 if zoomed and self.mini is not None else 1.0
            self.panel.content = self.players_panel()
        self.top.content = self.top_bar()
        self.bottom.content = self.bottom_bar()

    def tap_square(self, name: str, square: Square) -> None:
        s = self.session
        self.human(lambda: s.tap(name, square))

    @staticmethod
    def default_name(player: int, seats: dict[int, str]) -> str:
        """'You' when you're the only human, 'Player 1/2/3' when several humans share the phone."""
        humans = [p for p in PLAYERS if seats[p] == "human"]
        return "You" if humans == [player] else f"Player {humans.index(player) + 1}"

    def display_name(self, player: int) -> str:
        """A human's typed-in name (or the default); an AI's level, e.g. 'Hard AI'."""
        seats = self.session.seats if self.session else self.seats
        if seats[player] != "human":
            return seat_name(seats[player])
        return self.names[player].strip() or self.default_name(player, seats)

    def turn_of(self, player: int) -> str:
        name = self.display_name(player)
        return "Your turn" if name == "You" else f"{name}'s turn"

    def players_panel(self) -> ft.Control:
        """Each player: colour, name, who plays it, and the towers they have captured (tall phones)."""
        s, t = self.session, self.look.theme
        side = self.side_rect
        rows = []
        for p in PLAYERS:
            current = not s.is_over() and s.to_move == p
            taken = sorted(s.state.captured[p], key=lambda tw: tw.rank, reverse=True)
            trophies = ([tower_view(tw, 18, self.look, t.card) for tw in taken] if taken
                        else [ft.Text("no captures yet", size=12, color=self.look.frozen)])
            rows.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=12, bgcolor=t.card,
                border=ft.Border.all(1.5 if current else 1, t.accent if current else t.line),
                content=ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    disc(p, 26, glow=current, look=self.look),
                    ft.Column([ft.Text(self.display_name(p), size=14, weight=ft.FontWeight.BOLD, max_lines=1,
                                       overflow=ft.TextOverflow.ELLIPSIS, color=t.text),
                               ft.Text(self.look.colour_name(p), size=11, color=t.muted)],
                              spacing=0, tight=True, width=96),
                    ft.Row(trophies, wrap=True, spacing=2, run_spacing=2, expand=True),
                ]),
            ))
        return ft.Column(rows, spacing=8, width=min(side.w, 440), tight=True)

    def top_bar(self) -> ft.Control:
        s, t = self.session, self.look.theme
        pts = scores(s.state)
        score_discs = ft.Row([disc(p, 30, str(pts[p]), glow=not s.is_over() and s.to_move == p, look=self.look)
                              for p in PLAYERS], spacing=8)
        for p, d in zip(PLAYERS, score_discs.controls):
            d.tooltip = f"{self.display_name(p)} ({self.look.colour_name(p)})"
        buttons = []
        if s.is_human_turn() and self.whole_table():
            pass                                    # every board is in view already: nothing to switch
        elif s.is_human_turn():
            if self.stage == "focus":
                buttons.append(self.icon_button(ft.Icons.ARROW_BACK_ROUNDED, "Both boards", lambda e: self.show_pair()))
            elif self.stage == "pair":
                buttons.append(self.icon_button(ft.Icons.CHANGE_HISTORY_ROUNDED, "Whole table",
                                                lambda e: self.show_table()))
            else:
                buttons.append(self.icon_button(ft.Icons.GRID_VIEW_ROUNDED, "Your boards", lambda e: self.show_pair()))
        elif s.has_ai() and not s.is_over():
            buttons.append(self.icon_button(ft.Icons.PLAY_ARROW_ROUNDED if self.paused else ft.Icons.PAUSE_ROUNDED,
                                            "Resume" if self.paused else "Pause", lambda e: self.toggle_pause()))
        buttons.append(self.icon_button(ft.Icons.SETTINGS_ROUNDED, "Settings", lambda e: self.open_settings()))
        buttons.append(self.icon_button(ft.Icons.HOME_ROUNDED, "Menu", lambda e: self.new_game()))
        return ft.Row([serif("Talat", 28, t.accent), score_discs, ft.Row(buttons, spacing=0)],
                      alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def bottom_bar(self) -> ft.Control:
        items = [self.status_row()]
        owner = self.tray_owner()
        if owner is not None:
            items.append(self.hand_tray(owner))
        return ft.Column(items, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def tray_owner(self) -> int | None:
        """Whose towers the tray shows during setup: the human to move; while an AI places, the
        only human's (dimmed), so the tray doesn't blink away between turns."""
        s = self.session
        if s.state.phase != "setup":
            return None
        if s.is_human_turn():
            return s.to_move
        humans = [p for p in PLAYERS if s.agents[p] is None]
        return humans[0] if len(humans) == 1 else None

    def status_text(self) -> str:
        s = self.session
        if s.is_over():
            return f"Game over · {end_reason(s.state)}"
        p = s.to_move
        name, colour = self.display_name(p), self.look.colour_name(p)
        if s.is_human_turn() and self.whole_table():     # played straight on the table
            if s.state.phase == "setup":
                return f"{self.turn_of(p)} · place a tower on your starting line"
            if s.selected is None:
                return f"{self.turn_of(p)} · tap one of your towers"
            return f"{self.turn_of(p)} · tap a highlighted square"
        if s.is_human_turn():
            if self.stage == "table":
                return f"{self.turn_of(p)} · tap one of your boards"
            if self.stage == "pair":
                return f"{self.turn_of(p)} · choose a board"
            # zoomed in: name the board, or, when the phone is passed around, whose turn it is
            # (the board is the big one, and glows on the mini table)
            where = f"Board {self.focus}" if name == "You" else name
            if s.state.phase == "setup":
                return f"{where} · place a tower on your starting line"
            if s.selected is None:
                return f"{where} · tap one of your towers"
            return f"{where} · tap a highlighted square"
        if self.paused:
            return f"Paused · {name} ({colour}) is next"
        return f"{name} ({colour}) is thinking…"

    def status_row(self) -> ft.Control:
        s, t = self.session, self.look.theme
        busy = not s.is_over() and not s.is_human_turn() and not self.paused
        items = [ft.Text(self.status_text(), size=15, color=t.text if s.is_human_turn() else t.muted,
                         weight=ft.FontWeight.W_600 if s.is_human_turn() else ft.FontWeight.NORMAL)]
        if busy:
            items.insert(0, ft.ProgressRing(width=14, height=14, stroke_width=2, color=t.accent))
        if s.must_pass():          # rare, so it sits in the status line instead of taking room
            items.append(ft.FilledButton("No moves: pass", height=36, on_click=lambda e: self.human(s.pass_turn),
                                         style=ft.ButtonStyle(bgcolor=t.accent, color=self.look.ink)))
        return ft.Row(items, alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True)

    def hand_tray(self, player: int) -> ft.Control:
        s, t = self.session, self.look.theme
        active = s.is_human_turn() and s.to_move == player
        current = s.setup_tower() if active else None

        def pick(tower):
            return lambda e: self.human(lambda: s.choose_tower(tower))

        towers = [
            ft.Container(
                width=44, height=44, bgcolor=t.square, border_radius=8, on_click=pick(tw) if active else None,
                border=ft.Border.all(3 if tw == current else 1, t.accent if tw == current else t.grid),
                content=tower_view(tw, 44, self.look, t.square),
            )
            for tw in sorted(s.state.hands[player], key=lambda tw: tw.rank, reverse=True)
        ]
        return ft.Row(towers, wrap=True, spacing=6, run_spacing=6, alignment=ft.MainAxisAlignment.CENTER,
                      opacity=1.0 if active else 0.45)

    # ---------- stages ----------

    def whole_table(self) -> bool:
        """On a computer screen every board stays in view and players play on the whole table."""
        return self.wide()

    def turn_view(self) -> None:
        """Choose the view for whoever moves next. On a computer screen: the whole table, turned
        so a human to move sits at the bottom (it holds still while the AIs move). On a phone:
        a human gets their two boards, otherwise the table."""
        s = self.session
        human = s is not None and s.is_human_turn()
        if self.whole_table():
            self.stage, self.focus = "table", None
            if human:
                self.table_turn = nearest_turn(self.table_turn, facing_turn(s.to_move))
            return
        self.stage, self.focus = ("pair" if human else "table"), None

    def focus_board(self, name: str) -> None:
        s = self.session
        if s is not None and name in s.playable_boards() and not self.whole_table():
            self.stage, self.focus = "focus", name
            s.selected = None
            self.render()

    def show_pair(self) -> None:
        self.stage, self.focus = ("table" if self.whole_table() else "pair"), None
        if self.session:
            self.session.selected = None
        self.render()

    def show_table(self) -> None:
        self.stage, self.focus = "table", None
        self.render()

    # ---------- flow ----------

    def start(self) -> None:
        self.session = Session(self.seats, time_limit=self.time_limit)
        self.screen = "game"
        self.paused = False
        self.scene = None                 # the game opens on the whole table, then the camera moves in
        humans = [p for p in PLAYERS if self.seats[p] == "human"]
        # On a computer screen the table starts out facing the first human (it never turns in Watch).
        self.table_turn = facing_turn(humans[0]) if humans and self.whole_table() else 0.0
        self.turn_view()
        self.render()
        self.maybe_run_ai()

    def new_game(self) -> None:
        self.session = None      # any AI move still being computed for the old game is dropped
        self.screen = "start"
        self.thinking = False
        self.stage, self.focus = "table", None
        self.render()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.render()
        self.maybe_run_ai()

    def human(self, action) -> None:
        """Run a human's tap or button press, then let the AIs continue."""
        with self.lock:
            s = self.session
            if s is None or not s.is_human_turn():
                return
            before = len(s.log)
            action()
            if len(s.log) != before:      # a move was played: show the next player's view
                self.turn_view()
        self.after_move()

    def after_move(self) -> None:
        self.render()
        if self.session and self.session.is_over():
            self.show_result()
        else:
            self.maybe_run_ai()

    def maybe_run_ai(self) -> None:
        s = self.session
        if (s is None or s.is_over() or s.is_human_turn() or self.paused or self.thinking
                or self.screen == "settings"):       # the game waits while the player is in Settings
            return
        self.thinking = True
        self.page.run_thread(self.ai_turn, s)

    def ai_turn(self, s: Session) -> None:
        started = time.perf_counter()
        try:
            action = s.think()
        except Exception as exc:          # show the problem instead of freezing silently
            self.thinking = False
            self.page.show_dialog(ft.AlertDialog(title=ft.Text("AI error"), content=ft.Text(str(exc))))
            return
        wait = self.delay * (0.25 if s.state.phase == "setup" else 1.0)
        if self.delay:      # let the boards finish gliding before the next move changes the scene
            wait = max(wait, MOTION_SECONDS + 0.15)
        time.sleep(max(0.0, wait - (time.perf_counter() - started)))
        with self.lock:
            self.thinking = False
            if s is not self.session:     # a new game was started meanwhile
                return
            s.play(action)
            self.turn_view()
        self.after_move()

    def show_result(self) -> None:
        s, t = self.session, self.look.theme
        pts = scores(s.state)
        win = winners(s.state)
        if len(win) > 1:
            title = "Shared win"
        else:
            name = self.display_name(win[0])
            title = "You win" if name == "You" else f"{name} wins"
        rows = [
            ft.Row(spacing=12, controls=[
                disc(p, 30, look=self.look),
                ft.Column([ft.Text(self.display_name(p), size=15, weight=ft.FontWeight.BOLD, max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS, color=t.text),
                           ft.Text(self.look.colour_name(p), size=12, color=t.muted)],
                          spacing=0, tight=True, width=160),
                ft.Text(f"{pts[p]}", size=20, weight=ft.FontWeight.BOLD, color=t.accent if p in win else t.text),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for p in sorted(PLAYERS, key=lambda p: -pts[p])
        ]
        reason = end_reason(s.state)

        def close(e):
            self.page.pop_dialog()

        def again(e):
            self.page.pop_dialog()
            self.start()

        def menu(e):
            self.page.pop_dialog()
            self.new_game()

        quiet = ft.ButtonStyle(color=t.text, side=ft.BorderSide(1, t.line), shape=ft.RoundedRectangleBorder(radius=12))
        self.page.show_dialog(ft.AlertDialog(
            modal=True, bgcolor=t.card, shape=ft.RoundedRectangleBorder(radius=18), title=serif(title, 30, t.accent),
            content=ft.Column(([ft.Text(reason[0].upper() + reason[1:], size=13, color=t.muted)] if reason else [])
                              + rows, tight=True, spacing=10, width=260),
            actions=[ft.OutlinedButton("See the board", on_click=close, style=quiet),
                     ft.OutlinedButton("Menu", on_click=menu, style=quiet),
                     ft.FilledButton("Play again", on_click=again,
                                     style=ft.ButtonStyle(bgcolor=t.accent, color=self.look.ink,
                                                          shape=ft.RoundedRectangleBorder(radius=12)))],
            actions_alignment=ft.MainAxisAlignment.END,
        ))


def main(page: ft.Page) -> None:
    TalatApp(page)


if __name__ == "__main__":
    ft.run(main)
