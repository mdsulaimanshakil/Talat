"""TALAT 3D — Ursina desktop application.

Run with:
    python -m talat.app3d          (from the project root)
    python talat/app3d.py          (direct)

Controls:
    Left-click      select / move / place tower
    Right-drag      orbit camera
    Middle-drag     pan camera
    Scroll wheel    zoom in / out
    Escape          quit
"""
from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Ursina ────────────────────────────────────────────────────────────────────
from ursina import (
    Ursina, Entity, Button, Text, DirectionalLight, AmbientLight,
    EditorCamera, camera, mouse, window, color, Vec3,
    held_keys, destroy, invoke, Mesh,
)

# ── Game engine ───────────────────────────────────────────────────────────────
from talat.engine import (
    BOARD_PLAYERS, BOARD_SIZE, PLAYER_NAMES, PLAYERS,
    Shape, Size, Square, Tower,
    boards_of, end_reason, is_frozen, scores, winners,
    legal_actions, legal_placements,
)
from talat.session import PRESETS, SEAT_CHOICES, Session, seat_name

# ══════════════════════════════════════════════════════════════════════════════
# Colour palette  (matches the original Flet app)
# ══════════════════════════════════════════════════════════════════════════════
BG_COL      = color.rgb(10,  10,  10)
GOLD_COL    = color.rgb(201, 151, 58)
BEIGE_COL   = color.rgb(235, 213, 174)
GRID_COL    = color.rgb(140, 106, 46)
DARK_COL    = color.rgb(30,  30,  30)
SELECT_COL  = color.rgb(61,  123, 224)
CAPTURE_COL = color.rgb(229, 57,  53)
FROZEN_COL  = color.rgb(70,  70,  70)
MUTED_COL   = color.rgb(100, 100, 100)

# Tower surface per player
TOWER_COL = {
    1: color.rgb(244, 244, 240),   # White
    2: color.rgb(25,  25,  25),    # Black
    3: color.rgb(160, 160, 160),   # Grey
}
# Starting-line tint per player
LINE_COL = {
    1: color.rgb(215, 215, 210),
    2: color.rgb(40,  40,  40),
    3: color.rgb(190, 190, 190),
}

# ══════════════════════════════════════════════════════════════════════════════
# World layout constants
# ══════════════════════════════════════════════════════════════════════════════
BOARD_RADIUS     = 4.0           # table centre → board centre (world units)
BOARD_DIRECTIONS = {"A": -30, "B": 90, "C": 210}   # degrees, clockwise around Y
BOARD_ROTATIONS  = {"A": -30, "B": 90, "C": -150}  # each board's Y rotation

CELL_SIZE   = 1.0                # world units per grid square
BOARD_SCALE = BOARD_SIZE * CELL_SIZE   # 5.0 units

# Tower heights and radii per size
TOWER_H  = {Size.L: 1.4,  Size.M: 1.0,  Size.S: 0.6}
TOWER_R  = {Size.L: 0.38, Size.M: 0.28, Size.S: 0.20}
INNER_F  = 0.52                  # hollow inner radius as fraction of outer

# ══════════════════════════════════════════════════════════════════════════════
# Procedural mesh builders
# ══════════════════════════════════════════════════════════════════════════════

def _ngon(n: int, r: float, cx: float = 0.0, cz: float = 0.0) -> list[tuple]:
    """Regular n-gon vertices in the XZ plane at y = 0."""
    return [
        (cx + r * math.cos(math.radians(90 + i * 360 / n)),
         0,
         cz + r * math.sin(math.radians(90 + i * 360 / n)))
        for i in range(n)
    ]


def _cross(ax, ay, az, bx, by, bz):
    return (ay*bz - az*by, az*bx - ax*bz, ax*by - ay*bx)


def _normalised(nx, ny, nz):
    L = max((nx**2 + ny**2 + nz**2) ** 0.5, 1e-9)
    return nx/L, ny/L, nz/L


def _prism_mesh(sides: int, outer_r: float, inner_r: float, height: float) -> Mesh:
    """Hollow prism: outer walls + inner walls + top ring. Base is open."""
    verts, tris, norms, uvs = [], [], [], []

    ot = _ngon(sides, outer_r)                           # outer top ring, y=0
    ob = [(x, -height, z) for x, _, z in ot]            # outer bottom ring
    it = _ngon(sides, inner_r)                           # inner top ring
    ib = [(x, -height, z) for x, _, z in it]            # inner bottom ring

    def quad(a, b, c, d):
        base = len(verts)
        verts.extend([a, b, c, d])
        tris.extend([(base, base+1, base+2), (base, base+2, base+3)])
        nx, ny, nz = _cross(
            b[0]-a[0], b[1]-a[1], b[2]-a[2],
            d[0]-a[0], d[1]-a[1], d[2]-a[2],
        )
        n_ = _normalised(nx, ny, nz)
        norms.extend([n_] * 4)
        uvs.extend([(0, 0), (1, 0), (1, 1), (0, 1)])

    for i in range(sides):
        j = (i + 1) % sides
        quad(ot[i], ot[j], ob[j], ob[i])                # outer wall
        quad(it[j], it[i], ib[i], ib[j])                # inner wall (flipped)
        quad(ot[i], ot[j], it[j], it[i])                # top ring

    return Mesh(vertices=verts, triangles=tris, normals=norms, uvs=uvs, mode='triangle')


def _pyramid_mesh(sides: int, outer_r: float, inner_r: float, height: float) -> Mesh:
    """Hollow pyramid for the triangle shape."""
    verts, tris, norms, uvs = [], [], [], []
    apex       = (0.0, 0.0, 0.0)
    inner_apex = (0.0, -height * 0.15, 0.0)
    ob = [(x, -height,            z) for x, _, z in _ngon(sides, outer_r * 1.1)]
    ib = [(x, -height + height*0.15, z) for x, _, z in _ngon(sides, inner_r * 1.1)]

    def tri(a, b, c):
        base = len(verts)
        verts.extend([a, b, c])
        tris.append((base, base+1, base+2))
        nx, ny, nz = _cross(
            b[0]-a[0], b[1]-a[1], b[2]-a[2],
            c[0]-a[0], c[1]-a[1], c[2]-a[2],
        )
        norms.extend([_normalised(nx, ny, nz)] * 3)
        uvs.extend([(0, 0), (1, 0), (0.5, 1)])

    for i in range(sides):
        j = (i + 1) % sides
        tri(apex, ob[j], ob[i])                          # outer face
        tri(inner_apex, ib[i], ib[j])                    # inner face
        tri(ob[i], ob[j], ib[j])                         # bottom ring (half)
        tri(ob[i], ib[j], ib[i])

    return Mesh(vertices=verts, triangles=tris, normals=norms, uvs=uvs, mode='triangle')


# Cache of (Shape, Size) → Mesh — built once at startup
TOWER_MESHES: dict[tuple[Shape, Size], Mesh] = {}


def _ensure_meshes():
    if TOWER_MESHES:
        return
    for sh in Shape:
        for sz in Size:
            r = TOWER_R[sz]
            h = TOWER_H[sz]
            ri = r * INNER_F
            if sh == Shape.T:
                TOWER_MESHES[(sh, sz)] = _pyramid_mesh(3, r, ri, h)
            elif sh == Shape.Q:
                TOWER_MESHES[(sh, sz)] = _prism_mesh(4, r, ri, h)
            else:
                TOWER_MESHES[(sh, sz)] = _prism_mesh(6, r, ri, h)


# ══════════════════════════════════════════════════════════════════════════════
# World-coordinate helpers
# ══════════════════════════════════════════════════════════════════════════════

def _board_centre(name: str) -> tuple[float, float]:
    """World (x, z) of a board's centre."""
    a = math.radians(BOARD_DIRECTIONS[name])
    return BOARD_RADIUS * math.sin(a), BOARD_RADIUS * math.cos(a)


def _cell_world(name: str, row: int, col: int) -> Vec3:
    """World position of a cell centre (y = 0, the top of the board slab)."""
    bx, bz = _board_centre(name)
    rot = math.radians(BOARD_ROTATIONS[name])
    lx = (col - 2) * CELL_SIZE
    lz = (row - 2) * CELL_SIZE
    wx = lx * math.cos(rot) - lz * math.sin(rot)
    wz = lx * math.sin(rot) + lz * math.cos(rot)
    return Vec3(bx + wx, 0, bz + wz)


# ══════════════════════════════════════════════════════════════════════════════
# Scene entities
# ══════════════════════════════════════════════════════════════════════════════

class TileEntity(Entity):
    """One board cell — clickable, colour-highlighted."""

    def __init__(self, board_name: str, row: int, col: int,
                 base_color: color, game: "TalatGame3D"):
        pos = _cell_world(board_name, row, col)
        super().__init__(
            model="cube",
            color=base_color,
            position=Vec3(pos.x, -0.055, pos.z),
            scale=Vec3(CELL_SIZE * 0.97, 0.11, CELL_SIZE * 0.97),
            collider="box",
        )
        self.board_name = board_name
        self.row = row
        self.col = col
        self.base_color = base_color
        self.game = game

    def on_click(self):
        self.game.on_tile_click(self.board_name, self.row, self.col)

    def set_highlight(self, mode: str) -> None:
        if mode == "select":
            self.color = SELECT_COL
        elif mode == "target":
            self.color = color.rgb(80, 140, 220)
        elif mode == "capture":
            self.color = CAPTURE_COL
        elif mode == "frozen":
            self.color = FROZEN_COL
        else:
            self.color = self.base_color


class TowerEntity(Entity):
    """A single 3D tower standing on the board."""

    def __init__(self, tower: Tower, board_name: str, row: int, col: int,
                 game: "TalatGame3D"):
        pos = _cell_world(board_name, row, col)
        h   = TOWER_H[tower.size]
        super().__init__(
            model=TOWER_MESHES[(tower.shape, tower.size)],
            color=TOWER_COL[tower.owner],
            position=Vec3(pos.x, h, pos.z),          # pivot at top face
            rotation_y=BOARD_ROTATIONS[board_name],   # orient square/triangle with board
            collider="box",
        )
        self.tower      = tower
        self.board_name = board_name
        self.row        = row
        self.col        = col
        self.game       = game

    def on_click(self):
        self.game.on_tower_click(self.board_name, self.row, self.col)


class BoardSlab(Entity):
    """The beige slab and dark border frame for one board."""

    def __init__(self, board_name: str):
        bx, bz = _board_centre(board_name)
        rot_y  = BOARD_ROTATIONS[board_name]
        super().__init__(
            model="cube",
            color=BEIGE_COL,
            position=Vec3(bx, -0.13, bz),
            rotation_y=rot_y,
            scale=Vec3(BOARD_SCALE + 0.55, 0.13, BOARD_SCALE + 0.55),
        )
        # Four dark border strips (children, so they rotate with the board)
        half  = BOARD_SCALE / 2
        thick = 0.28
        for lx, lz, sw, sl in [
            (0,              -(half + thick/2), BOARD_SCALE + thick*2, thick),
            (0,               (half + thick/2), BOARD_SCALE + thick*2, thick),
            (-(half + thick/2), 0,              thick, BOARD_SCALE),
            ( (half + thick/2), 0,              thick, BOARD_SCALE),
        ]:
            Entity(
                parent=self,
                model="cube",
                color=DARK_COL,
                position=Vec3(lx, 0.03, lz),
                scale=Vec3(sw, 0.16, sl),
            )


# ══════════════════════════════════════════════════════════════════════════════
# Heads-up display (screen-space text + buttons)
# ══════════════════════════════════════════════════════════════════════════════

class HUD:
    def __init__(self):
        self.status = Text("", position=(-0.85, 0.47), scale=1.05,
                           color=color.white, background=True)
        self.scores = Text("", position=(-0.85, 0.41), scale=0.88,
                           color=GOLD_COL, background=True)
        self.turn   = Text("", position=(-0.85, 0.35), scale=0.88,
                           color=color.white, background=True)
        self.hint   = Text(
            "[L-Click] select/move   [R-drag] orbit   [Scroll] zoom   [Esc] quit",
            position=(-0.85, -0.47), scale=0.62, color=MUTED_COL, background=True,
        )

    def update(self, session: "Session | None", status: str) -> None:
        self.status.text = status
        if session is None:
            self.scores.text = ""
            self.turn.text   = ""
            return
        pts = scores(session.state)
        self.scores.text = "   ".join(
            f"P{p} {PLAYER_NAMES[p]}: {pts[p]}" for p in PLAYERS
        )
        if not session.is_over():
            p = session.to_move
            self.turn.text = f"→  {PLAYER_NAMES[p]}'s turn"
        else:
            self.turn.text = ""

    def cleanup(self):
        for obj in (self.status, self.scores, self.turn, self.hint):
            destroy(obj)


# ══════════════════════════════════════════════════════════════════════════════
# Main game controller
# ══════════════════════════════════════════════════════════════════════════════

class TalatGame3D:
    """
    Owns all Ursina scene objects, links them to the Session, and handles input.
    """

    def __init__(self):
        self.session:   Session | None                             = None
        self.tiles:     dict[tuple[str, int, int], TileEntity]    = {}
        self.towers:    dict[tuple[str, int, int], TowerEntity]   = {}
        self.slabs:     list[BoardSlab]                           = []
        self.selected:  tuple[str, int, int] | None               = None
        self.hud        = HUD()
        self._overlays: list                                      = []   # menu / result widgets
        self.lock       = threading.Lock()
        self.thinking   = False

        self._setup_lights()
        self._make_table()
        self._show_start_menu()

    # ── world setup ────────────────────────────────────────────────────────

    def _setup_lights(self):
        AmbientLight(color=color.rgba(90, 90, 90, 255))
        sun = DirectionalLight()
        sun.look_at(Vec3(1, -2, 0.5))

    def _make_table(self):
        # Dark floor plane
        Entity(model="plane", color=color.rgb(16, 12, 8),
               scale=60, position=Vec3(0, -0.21, 0))

    # ── board / tile setup ─────────────────────────────────────────────────

    def _build_boards(self):
        for name, (top_p, bot_p) in BOARD_PLAYERS.items():
            self.slabs.append(BoardSlab(name))
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if r == 0:
                        base = LINE_COL[top_p]
                    elif r == BOARD_SIZE - 1:
                        base = LINE_COL[bot_p]
                    else:
                        base = BEIGE_COL
                    t = TileEntity(name, r, c, base, self)
                    self.tiles[(name, r, c)] = t

    def _clear_scene(self):
        for e in list(self.tiles.values()):
            destroy(e)
        for e in list(self.towers.values()):
            destroy(e)
        for b in self.slabs:
            destroy(b)
        self.tiles.clear()
        self.towers.clear()
        self.slabs.clear()
        self.selected = None

    # ── start menu ─────────────────────────────────────────────────────────

    def _show_start_menu(self):
        self._clear_overlays()

        def add(w):
            self._overlays.append(w)

        add(Text("TALAT", scale=4.5, position=(0, 0.38), origin=(0, 0),
                 color=color.white))
        add(Text("The Power of Three", scale=1.5, position=(0, 0.27),
                 origin=(0, 0), color=GOLD_COL))

        modes = [
            ("solo",  "Solo — You vs two AIs"),
            ("watch", "Watch — Three AIs battle"),
            ("all",   "Pass & play — 3 humans"),
        ]
        for i, (key, label) in enumerate(modes):
            by = 0.10 - i * 0.09
            add(Button(
                text=label,
                scale=(0.44, 0.07),
                position=(0, by),
                color=DARK_COL,
                highlight_color=color.rgb(50, 50, 50),
                pressed_color=GOLD_COL,
                on_click=lambda k=key: self._start_game(k),
            ))

        add(Text("Click a mode above to start",
                 scale=0.85, position=(0, -0.14), origin=(0, 0), color=MUTED_COL))
        self.hud.update(None, "Welcome to TALAT 3D")

    def _clear_overlays(self):
        for e in self._overlays:
            destroy(e)
        self._overlays.clear()

    # ── game lifecycle ──────────────────────────────────────────────────────

    def _start_game(self, mode: str):
        self._clear_overlays()
        _, _, seat_tuple = PRESETS[mode]
        seats = dict(zip(PLAYERS, seat_tuple))
        self.session  = Session(seats, time_limit=1.0)
        self.thinking = False
        self.selected = None
        self._clear_scene()
        self._build_boards()
        self._refresh()
        self._maybe_run_ai()

    def _refresh(self):
        """Full visual sync: towers, highlights, HUD."""
        s = self.session
        if s is None:
            return
        self._sync_towers()
        self._sync_highlights()
        self._sync_hud()

    # ── tower sync ─────────────────────────────────────────────────────────

    def _sync_towers(self):
        s = self.session
        wanted: dict[tuple[str, int, int], Tower] = {}
        for name, board in s.state.boards.items():
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    t = board[(r, c)]
                    if t is not None:
                        wanted[(name, r, c)] = t

        # Remove stale
        for key in list(self.towers.keys()):
            if key not in wanted or self.towers[key].tower != wanted[key]:
                destroy(self.towers.pop(key))

        # Add new
        for key, tower in wanted.items():
            if key not in self.towers:
                n, r, c = key
                self.towers[key] = TowerEntity(tower, n, r, c, self)

    # ── highlight sync ─────────────────────────────────────────────────────

    def _sync_highlights(self):
        s = self.session
        targets = s.targets()   # {(board, sq): Action}
        frozen  = {
            n for n in BOARD_PLAYERS
            if s.state.phase == "play" and is_frozen(s.state.boards[n])
        }

        for (bn, r, c), tile in self.tiles.items():
            sq = (r, c)
            if bn in frozen:
                tile.set_highlight("frozen")
            elif self.selected == (bn, r, c):
                tile.set_highlight("select")
            elif (bn, sq) in targets:
                board = s.state.boards[bn]
                mode  = "capture" if board[(r, c)] is not None else "target"
                tile.set_highlight(mode)
            else:
                tile.set_highlight("")

    # ── HUD sync ───────────────────────────────────────────────────────────

    def _sync_hud(self):
        s = self.session
        if s is None:
            return
        if s.is_over():
            win = winners(s.state)
            if len(win) > 1:
                status = f"Shared win!  ({end_reason(s.state)})"
            else:
                status = f"P{win[0]} {PLAYER_NAMES[win[0]]} wins!  ({end_reason(s.state)})"
        elif not s.is_human_turn():
            p = s.to_move
            status = f"{PLAYER_NAMES[p]} (AI) is thinking…"
        else:
            p = s.to_move
            if s.state.phase == "setup":
                status = f"P{p} {PLAYER_NAMES[p]}: click a starting square to place a tower"
            elif self.selected is None:
                status = f"P{p} {PLAYER_NAMES[p]}: click one of your towers"
            else:
                status = f"P{p} {PLAYER_NAMES[p]}: click a highlighted square"
        self.hud.update(s, status)

    # ── input handlers ──────────────────────────────────────────────────────

    def on_tile_click(self, board_name: str, row: int, col: int):
        s = self.session
        if s is None or not s.is_human_turn() or s.is_over():
            return
        with self.lock:
            sq      = (row, col)
            targets = s.targets()
            if (board_name, sq) in targets:
                s.play(targets[(board_name, sq)])
                self.selected = None
                self._refresh()
                if s.is_over():
                    self._show_result()
                else:
                    self._maybe_run_ai()
            else:
                # Click on empty / non-target square → deselect
                self.selected = None
                self._sync_highlights()
                self._sync_hud()

    def on_tower_click(self, board_name: str, row: int, col: int):
        s = self.session
        if s is None or not s.is_human_turn() or s.is_over():
            return
        with self.lock:
            sq      = (row, col)
            targets = s.targets()

            # Is this tower a capture target?
            if (board_name, sq) in targets:
                s.play(targets[(board_name, sq)])
                self.selected = None
                self._refresh()
                if s.is_over():
                    self._show_result()
                else:
                    self._maybe_run_ai()
                return

            # Setup phase: clicking any tile places the next tower
            if s.state.phase == "setup":
                self.on_tile_click(board_name, row, col)
                return

            # Play phase: select / deselect
            if s.selectable(board_name, sq):
                old = self.selected
                self.selected = (
                    None if old == (board_name, row, col)
                    else (board_name, row, col)
                )
            else:
                self.selected = None
            self._sync_highlights()
            self._sync_hud()

    # ── AI worker ──────────────────────────────────────────────────────────

    def _maybe_run_ai(self):
        s = self.session
        if s is None or s.is_over() or s.is_human_turn() or self.thinking:
            return
        self.thinking = True
        threading.Thread(target=self._ai_worker, args=(s,), daemon=True).start()

    def _ai_worker(self, s: Session):
        try:
            action = s.think()
        except Exception as exc:
            self.thinking = False
            self.hud.update(s, f"AI error: {exc}")
            return
        time.sleep(0.35)   # small pause so the human sees the previous move
        with self.lock:
            self.thinking = False
            if s is not self.session:
                return   # a new game started while we were thinking
            s.play(action)
        # Ursina is not thread-safe, so schedule the UI update on the main thread
        invoke(self._after_ai)

    def _after_ai(self):
        self._refresh()
        s = self.session
        if s and s.is_over():
            self._show_result()
        else:
            self._maybe_run_ai()

    # ── result screen ───────────────────────────────────────────────────────

    def _show_result(self):
        self._clear_overlays()
        s   = self.session
        pts = scores(s.state)
        win = winners(s.state)

        title = (
            "Shared win!" if len(win) > 1
            else f"P{win[0]} {PLAYER_NAMES[win[0]]} wins!"
        )
        self._overlays.append(
            Text(title, scale=3.2, position=(0, 0.32), origin=(0, 0), color=GOLD_COL)
        )
        for i, p in enumerate(sorted(PLAYERS, key=lambda p: -pts[p])):
            ly    = 0.20 - i * 0.08
            col_  = GOLD_COL if p in win else color.white
            self._overlays.append(
                Text(f"P{p} {PLAYER_NAMES[p]}  —  {pts[p]} pts",
                     scale=1.3, position=(0, ly), origin=(0, 0), color=col_)
            )

        self._overlays.append(
            Text(f"({end_reason(s.state)})",
                 scale=0.9, position=(0, 0.20 - 3*0.08 - 0.03),
                 origin=(0, 0), color=MUTED_COL)
        )

        # Determine the mode key so "play again" can restart the same mode
        seat_vals = list(s.seats.values())
        mode_key  = next(
            (k for k, (_, _, st) in PRESETS.items() if list(st) == seat_vals),
            "watch",
        )

        self._overlays.append(Button(
            text="Play again",
            scale=(0.30, 0.07),
            position=(-0.19, -0.23),
            color=GOLD_COL,
            pressed_color=GOLD_COL * 1.3,
            on_click=lambda: self._start_game(mode_key),
        ))
        self._overlays.append(Button(
            text="Main menu",
            scale=(0.30, 0.07),
            position=(0.19, -0.23),
            color=DARK_COL,
            highlight_color=color.rgb(50, 50, 50),
            on_click=self._go_menu,
        ))

    def _go_menu(self):
        self._clear_overlays()
        self._clear_scene()
        self.session = None
        self._show_start_menu()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    _ensure_meshes()

    app = Ursina(
        title="TALAT 3D",
        borderless=False,
        fullscreen=False,
        development_mode=False,
    )
    window.color = BG_COL
    window.exit_button.visible = True

    # EditorCamera gives free orbit (right-drag), pan (middle-drag), zoom (scroll)
    ec = EditorCamera()
    ec.position    = Vec3(0, 12, -16)
    ec.rotation_x  = 38

    game = TalatGame3D()

    app.run()


if __name__ == "__main__":
    main()
