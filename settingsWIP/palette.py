"""
Shared palette loader for the island and the settings panel.

Both widgets read the same ~/.config/<widget>/colors.css that matugen
regenerates from the wallpaper, and both need the same derived neutrals
(accent_muted, accent_dim) so the two panels sit in one visual family
instead of drifting apart. This module is the one place that logic lives.

island.py additionally computes @island_accent from the wallpaper itself
(see _pick_accent in island.py) -- that part is NOT duplicated here. The
settings panel doesn't need to re-derive an accent; it reads the same
colors.css file island already writes @island_accent into indirectly via
its own provider. Simplest correct approach: settings.py loads colors.css
(the plain matugen output, same file waybar/kitty/etc. use) and derives
its OWN accent tier the same way island does, from @primary, since the
settings panel is a separate GTK screen resource and can't reach into
island's live GtkStyleContext.
"""

import colorsys
import os

ACHROMATIC_SAT = 0.08

DEFAULT_PALETTE = {
    "primary": (0.55, 0.65, 0.95),
    "on_primary": (0.05, 0.06, 0.09),
    "on_surface": (0.89, 0.89, 0.91),
    "on_surface_variant": (0.77, 0.78, 0.83),
    "surface_container": (0.13, 0.13, 0.15),
    "outline": (0.55, 0.56, 0.61),
    "tertiary": (0.85, 0.70, 0.90),
    "error": (1.0, 0.71, 0.67),
    "background": (0.05, 0.06, 0.09),
    "shadow": (0.0, 0.0, 0.0),
}


def vivid(rgb, min_sat=0.58, lo=0.56, hi=0.72):
    """Same lift island.py applies to source_color -- see island.py for the
    full rationale. Kept identical here so a settings accent and the
    island's accent read as the same hue family when both derive from the
    same wallpaper."""
    h, l, sat = colorsys.rgb_to_hls(*rgb)
    if sat < ACHROMATIC_SAT:
        return None
    return colorsys.hls_to_rgb(h, min(hi, max(lo, l)), max(sat, min_sat))


def tone(rgb, sat, light):
    h = colorsys.rgb_to_hls(*rgb)[0]
    return colorsys.hls_to_rgb(h, light, sat)


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def parse_css_colors(css_text, base=None):
    """Parse @define-color lines out of a matugen-generated colors.css into
    an {name: (r, g, b)} dict with values in 0..1."""
    palette = dict(base or DEFAULT_PALETTE)
    for line in css_text.splitlines():
        line = line.strip()
        if not line.startswith("@define-color "):
            continue
        parts = line[len("@define-color "):].rstrip(";").split()
        if len(parts) != 2 or not parts[1].startswith("#"):
            continue
        hexval = parts[1][1:]
        if len(hexval) == 6:
            palette[parts[0]] = tuple(
                int(hexval[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return palette


def load_palette(colors_css_path):
    """Read a matugen colors.css and return a palette dict with the settings
    panel's own accent tiers derived from @primary, the same way island.py
    derives island_accent/_muted/_dim from source_color -- but from the
    already-generated matugen primary rather than re-sampling the wallpaper,
    since this module has no PIL dependency by design (keep the settings
    panel's Stage 1 dependency-free)."""
    try:
        with open(colors_css_path) as fh:
            css = fh.read()
    except OSError:
        css = ""
    palette = parse_css_colors(css)

    seed = palette.get("primary", DEFAULT_PALETTE["primary"])
    accent = vivid(seed) or seed
    palette["settings_accent"] = accent
    palette["settings_accent_muted"] = tone(accent, 0.20, 0.75)
    palette["settings_accent_dim"] = tone(accent, 0.15, 0.55)
    palette["on_primary"] = palette.get("background", DEFAULT_PALETTE["background"])
    return palette


def palette_to_css_header(palette):
    """Emit @define-color lines for the derived tiers so they can be
    concatenated ahead of colors.css + style.css, exactly like island.py's
    `header` variable in _load_css."""
    names = ("settings_accent", "settings_accent_muted", "settings_accent_dim")
    return "".join(
        "@define-color %s %s;\n" % (n, to_hex(palette[n]))
        for n in names if n in palette
    )
