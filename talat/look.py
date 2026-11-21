"""How the game looks, and the player's saved choices.

Everything a player can change under Settings lives here: the theme (room, board and accent
colours), the tower colours, how a tower shows its size, the board frame, the A-E / 1-5 labels,
the move hints and the AI speed. Pure data and geometry, no UI code, so it can be tested.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


# ---------- colour helpers ----------

def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def mix(a: str, b: str, t: float) -> str:
    """The colour a fraction `t` of the way from `a` to `b`."""
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(_rgb(a), _rgb(b)))


def luminance(color: str) -> float:
    r, g, b = (v / 255 for v in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ink_on(color: str) -> str:
    """Black or white, whichever reads on `color`."""
    return "#111111" if luminance(color) > 0.45 else "#FFFFFF"


# ---------- the options ----------

@dataclass(frozen=True)
class Frame:
    wood: str       # the band around the squares
    rim: str        # its outer edge
    inlay: str      # the thin line where the frame meets the squares
    mark: str       # diamonds, corner dots and the A-E / 1-5 labels


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str         # the room
    bg2: str        # the glow in the middle of the room
    card: str       # panels, cards, dialogs
    line: str       # their borders
    text: str
    muted: str
    accent: str     # logo, highlights, the glow on whoever is to move
    square: str     # board squares (starting lines take their player's colour)
    grid: str       # lines between squares
    grid_width: float
    shadow: str     # under each board
    frame: Frame
    tag: str = ""
    light: bool = False


THEMES: dict[str, Theme] = {
    "midnight": Theme("Midnight Brass", "#0A0A0A", "#18140E", "#161616", "#2A2A2A", "#FFFFFF", "#9A9A9A", "#C9973A",
                      "#EBD5AE", "#8C6A2E", 0.5, "#C0000000", Frame("#2E1F14", "#4D3523", "#C9973A", "#DDB462"),
                      tag="Default"),
    "library": Theme("Library Green", "#0D1A15", "#1B3529", "#14261E", "#24402F", "#F3EFE4", "#9DB3A5", "#D4A64A",
                     "#E6CC9A", "#8E6A33", 0.5, "#99000000", Frame("#3A2416", "#5A3A24", "#D4A64A", "#E3BC6A")),
    "slate": Theme("Slate & Ivory", "#13181F", "#232C38", "#1B222B", "#2D3742", "#EEF2F6", "#94A3B3", "#8FB8E0",
                   "#DCD1BC", "#7D8A99", 0.5, "#99000000", Frame("#2A313B", "#434D59", "#8FB8E0", "#B5CFEA")),
    "rosewood": Theme("Rosewood Night", "#150D12", "#2C1822", "#1F141A", "#3A2430", "#F6ECEF", "#B79AA6", "#E0A47E",
                      "#E8C7AC", "#9A6650", 0.5, "#A6000000", Frame("#4A1D24", "#6B2C35", "#E0A47E", "#EDBE9C")),
    "jade": Theme("Jade Court", "#0B1816", "#14332D", "#12221F", "#1F3B36", "#ECF4F1", "#8FB0A7", "#D2BC7A",
                  "#B7CFA6", "#5E7F5A", 0.5, "#99000000", Frame("#173B35", "#26564D", "#D2BC7A", "#E0CD92")),
    "daylight": Theme("Daylight Maple", "#DCD9D3", "#F4F2EE", "#FFFFFF", "#CFCAC0", "#1D1B18", "#66625B", "#1F6F6A",
                      "#E2BF84", "#8F6B35", 0.6, "#4D3C280A", Frame("#2F3D3C", "#465655", "#E2BF84", "#F0D6A6"),
                      tag="Light", light=True),
    "contrast": Theme("High Contrast", "#000000", "#000000", "#0D0D0D", "#4A4A4A", "#FFFFFF", "#D6D6D6", "#FFD23F",
                      "#D9A441", "#000000", 1.2, "#00000000", Frame("#000000", "#FFD23F", "#FFD23F", "#FFD23F"),
                      tag="Accessible"),
}


@dataclass(frozen=True)
class Colour:
    """One player's colour: their towers, starting line and score disc."""
    name: str
    fill: str
    edge: str       # outline of the tower
    top: str        # rings and the hollow top, drawn on the fill
    line: str       # their starting-line squares
    ink: str        # text on their score disc


@dataclass(frozen=True)
class Palette:
    name: str
    colours: dict[int, Colour]
    tag: str = ""


_IVORY = Colour("Ivory", "#F5F1E6", "#1A1A1A", "#1A1A1A", "#F5F1E6", "#141414")
_ONYX = Colour("Onyx", "#151515", "#FFFFFF", "#FFFFFF", "#151515", "#FFFFFF")
# Every set gives each player a different lightness AND a different hue, so towers stay apart
# on a small screen, in greyscale and for colour-blind players.
PALETTES: dict[str, Palette] = {
    "copper": Palette("Ivory · Onyx · Copper", {1: _IVORY, 2: _ONYX,
                      3: Colour("Copper", "#C0602A", "#2A1206", "#FFF1E4", "#C9763F", "#FFFFFF")}, tag="Default"),
    "cobalt": Palette("Ivory · Cobalt · Amber", {1: _IVORY,
                      2: Colour("Cobalt", "#1D4FAE", "#FFFFFF", "#FFFFFF", "#2B5DBA", "#FFFFFF"),
                      3: Colour("Amber", "#F2A516", "#3A2600", "#3A2600", "#F0B23F", "#2A1B00")}, tag="Most distinct"),
    "teal": Palette("Ivory · Onyx · Teal", {1: _IVORY, 2: _ONYX,
                    3: Colour("Teal", "#14978A", "#062A26", "#E6FFFB", "#2BA394", "#FFFFFF")}),
    "classic": Palette("White · Black · Grey", {
        1: Colour("White", "#F4F4F0", "#1A1A1A", "#1A1A1A", "#F4F4F0", "#141414"),
        2: Colour("Black", "#141414", "#FFFFFF", "#FFFFFF", "#141414", "#FFFFFF"),
        3: Colour("Grey", "#9E9E9E", "#1A1A1A", "#FFFFFF", "#CFCFCF", "#141414")}, tag="Original"),
}

# How a tower shows its size: small 1, medium 2, large 3 outlines (except "plain").
TOWER_STYLES: dict[str, tuple[str, str]] = {
    "tiers": ("Stepped tiers", "Default"),
    "rings": ("Inner rings", ""),
    "outer": ("Outer borders", ""),
    "plain": ("Plain", "Size only"),
}

FRAMES: dict[str, tuple[str, Frame | None]] = {
    "theme": ("Match theme", None),
    "walnut": ("Walnut & brass", Frame("#2E1F14", "#4D3523", "#C9973A", "#DDB462")),
    "teal": ("Deep teal & brass", Frame("#0F2B2A", "#1F4846", "#C9973A", "#DDB462")),
    "oxblood": ("Oxblood & gold", Frame("#3A1416", "#5E2629", "#D9B26A", "#E6C784")),
    "none": ("No frame", None),
}

SPEEDS: dict[str, tuple[str, float]] = {"slow": ("Slow", 1.0), "normal": ("Normal", 0.5), "fast": ("Fast", 0.2)}


# ---------- the player's choices ----------

@dataclass
class Settings:
    theme: str = "midnight"
    palette: str = "copper"
    towers: str = "tiers"
    frame: str = "theme"
    coords: bool = True
    hints: bool = True
    speed: str = "normal"

    def valid(self) -> Settings:
        """Unknown values (an older or edited file) fall back to the defaults."""
        d = Settings()
        for key, options in (("theme", THEMES), ("palette", PALETTES), ("towers", TOWER_STYLES),
                             ("frame", FRAMES), ("speed", SPEEDS)):
            if getattr(self, key) not in options:
                setattr(self, key, getattr(d, key))
        for key in ("coords", "hints"):
            if not isinstance(getattr(self, key), bool):
                setattr(self, key, getattr(d, key))
        return self


def settings_path() -> Path:
    """Next to the app's other data: Flet's storage folder on a phone, ~/.talat on a computer.
    TALAT_SETTINGS_DIR overrides both (the tests use it)."""
    base = os.environ.get("TALAT_SETTINGS_DIR") or os.environ.get("FLET_APP_STORAGE_DATA")
    return Path(base) if base else Path.home() / ".talat"


def load_settings() -> Settings:
    try:
        data = json.loads((settings_path() / "settings.json").read_text(encoding="utf-8"))
        known = {f.name for f in fields(Settings)}
        return Settings(**{k: v for k, v in data.items() if k in known}).valid()
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings) -> None:
    """Best effort: a read-only disk must not stop the game."""
    try:
        folder = settings_path()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings.json").write_text(json.dumps(asdict(settings), indent=1), encoding="utf-8")
    except OSError:
        pass


class Look:
    """Settings turned into the colours and switches the screens draw with."""

    def __init__(self, settings: Settings | None = None):
        s = self.settings = (settings or Settings()).valid()
        t = self.theme = THEMES[s.theme]
        self.colours = PALETTES[s.palette].colours
        self.style = s.towers
        self.frame: Frame | None = t.frame if s.frame == "theme" else FRAMES[s.frame][1]   # None: no frame
        self.coords, self.hints = s.coords, s.hints
        self.ai_delay = SPEEDS[s.speed][1]
        self.ink = ink_on(t.accent)                        # text on accent buttons
        self.card_on = mix(t.card, t.accent, 0.08)         # a chosen card
        self.frozen = mix(t.muted, t.bg, 0.45)             # the letter of a frozen board

    def colour(self, player: int) -> Colour:
        return self.colours[player]

    def colour_name(self, player: int) -> str:
        return self.colours[player].name

    def tiers(self, player: int) -> list[str]:
        """The three storeys of a stepped tower, each a little further from the fill."""
        fill = self.colours[player].fill
        toward = "#000000" if luminance(fill) > 0.5 else "#FFFFFF"
        return [fill, mix(fill, toward, 0.11), mix(fill, toward, 0.22)]


# ---------- tower outlines ----------

def inset(points: list[tuple[float, float]], dist: float) -> list[tuple[float, float]]:
    """A convex polygon with every edge moved `dist` inward (outward if negative), so nested
    outlines keep an even gap on a triangle as well as on a hexagon."""
    if not dist:
        return list(points)
    n = len(points)
    cx, cy = sum(x for x, _ in points) / n, sum(y for _, y in points) / n
    lines = []
    for i, (ax, ay) in enumerate(points):
        bx, by = points[(i + 1) % n]
        length = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / length, (by - ay) / length
        nx, ny = -uy, ux
        if nx * (cx - ax) + ny * (cy - ay) < 0:
            nx, ny = uy, -ux
        lines.append(((ax + nx * dist, ay + ny * dist), (ux, uy)))
    out = []
    for i in range(n):
        (p1, u1), (p2, u2) = lines[i - 1], lines[i]
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        t = ((p2[0] - p1[0]) * u2[1] - (p2[1] - p1[1]) * u2[0]) / cross
        out.append((p1[0] + t * u1[0], p1[1] + t * u1[1]))
    return out
