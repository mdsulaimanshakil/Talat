"""TALAT app (Flet): desktop, web and phone.

    flet run                 # desktop window (uses main.py and the assets/ folder)
    flet run --android       # on an Android phone, via the Flet app
    flet build apk           # installable Android app

The boards sit on a table exactly like the real game and never move or turn;
a camera zooms and pans over the table (see talat/scene.py):
- table: the whole table, while the AIs play;
- pair:  on a human's turn the camera closes in on their two boards, which glow;
- focus: the chosen board fills the screen, its neighbours still around it.
After a move the camera glides back to the whole table. Where the screen has room
beside the table (above it on a phone) there's a players panel, and while zoomed
in a mini table keeps all three boards in view.
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
    BOARD_PLAYERS, BOARD_SIZE, PLAYER_NAMES, PLAYERS, Shape, Size, Square, Tower, boards_of, end_reason,
    is_frozen, scores, winners,
)
from talat.scene import (
    BOARD_TURN, PLAYER_SPOT, TABLE_ABOVE, TABLE_BELOW, TABLE_W, TOKEN, Camera, Rect, board_centre, camera,
    focus_camera, letter_spot, name_box, regions, table_camera,
)
from talat.session import PRESETS, SEAT_CHOICES, Session, seat_name

# ---------- look ----------
BG, CARD, GOLD, BEIGE, GRID = "#0A0A0A", "#161616", "#C9973A", "#EBD5AE", "#8C6A2E"
TEXT, MUTED = "#FFFFFF", "#9A9A9A"
SELECT, CAPTURE = "#3D7BE0", "#E53935"
TOWER_FILL = {1: "#F4F4F0", 2: "#141414", 3: "#9E9E9E"}
TOWER_EDGE = {1: "#1A1A1A", 2: "#FFFFFF", 3: "#1A1A1A"}
TOWER_TOP = {1: "#1A1A1A", 2: "#FFFFFF", 3: "#FFFFFF"}      # outline of the hollow top
LINE_FILL = {1: "#F4F4F0", 2: "#141414", 3: "#CFCFCF"}      # starting-line squares
SIZE_SCALE = {Size.L: 0.92, Size.M: 0.72, Size.S: 0.52}
SERIF = "Talat Serif"   # Libre Baskerville Italic, bundled in assets/fonts (OFL licence)
AI_DELAY = 0.5          # pause between AI moves, so people can follow
MOTION_SECONDS = 0.45
MOTION = ft.Animation(int(MOTION_SECONDS * 1000), ft.AnimationCurve.EASE_IN_OUT)   # every move between layouts
TOP_BAR = 56
PAGE_PAD = 8            # space around the whole screen
GAP = 8                 # between the top bar, the table and the status line


# ---------- drawing towers ----------

def shape_points(shape: Shape, cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    if shape == Shape.H:
        return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    if shape == Shape.Q:
        h = r * 0.78
        return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    cy += r * 0.15                                  # a triangle looks centred when nudged down
    return [(cx, cy - r), (cx + r * 0.95, cy + r * 0.62), (cx - r * 0.95, cy + r * 0.62)]


def polygon(points, color: str, stroke: float | None = None) -> cv.Path:
    (x0, y0), *rest = points
    elements = [cv.Path.MoveTo(x=x0, y=y0)] + [cv.Path.LineTo(x=x, y=y) for x, y in rest] + [cv.Path.Close()]
    style = ft.PaintingStyle.STROKE if stroke else ft.PaintingStyle.FILL
    return cv.Path(elements, paint=ft.Paint(color=color, style=style, stroke_width=stroke or 0))


def tower_view(tower: Tower, size: float) -> cv.Canvas:
    """A tower seen from above, as in the rule sheet: solid body, hollow top."""
    c = size / 2
    r = c * SIZE_SCALE[tower.size]
    outer = shape_points(tower.shape, c, c, r)
    inner = shape_points(tower.shape, c, c, r * 0.48)
    stroke = max(1.0, size / 32)
    shapes = [polygon(outer, TOWER_FILL[tower.owner]), polygon(outer, TOWER_EDGE[tower.owner], stroke * 1.3),
              polygon(inner, TOWER_TOP[tower.owner], stroke)]
    return cv.Canvas(shapes=shapes, width=size, height=size)


def disc(player: int, size: float, label: str = "", glow: bool = False) -> ft.Container:
    box = ft.Container(width=size, height=size, border_radius=size / 2, bgcolor=TOWER_FILL[player],
                       alignment=ft.Alignment.CENTER)
    style_disc(box, player, label, glow)
    return box


def style_disc(box: ft.Container, player: int, label: str, glow: bool) -> None:
    size = box.width
    box.border = ft.Border.all(3 if glow else 1.5, GOLD)
    box.shadow = ft.BoxShadow(blur_radius=size * 0.6, spread_radius=1, color=GOLD) if glow else None
    box.content = ft.Text(label, size=size * 0.36, weight=ft.FontWeight.BOLD,
                          color=TEXT if player == 2 else "#1A1A1A") if label else None


def serif(text: str, size: float, color: str = GOLD) -> ft.Text:
    return ft.Text(text, size=size, color=color, font_family=SERIF, italic=True, weight=ft.FontWeight.BOLD)


def turn(degrees: float) -> ft.Rotate:
    return ft.Rotate(angle=math.radians(degrees), alignment=ft.Alignment.CENTER)


# ---------- the table, drawn once and then only filmed ----------

class TableView:
    """One drawing of the table: the three boards exactly as in the real game, their letters and
    (optionally) the players' discs, inside a 'world' that a camera zooms and pans within a
    clipped window. After it is built, only the camera and the squares' contents change, which
    is what lets Flutter animate it."""

    def __init__(self, board_px: float, window: Rect, discs: bool = True, animate: bool = True):
        b = self.board_px = board_px
        self.window = window
        width, height = TABLE_W * b, (TABLE_ABOVE + TABLE_BELOW) * b
        ox, oy = self.origin = (width / 2, TABLE_ABOVE * b)          # the table centre
        # No frame around a board: its squares get the whole width. A hairline outline keeps the
        # edge visible where a black starting line meets the black background.
        self.edge = max(1.0, b * 0.005)
        self.cell_px = (b - 2 * self.edge) / BOARD_SIZE
        self.boards: dict[str, ft.Container] = {}
        self.cells: dict[tuple[str, Square], tuple[ft.Container, ft.Container]] = {}
        self.drawn: dict[tuple[str, Square], object] = {}
        for name in BOARD_PLAYERS:
            upright = turn(-BOARD_TURN[name])          # towers stand upright on a turned board
            rows = []
            for r in range(BOARD_SIZE):
                row = []
                for c in range(BOARD_SIZE):
                    holder = ft.Container(width=self.cell_px, height=self.cell_px, alignment=ft.Alignment.CENTER,
                                          rotate=upright)
                    cell = ft.Container(width=self.cell_px, height=self.cell_px, alignment=ft.Alignment.CENTER,
                                        content=holder)
                    self.cells[(name, (r, c))] = (cell, holder)
                    row.append(cell)
                rows.append(ft.Row(row, spacing=0))
            cx, cy = board_centre(name)
            self.boards[name] = ft.Container(
                width=b, height=b, border=ft.Border.all(self.edge, GOLD), left=ox + cx * b - b / 2,
                top=oy + cy * b - b / 2, rotate=turn(BOARD_TURN[name]), content=ft.Column(rows, spacing=0),
                animate_opacity=MOTION,
            )
        letter = 0.36 * b
        self.letters = {}
        for name in BOARD_PLAYERS:
            lx, ly = letter_spot(name)
            self.letters[name] = ft.Container(width=letter, height=letter, alignment=ft.Alignment.CENTER,
                                              left=ox + lx * b - letter / 2, top=oy + ly * b - letter / 2,
                                              animate_opacity=MOTION)
        d = TOKEN * b
        self.discs = {
            p: ft.Container(width=d, height=d, border_radius=d / 2, bgcolor=TOWER_FILL[p],
                            alignment=ft.Alignment.CENTER, left=ox + px * b - d / 2, top=oy + py * b - d / 2,
                            animate_opacity=MOTION)
            for p, (px, py) in PLAYER_SPOT.items()
        } if discs else {}
        self.labels: dict[int, ft.Container] = {}       # each player's name, under their disc
        for p in (PLAYER_SPOT if discs else ()):
            x, y, w, h = name_box(p)
            self.labels[p] = ft.Container(width=w * b, height=h * b, left=ox + (x - w / 2) * b,
                                         top=oy + (y - h / 2) * b, alignment=ft.Alignment.CENTER,
                                         animate_opacity=MOTION)
        motion = MOTION if animate else None
        layers = (list(self.boards.values()) + list(self.letters.values()) + list(self.discs.values())
                  + list(self.labels.values()))
        self.world = ft.Container(
            width=width, height=height, animate_position=motion, animate_scale=motion,
            content=ft.Stack(layers, width=width, height=height),
        )
        self.frame = ft.Container(
            left=window.x, top=window.y, width=window.w, height=window.h, clip_behavior=ft.ClipBehavior.HARD_EDGE,
            animate_opacity=MOTION, content=ft.Stack([self.world], width=window.w, height=window.h),
        )

    def look(self, cam: Camera) -> None:
        """Show table point (cam.x, cam.y) at the centre of the window, `cam.zoom` pixels per board."""
        b = self.board_px
        k = cam.zoom / b
        ox, oy = self.origin
        self.world.left = self.window.w / 2 - k * (ox + cam.x * b)
        self.world.top = self.window.h / 2 - k * (oy + cam.y * b)
        self.world.scale = ft.Scale(scale=k, alignment=ft.Alignment.TOP_LEFT)

    def refresh(self, s: Session, *, opacity: dict[str, float], glow: set[str], clicks: dict, tap=None,
                interactive: str | None = None, marks: float = 1.0, highlights: bool = True,
                names: dict[int, str] | None = None) -> None:
        b = self.board_px
        targets = s.targets() if highlights else {}
        for name, box in self.boards.items():
            box.opacity = opacity[name]
            # The outline never changes width (that would shift the squares); a glow marks a board.
            box.shadow = (ft.BoxShadow(blur_radius=b * 0.12, spread_radius=b * 0.015, color=GOLD) if name in glow
                          else ft.BoxShadow(blur_radius=b * 0.06, color="#000000"))
            box.on_click = clicks.get(name)
            self.refresh_cells(s, name, targets, tap if name == interactive else None, highlights)
        for name, label in self.letters.items():
            frozen = s.state.phase == "play" and is_frozen(s.state.boards[name])
            label.content = serif(name, b * 0.2, "#5A5A5A" if frozen else GOLD)
            label.opacity = marks
        pts = scores(s.state)
        for p, box in self.discs.items():
            box.opacity = marks
            style_disc(box, p, str(pts[p]), glow=not s.is_over() and s.to_move == p)
            box.tooltip = f"{(names or {}).get(p, PLAYER_NAMES[p])} · {pts[p]} points"
        for p, label in self.labels.items():
            current = not s.is_over() and s.to_move == p
            label.opacity = marks
            label.content = ft.Text((names or {}).get(p, PLAYER_NAMES[p]), size=b * 0.095, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER,
                                    color=GOLD if current else MUTED,
                                    weight=ft.FontWeight.BOLD if current else ft.FontWeight.NORMAL)

    def refresh_cells(self, s: Session, name: str, targets: dict, tap, highlights: bool) -> None:
        """Update one board's squares; only squares whose contents changed are redrawn."""
        board = s.state.boards[name]
        size = self.cell_px
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                sq = (r, c)
                cell, holder = self.cells[(name, sq)]
                tower = board[sq]
                cell.bgcolor = (LINE_FILL[board.top] if r == 0 else LINE_FILL[board.bottom]
                                if r == BOARD_SIZE - 1 else BEIGE)
                border, dot = ft.Border.all(max(0.3, min(0.5, size * 0.02)), GRID), False
                if highlights and s.selected == (name, sq):
                    border = ft.Border.all(max(2.0, size * 0.07), SELECT)
                elif (name, sq) in targets:
                    if tower is not None:
                        border = ft.Border.all(max(2.0, size * 0.07), CAPTURE)
                    else:
                        dot = True
                elif s.last == (name, sq):
                    border = ft.Border.all(max(1.0, size * 0.05), GOLD)
                cell.border = border
                if self.drawn.get((name, sq)) != (tower, dot):
                    self.drawn[(name, sq)] = (tower, dot)
                    holder.content = (tower_view(tower, size) if tower else
                                      ft.Container(width=size * 0.3, height=size * 0.3, bgcolor=SELECT,
                                                   border_radius=size) if dot else None)
                cell.on_click = (lambda e, n=name, q=sq: tap(n, q)) if tap else None


# ---------- the app ----------

class TalatApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.session: Session | None = None
        self.mode = "solo"
        self.seats = dict(zip(PLAYERS, PRESETS[self.mode][2]))
        self.time_limit = 1.0
        self.delay = AI_DELAY
        self.customize = False
        self.names = {p: "" for p in PLAYERS}       # names typed in for human players
        self.paused = False
        self.thinking = False
        self.stage, self.focus = "table", None      # see turn_view()
        self.scene: ft.Stack | None = None          # built once per game; then only the camera moves
        self.lock = threading.RLock()

        page.title = "Talat"
        page.fonts = {SERIF: "fonts/LibreBaskerville-Italic.ttf"}
        page.bgcolor = BG
        page.theme_mode = ft.ThemeMode.DARK
        page.dark_theme = ft.Theme(color_scheme_seed=GOLD, color_scheme=ft.ColorScheme(primary=GOLD, on_primary=BG))
        page.padding = PAGE_PAD
        page.on_resize = lambda e: self.render()
        self.render()

    # ---------- screens ----------

    def render(self) -> None:
        with self.lock:
            if self.session is None:
                self.scene = None
                # SafeArea keeps the content clear of the phone's status bar and notch; the
                # start screen scrolls inside it.
                self.page.controls[:] = [ft.SafeArea(expand=True, content=self.start_view())]
            else:
                if self.scene is None or self.scene_size != self.scene_dims():
                    self.build_scene()
                self.refresh_scene()
            self.page.update()

    def size(self) -> tuple[float, float]:
        return (self.page.width or 400), (self.page.height or 800)

    def insets(self) -> tuple[float, float]:
        """The phone's status bar and gesture bar (top, bottom), which SafeArea keeps clear."""
        padding = getattr(getattr(self.page, "media", None), "padding", None)
        if padding is None:
            return 0.0, 0.0
        return float(padding.top or 0), float(padding.bottom or 0)

    # ----- start screen -----

    def start_view(self) -> ft.Control:
        width = min(440, self.size()[0] - 2 * PAGE_PAD)

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
                width=width, padding=ft.Padding.symmetric(horizontal=18, vertical=14), border_radius=14,
                bgcolor="#1B1712" if chosen else CARD, border=ft.Border.all(1.5 if chosen else 1, GOLD if chosen else "#2A2A2A"),
                on_click=pick_mode(key),
                content=ft.Row(spacing=16, controls=[
                    ft.Icon(icon, color=GOLD if chosen else MUTED, size=26),
                    ft.Column(spacing=2, tight=True, controls=[
                        ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color=TEXT),
                        ft.Text(subtitle, size=13, color=MUTED),
                    ]),
                ]),
            )

        controls: list[ft.Control] = [
            ft.Container(height=12),
            ft.Row([tower_view(Tower(p, Size.L, sh), 46) for p, sh in ((1, Shape.H), (2, Shape.Q), (3, Shape.T))],
                   alignment=ft.MainAxisAlignment.CENTER, spacing=14),
            ft.Text("Talat", size=76, font_family=SERIF, italic=True, weight=ft.FontWeight.BOLD, color=TEXT,
                    text_align=ft.TextAlign.CENTER),
            serif("The Power of Three", 20),
            ft.Container(height=14),
            *[mode_card(key) for key in PRESETS],
            ft.TextButton("Hide players" if self.customize else "Customize players",
                          on_click=lambda e: self.toggle_customize(), style=ft.ButtonStyle(color=MUTED)),
        ]
        if self.customize:
            controls.append(self.customize_panel(width))
        controls += [
            ft.Container(height=6),
            ft.FilledButton("Play", width=width, height=54, on_click=lambda e: self.start(),
                            style=ft.ButtonStyle(bgcolor=GOLD, color=BG,
                                                 text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
                                                 shape=ft.RoundedRectangleBorder(radius=14))),
            ft.Container(height=12),
        ]
        return ft.Column(controls, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                         width=self.size()[0] - 2 * PAGE_PAD, scroll=ft.ScrollMode.AUTO, expand=True)

    def toggle_customize(self) -> None:
        self.customize = not self.customize
        self.render()

    def customize_panel(self, width: float) -> ft.Control:
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

        time_label = ft.Text(f"AI thinking time · {self.time_limit:.1f} s", size=13, color=MUTED)
        rows = []
        for p in PLAYERS:
            human = self.seats[p] == "human"
            room = width - 42                  # beside the disc
            controls = [
                disc(p, 30),
                ft.Dropdown(value=self.seats[p], width=room * 0.48 if human else room, menu_width=room,
                            label=PLAYER_NAMES[p], border_color="#3A3A3A", focused_border_color=GOLD,
                            on_select=set_seat(p),
                            options=[ft.DropdownOption(key=k, text=v) for k, v in SEAT_CHOICES.items()]),
            ]
            if human:                          # a human gets a name (blank: "You" or "Player 2")
                controls.append(ft.TextField(
                    value=self.names[p], label="Name", hint_text=self.default_name(p, self.seats),
                    max_length=12, counter="", width=room * 0.52 - 12, border_color="#3A3A3A",
                    focused_border_color=GOLD, capitalization=ft.TextCapitalization.WORDS,
                    on_change=set_name(p)))
            rows.append(ft.Row(spacing=12, controls=controls))
        if any(seat != "human" for seat in self.seats.values()):
            rows += [time_label, ft.Slider(min=0.2, max=3.0, divisions=14, value=self.time_limit, width=width,
                                           active_color=GOLD, on_change=set_time)]
        return ft.Column(rows, spacing=12, width=width)

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
        """Create the game screen once per game (and on resize): the main view of the table, and,
        where the screen has room beside it, the players panel / mini table."""
        s = self.session
        width, height = self.scene_size = self.scene_dims()
        self.main_rect, self.side_rect = main, side = regions(width, height)
        humans = [p for p in PLAYERS if s.agents[p] is None]
        # The main table is drawn once at the largest zoom its camera will use, then scaled down.
        zoom = max([table_camera(main.w, main.h).zoom] +
                   [focus_camera(n, main.w, main.h).zoom for p in humans for n in boards_of(p)])
        self.main = TableView(zoom, main)
        self.main.look(table_camera(main.w, main.h))          # every game opens on the whole table
        layers: list[ft.Control] = []
        self.mini, self.panel = None, None
        if side is not None:
            self.panel = ft.Container(left=side.x, top=side.y, width=side.w, height=side.h,
                                      alignment=ft.Alignment.CENTER, animate_opacity=MOTION)
            layers.append(self.panel)
            if humans:               # the mini table only appears while a human zooms in on a board
                mini_cam = table_camera(side.w, side.h)
                self.mini = TableView(mini_cam.zoom, side, discs=False, animate=False)
                self.mini.look(mini_cam)
                self.mini.frame.opacity = 0.0
                layers.append(self.mini.frame)
        layers.append(self.main.frame)
        self.scene = ft.Stack(layers, width=width, height=height)
        self.top = ft.Container(height=TOP_BAR)
        self.bottom = ft.Container(height=self.bottom_height(), width=width, alignment=ft.Alignment.TOP_CENTER)
        self.page.controls[:] = [ft.SafeArea(expand=True, content=ft.Column(
            [self.top, ft.Row([self.scene], alignment=ft.MainAxisAlignment.CENTER), self.bottom],
            spacing=GAP, expand=True))]

    def refresh_scene(self) -> None:
        s = self.session
        main = self.main_rect
        self.main.look(camera(self.stage, s.to_move, self.focus, main.w, main.h))
        playable = s.playable_boards()               # empty unless a human is to move
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
        """Each player: colour, name, who plays it, and the towers they have captured."""
        s = self.session
        side = self.side_rect
        rows = []
        for p in PLAYERS:
            current = not s.is_over() and s.to_move == p
            taken = sorted(s.state.captured[p], key=lambda t: t.rank, reverse=True)
            trophies = ([tower_view(t, 18) for t in taken] if taken
                        else [ft.Text("no captures yet", size=12, color="#5A5A5A")])
            rows.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=12, bgcolor=CARD,
                border=ft.Border.all(1.5 if current else 1, GOLD if current else "#2A2A2A"),
                content=ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    disc(p, 26, glow=current),
                    ft.Column([ft.Text(self.display_name(p), size=14, weight=ft.FontWeight.BOLD, max_lines=1,
                                       overflow=ft.TextOverflow.ELLIPSIS),
                               ft.Text(PLAYER_NAMES[p], size=11, color=MUTED)], spacing=0, tight=True, width=96),
                    ft.Row(trophies, wrap=True, spacing=2, run_spacing=2, expand=True),
                ]),
            ))
        return ft.Column(rows, spacing=8, width=min(side.w, 440), tight=True)

    def top_bar(self) -> ft.Control:
        s = self.session
        pts = scores(s.state)
        score_discs = ft.Row([disc(p, 30, str(pts[p]), glow=not s.is_over() and s.to_move == p) for p in PLAYERS],
                             spacing=8)
        for p, d in zip(PLAYERS, score_discs.controls):
            d.tooltip = f"{self.display_name(p)} ({PLAYER_NAMES[p]})"
        buttons = []
        if s.is_human_turn():
            if self.stage == "focus":
                buttons.append(ft.IconButton(ft.Icons.ARROW_BACK_ROUNDED, icon_color=GOLD, tooltip="Both boards",
                                             on_click=lambda e: self.show_pair()))
            elif self.stage == "pair":
                buttons.append(ft.IconButton(ft.Icons.CHANGE_HISTORY_ROUNDED, icon_color=GOLD, tooltip="Whole table",
                                             on_click=lambda e: self.show_table()))
            else:
                buttons.append(ft.IconButton(ft.Icons.GRID_VIEW_ROUNDED, icon_color=GOLD, tooltip="Your boards",
                                             on_click=lambda e: self.show_pair()))
        elif s.has_ai() and not s.is_over():
            buttons.append(ft.IconButton(ft.Icons.PLAY_ARROW_ROUNDED if self.paused else ft.Icons.PAUSE_ROUNDED,
                                         icon_color=GOLD, tooltip="Resume" if self.paused else "Pause",
                                         on_click=lambda e: self.toggle_pause()))
        buttons.append(ft.IconButton(ft.Icons.HOME_ROUNDED, icon_color=GOLD, tooltip="Menu",
                                     on_click=lambda e: self.new_game()))
        return ft.Row([serif("Talat", 28), score_discs, ft.Row(buttons, spacing=0)],
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
        name = self.display_name(p)
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
            return f"Paused · {name} ({PLAYER_NAMES[p]}) is next"
        return f"{name} ({PLAYER_NAMES[p]}) is thinking…"

    def status_row(self) -> ft.Control:
        s = self.session
        busy = not s.is_over() and not s.is_human_turn() and not self.paused
        items = [ft.Text(self.status_text(), size=15, color=TEXT if s.is_human_turn() else MUTED)]
        if busy:
            items.insert(0, ft.ProgressRing(width=14, height=14, stroke_width=2, color=GOLD))
        if s.must_pass():          # rare, so it sits in the status line instead of taking room
            items.append(ft.FilledButton("No moves: pass", height=36, on_click=lambda e: self.human(s.pass_turn),
                                         style=ft.ButtonStyle(bgcolor=GOLD, color=BG)))
        return ft.Row(items, alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True)

    def hand_tray(self, player: int) -> ft.Control:
        s = self.session
        active = s.is_human_turn() and s.to_move == player
        current = s.setup_tower() if active else None

        def pick(tower):
            return lambda e: self.human(lambda: s.choose_tower(tower))

        towers = [
            ft.Container(
                width=44, height=44, bgcolor=BEIGE, border_radius=8, on_click=pick(t) if active else None,
                border=ft.Border.all(3 if t == current else 1, GOLD if t == current else GRID),
                content=tower_view(t, 44),
            )
            for t in sorted(s.state.hands[player], key=lambda t: t.rank, reverse=True)
        ]
        return ft.Row(towers, wrap=True, spacing=6, run_spacing=6, alignment=ft.MainAxisAlignment.CENTER,
                      opacity=1.0 if active else 0.45)

    # ---------- stages ----------

    def turn_view(self) -> None:
        """Choose the stage for whoever moves next: a human gets their two boards, otherwise the table."""
        human = self.session is not None and self.session.is_human_turn()
        self.stage, self.focus = ("pair" if human else "table"), None

    def focus_board(self, name: str) -> None:
        s = self.session
        if s is not None and name in s.playable_boards():
            self.stage, self.focus = "focus", name
            s.selected = None
            self.render()

    def show_pair(self) -> None:
        self.stage, self.focus = "pair", None
        if self.session:
            self.session.selected = None
        self.render()

    def show_table(self) -> None:
        self.stage, self.focus = "table", None
        self.render()

    # ---------- flow ----------

    def start(self) -> None:
        self.session = Session(self.seats, time_limit=self.time_limit)
        self.paused = False
        self.scene = None                 # the game opens on the whole table, then the camera moves in
        self.turn_view()
        self.render()
        self.maybe_run_ai()

    def new_game(self) -> None:
        self.session = None      # any AI move still being computed for the old game is dropped
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
        if s is None or s.is_over() or s.is_human_turn() or self.paused or self.thinking:
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
        s = self.session
        pts = scores(s.state)
        win = winners(s.state)
        if len(win) > 1:
            title = "Shared win"
        else:
            name = self.display_name(win[0])
            title = "You win" if name == "You" else f"{name} wins"
        rows = [
            ft.Row(spacing=12, controls=[
                disc(p, 28),
                ft.Column([ft.Text(self.display_name(p), size=15, weight=ft.FontWeight.BOLD, max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS),
                           ft.Text(PLAYER_NAMES[p], size=12, color=MUTED)], spacing=0, tight=True, width=136),
                ft.Text(f"{pts[p]}", size=18, weight=ft.FontWeight.BOLD, color=GOLD if p in win else TEXT),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for p in sorted(PLAYERS, key=lambda p: -pts[p])
        ]

        def close(e):
            self.page.pop_dialog()

        def again(e):
            self.page.pop_dialog()
            self.start()

        def menu(e):
            self.page.pop_dialog()
            self.new_game()

        self.page.show_dialog(ft.AlertDialog(
            modal=True, bgcolor=CARD, title=serif(title, 30),
            content=ft.Column(rows, tight=True, spacing=10),
            # Icons for the two quiet choices, so all three fit on one line on a phone.
            actions=[ft.IconButton(ft.Icons.VISIBILITY_OUTLINED, icon_color=MUTED, tooltip="View board",
                                   on_click=close),
                     ft.IconButton(ft.Icons.HOME_ROUNDED, icon_color=MUTED, tooltip="Menu", on_click=menu),
                     ft.FilledButton("Play again", on_click=again, style=ft.ButtonStyle(bgcolor=GOLD, color=BG))],
            actions_alignment=ft.MainAxisAlignment.END,
        ))


def main(page: ft.Page) -> None:
    TalatApp(page)


if __name__ == "__main__":
    ft.run(main)
