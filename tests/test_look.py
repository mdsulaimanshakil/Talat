import itertools
import json
import math

import pytest

from talat.look import (
    FRAMES, PALETTES, SPEEDS, THEMES, TOWER_STYLES, Look, Settings, inset, load_settings, luminance, mix,
    save_settings, settings_path,
)


def test_defaults_are_the_recommended_look():
    look = Look()
    assert look.theme.name == "Midnight Brass" and look.style == "tiers"
    assert [look.colour_name(p) for p in (1, 2, 3)] == ["Ivory", "Onyx", "Copper"]
    assert look.frame == THEMES["midnight"].frame and look.coords and look.hints
    assert look.ai_delay == SPEEDS["normal"][1]


def test_settings_are_saved_and_read_back():
    save_settings(Settings(theme="jade", palette="cobalt", towers="outer", frame="none", coords=False, hints=False,
                           speed="fast"))
    s = load_settings()
    assert (s.theme, s.palette, s.towers, s.frame, s.coords, s.hints, s.speed) == \
        ("jade", "cobalt", "outer", "none", False, False, "fast")
    assert Look(s).frame is None and Look(s).ai_delay == SPEEDS["fast"][1]


def test_unknown_or_broken_settings_fall_back_to_the_defaults():
    folder = settings_path()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps({"theme": "neon", "palette": "cobalt", "coords": "yes",
                                                      "something": 1}))
    s = load_settings()
    assert s.theme == "midnight" and s.palette == "cobalt" and s.coords is True
    (folder / "settings.json").write_text("{ not json")
    assert load_settings() == Settings()


def test_every_option_has_a_name():
    for options in (THEMES, PALETTES):
        assert all(o.name for o in options.values())
    assert all(name for name, _ in TOWER_STYLES.values()) and all(name for name, _ in FRAMES.values())


@pytest.mark.parametrize("key", [k for k in PALETTES if k != "classic"])
def test_tower_colours_differ_in_lightness_too(key):
    """Seen in greyscale, on a small screen or by a colour-blind player, the three players' towers
    still look different: no two are close in lightness."""
    fills = [c.fill for c in PALETTES[key].colours.values()]
    for a, b in itertools.combinations(fills, 2):
        assert abs(luminance(a) - luminance(b)) >= 0.2


def test_stepped_tiers_get_lighter_or_darker_step_by_step():
    look = Look()
    for p in (1, 2, 3):
        tiers = [luminance(c) for c in look.tiers(p)]
        assert tiers == sorted(tiers) or tiers == sorted(tiers, reverse=True)
        assert len(set(tiers)) == 3


def test_mix():
    assert mix("#000000", "#FFFFFF", 0.5) == "#808080"
    assert mix("#123456", "#ABCDEF", 0) == "#123456"


def distance_to_line(p, a, b):
    return abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / math.dist(a, b)


@pytest.mark.parametrize("points", [
    [(0, 0), (4, 0), (4, 4), (0, 4)],                                   # square
    [(0, -10), (9.5, 6.2), (-9.5, 6.2)],                                # the tower triangle
    [(10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))) for a in range(0, 360, 60)],
])
def test_inset_moves_every_edge_in_by_the_same_distance(points):
    inner = inset(points, 1.5)
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        c, d = inner[i], inner[(i + 1) % n]
        assert distance_to_line(c, a, b) == pytest.approx(1.5)
        assert distance_to_line(d, a, b) == pytest.approx(1.5)
