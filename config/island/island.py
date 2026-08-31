#!/usr/bin/env python3
"""
Dynamic island for Hyprland.

A layer-shell overlay pinned to the top centre of the screen. Collapsed it is a
small pill showing whatever is most interesting right now; hovering it morphs
into a panel with the media player, volume/mic sliders and a do-not-disturb
toggle.

Colours come from ~/.config/island/colors.css, which matugen regenerates from
the wallpaper. A SIGUSR1 reloads them in place, so `retheme` re-skins the
island without restarting it.
"""

import os

# gir1.2-gtklayershell-0.1 is not installed system-wide; the typelib was
# unpacked into ~/.local instead, so point introspection at it before gi loads.
_LOCAL_GIR = os.path.expanduser("~/.local/lib/girepository-1.0")
if os.path.isdir(_LOCAL_GIR):
    os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
        filter(None, [_LOCAL_GIR, os.environ.get("GI_TYPELIB_PATH", "")]))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import (Gtk, Gdk, GLib, GdkPixbuf, GtkLayerShell, Pango,  # noqa: E402
                           PangoCairo)

import cairo
import colorsys
import hashlib
import math
import signal
import socket
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
CONF = os.path.join(HOME, ".config", "island")
CACHE = os.path.join(HOME, ".cache", "island")

PLAYERS = "spotify,%any"     # bare playerctl grabs a stale WebKit player
ICON_PREV = "\U000f04ae"
ICON_NEXT = "\U000f04ad"
ICON_PLAY = "\U000f040a"
ICON_PAUSE = "\U000f03e4"
MUTED_ICON = {"\U000f057e": "\U000f0581", "\U000f036c": "\U000f036d"}
DOUBLE_PRESS = getattr(Gdk.EventType, "_2BUTTON_PRESS",
                       getattr(Gdk.EventType, "DOUBLE_BUTTON_PRESS", None))

COLLAPSED_W = 210
EXPANDED_W = 400
MORPH_MS = 320
LEAVE_GRACE_MS = 260
MARGIN_TOP = 3             # resting gap below the top edge
DRAG_SLOP = 4              # px of movement before a click becomes a drag
HOME_MS = 420              # double-click glide back to the home position
DOCK_Y = 26                # within this of the top, the island counts as docked
SNAP_MS = 220              # glide that settles it back onto the top rail
CLOSE_HOLD_MS = 70         # let the panel fade before its height starts moving
CLOSE_FADE_MS = 140
CLOSE_REVEAL_MS = 230
ART_PX = 80
CAVA_BARS = 30
VOLUME_POPUP_S = 1.6


def run(*args, **kw):
    """Fire-and-read a short command. Returns stripped stdout, or '' on failure."""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=2, **kw
        ).stdout.strip()
    except Exception:
        return ""


def spawn(*args):
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


_HYPR_SOCK = None


def hypr_cursor():
    """The cursor position straight from the compositor, in layout pixels.

    Dragging cannot be driven from the pointer coordinates in motion events:
    those are relative to the island's own surface, so moving the island moves
    the ruler being measured with. Hyprland reports the pointer's surface-local
    position several frames behind our own margin changes, and feeding that
    back in at unity gain makes the position ring -- measured at +-60px, four
    times a second, during a perfectly steady drag. This is an *independent*
    measurement, so there is no loop to ring. The round trip on Hyprland's IPC
    socket is 0.03ms, which is nothing next to the 16ms frame it serves.
    """
    global _HYPR_SOCK
    if _HYPR_SOCK is None:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        run = os.environ.get("XDG_RUNTIME_DIR")
        _HYPR_SOCK = f"{run}/hypr/{sig}/.socket.sock" if sig and run else ""
    if not _HYPR_SOCK:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sk:
            sk.settimeout(0.05)
            sk.connect(_HYPR_SOCK)
            sk.sendall(b"cursorpos")
            x, y = sk.recv(64).decode().split(",")
        return float(x), float(y)
    except Exception:
        return None


def ease(t):
    """cubic ease-out, the same curve the CSS transitions use"""
    return 1 - pow(1 - t, 3)


def approach(current, target, dt, rate):
    """Frame-rate independent glide towards a target."""
    return current + (target - current) * min(1.0, dt * rate)


# Below this saturation a wallpaper has no real colour, and whatever hue
# matugen reports is extraction noise -- black.png yields #96ac9e (sat 0.12),
# which a saturation floor would turn into a vivid invented green.
ACHROMATIC_SAT = 0.18

# How much of the wallpaper actually carries colour. matugen only reports a
# single seed, which says nothing about how much of the image it covers --
# windows-11-dark yields a vivid #4285f4 from a ribbon on an otherwise black
# picture, and colouring the whole island from that looks wrong.
COLOUR_MASS_NONE = 0.05   # below this: no real colour anywhere, go pale
COLOUR_MASS_LOW = 0.20    # sparse colour: only trust a strongly saturated seed
SEED_SAT_STRONG = 0.32

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".gif")

# What a monochrome wallpaper gets instead: near-white with the faintest cool
# cast (#dee8f2). Reads as "no colour" rather than a colour nobody asked for.
PALE_ACCENT = colorsys.hls_to_rgb(0.58, 0.91, 0.35)


def wallpaper_frame():
    """The image to analyse: the wallpaper itself, or the still that retheme
    extracts for video wallpapers."""
    try:
        with open(os.path.join(HOME, ".cache", "current_wallpaper")) as fh:
            wp = fh.read().strip()
    except OSError:
        return None
    if os.path.splitext(wp)[1].lower() in VIDEO_EXTS:
        frame = os.path.join(HOME, ".cache", "wallpaper-frame.png")
        return frame if os.path.exists(frame) else None
    return wp if os.path.exists(wp) else None


def colour_mass(path):
    """Fraction of the image made of pixels with real, visible colour.

    Returns None if it cannot be measured, so callers fall back to judging the
    seed colour alone.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(path)
        im.draft("RGB", (110, 110))        # cheap decode for large JPEGs
        im = im.convert("RGB")
        im.thumbnail((110, 110))
    except Exception:
        return None
    px = list(im.getdata())
    if not px:
        return None
    hit = 0
    for r, g, b in px:
        _h, l, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if sat > 0.25 and 0.16 < l < 0.92:
            hit += 1
    return hit / len(px)


def read_overrides():
    """`accents.conf`: one `match = white|auto|#rrggbb` per line, where match is
    any substring of the wallpaper's filename. First match wins."""
    rules = []
    try:
        with open(os.path.join(CONF, "accents.conf")) as fh:
            for line in fh:
                line = line.strip()
                # only whole-line comments: an inline '#' would eat hex values
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = (x.strip() for x in line.split("=", 1))
                if key and val:
                    rules.append((key.lower(), val.lower()))
    except OSError:
        pass
    return rules


def vivid(rgb, min_sat=0.58, lo=0.56, hi=0.72):
    """Lift a colour into a range that reads on a dark glass surface.

    matugen's dark-mode `primary` is a pastel by design -- a strong red
    wallpaper (#ce4222) becomes #ffb4a3, so every wallpaper ends up looking
    much the same. The island samples `source_color` (the wallpaper's actual
    dominant colour) instead and only corrects it enough to stay legible:
    hue is untouched, saturation gets a floor, lightness a band.

    Returns None when the source is effectively colourless, so the caller can
    fall back to PALE_ACCENT rather than invent a hue.
    """
    h, l, sat = colorsys.rgb_to_hls(*rgb)
    if sat < ACHROMATIC_SAT:
        return None
    return colorsys.hls_to_rgb(h, min(hi, max(lo, l)), max(sat, min_sat))


def tone(rgb, sat, light):
    """Recolour to a given saturation/lightness, keeping the hue.

    Used to build the island's neutrals. matugen's `on_surface_variant` is a
    warm grey (#c4c4bd), which clashes against a cool accent -- deriving the
    greys from the accent's own hue keeps the whole panel in one family.
    """
    h = colorsys.rgb_to_hls(*rgb)[0]
    return colorsys.hls_to_rgb(h, light, sat)


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


DEFAULT_PALETTE = {
    "primary": (0.55, 0.65, 0.95),
    "accent": (0.55, 0.65, 0.95),
    "accent_soft": (0.30, 0.36, 0.55),
    "on_primary": (0.05, 0.06, 0.09),
    "on_surface": (0.89, 0.89, 0.91),
    "on_surface_variant": (0.77, 0.78, 0.83),
    "outline": (0.55, 0.56, 0.61),
    "accent_muted": (0.72, 0.75, 0.85),
    "accent_dim": (0.46, 0.50, 0.60),
    "tertiary": (0.85, 0.70, 0.90),
    "error": (1.0, 0.71, 0.67),
}


class Themed:
    """Mixin for the cairo widgets, which cannot read GTK's CSS colours."""

    palette = DEFAULT_PALETTE

    def set_palette(self, palette):
        self.palette = palette
        self.queue_draw()

    def col(self, name):
        return self.palette.get(name, DEFAULT_PALETTE.get(name, (1, 1, 1)))


def hms(us):
    s = int(us) // 1_000_000
    return "%d:%02d" % (s // 60, s % 60)


# --------------------------------------------------------------------------
# data sources
# --------------------------------------------------------------------------

class Player:
    """One playerctl round trip per poll, unpacked into attributes."""

    FMT = ("{{status}}\x1f{{xesam:title}}\x1f{{xesam:artist}}\x1f{{xesam:album}}"
           "\x1f{{mpris:length}}\x1f{{position}}\x1f{{mpris:artUrl}}")

    def __init__(self):
        self.status = ""
        self.title = self.artist = self.album = ""
        self.length = self.position = 0
        self.art_url = ""

    @property
    def active(self):
        return self.status in ("Playing", "Paused") and bool(self.title)

    def poll(self):
        out = run("playerctl", "-p", PLAYERS, "metadata", "--format", self.FMT)
        if not out:
            self.status = ""
            self.title = ""
            return
        f = out.split("\x1f")
        f += [""] * (7 - len(f))
        self.status, self.title, self.artist, self.album = f[0], f[1], f[2], f[3]
        self.length = int(f[4]) if f[4].isdigit() else 0
        self.position = int(f[5]) if f[5].isdigit() else 0
        self.art_url = f[6]

    @staticmethod
    def cmd(action):
        spawn("playerctl", "-p", PLAYERS, action)

    @staticmethod
    def seek(seconds):
        spawn("playerctl", "-p", PLAYERS, "position", str(int(seconds)))


class Audio:
    """wireplumber volumes. wpctl prints 'Volume: 0.60' or 'Volume: 0.60 [MUTED]'."""

    SINK = "@DEFAULT_AUDIO_SINK@"
    SOURCE = "@DEFAULT_AUDIO_SOURCE@"

    @staticmethod
    def _read(target):
        out = run("wpctl", "get-volume", target)
        if not out:
            return 0, False
        parts = out.split()
        try:
            vol = int(round(float(parts[1]) * 100))
        except (IndexError, ValueError):
            vol = 0
        return vol, "[MUTED]" in out

    @classmethod
    def sink(cls):
        return cls._read(cls.SINK)

    @classmethod
    def source(cls):
        return cls._read(cls.SOURCE)

    @staticmethod
    def set_volume(target, pct):
        spawn("wpctl", "set-volume", "-l", "1.5", target, "%d%%" % pct)

    @staticmethod
    def toggle_mute(target):
        spawn("wpctl", "set-mute", target, "toggle")


class Dnd:
    """mako modes. ~/.config/mako/config defines the do-not-disturb block."""

    MODE = "do-not-disturb"

    @classmethod
    def enabled(cls):
        return cls.MODE in run("makoctl", "mode").splitlines()

    @classmethod
    def set(cls, on):
        spawn("makoctl", "mode", "-a" if on else "-r", cls.MODE)


class Cava:
    """A private cava instance, started only while the panel is open."""

    CONF = os.path.join(CACHE, "cava.conf")

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.proc = None
        self._write_conf()

    def _write_conf(self):
        # cava 0.7.4 has no pipewire backend on this box; pulse reads the
        # pipewire-pulse shim just fine.
        with open(self.CONF, "w") as fh:
            fh.write(
                "[general]\n"
                "bars = %d\n"
                "framerate = 60\n"
                # autosens on its own pins half the bars at 100 during normal
                # playback; a lower starting sensitivity keeps headroom.
                "autosens = 1\n"
                "sensitivity = 40\n"
                "lower_cutoff_freq = 40\n"
                "higher_cutoff_freq = 12000\n"
                "[input]\nmethod = pulse\nsource = auto\n"
                "[output]\nmethod = raw\nraw_target = /dev/stdout\n"
                "data_format = ascii\nascii_max_range = 100\n"
                # cava defaults to stereo, which mirrors the left channel
                # against the right -- the bar list comes back a palindrome and
                # renders as a symmetric wall with a spike in the middle.
                "channels = mono\nmono_option = average\n"
                "[smoothing]\n"
                # monstercat smoothing drags neighbouring bars up to the peak;
                # at 1.4 a loud passage flattened the whole row into one block.
                "monstercat = 0\n"
                "waves = 0\n"
                "gravity = 100\n"
                "noise_reduction = 66\n" % CAVA_BARS
            )

    def start(self):
        if self.proc:
            return
        try:
            self.proc = subprocess.Popen(
                ["cava", "-p", self.CONF],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
        except Exception:
            self.proc = None
            return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        for line in proc.stdout:
            if proc is not self.proc:
                return
            vals = [int(v) for v in line.strip().rstrip(";").split(";") if v.isdigit()]
            if vals:
                GLib.idle_add(self.on_frame, vals)

    def stop(self):
        p, self.proc = self.proc, None
        if p:
            try:
                p.terminate()
            except Exception:
                pass


class ArtLoader:
    """Downloads mpris:artUrl once per track and caches it under ~/.cache/island."""

    def __init__(self, on_ready):
        self.on_ready = on_ready
        self.current = None

    def request(self, url):
        if url == self.current:
            return
        self.current = url
        if not url:
            GLib.idle_add(self.on_ready, None)
            return
        threading.Thread(target=self._fetch, args=(url,), daemon=True).start()

    def _fetch(self, url):
        if url.startswith("file://"):
            path = url[7:]
        else:
            path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".img")
            if not os.path.exists(path):
                try:
                    subprocess.run(
                        ["curl", "-fsSL", "--max-time", "8", "-o", path, url],
                        capture_output=True, timeout=12,
                    )
                except Exception:
                    return
        if url != self.current or not os.path.exists(path):
            return
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, ART_PX, ART_PX, True)
        except Exception:
            return
        GLib.idle_add(self.on_ready, pb)


# --------------------------------------------------------------------------
# widgets
# --------------------------------------------------------------------------

class Artwork(Gtk.DrawingArea, Themed):
    """Album art with rounded corners. GTK3 will not clip a child image to a
    border-radius, so the rounding is done in cairo."""

    def __init__(self):
        super().__init__()
        self.set_size_request(ART_PX, ART_PX)
        self.get_style_context().add_class("cairo-widget")
        self.pixbuf = None
        self.connect("draw", self._draw)

    def set_pixbuf(self, pb):
        self.pixbuf = pb
        self.queue_draw()

    def _rounded(self, cr, w, h, r):
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _draw(self, _w, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        self._rounded(cr, w, h, 12)
        cr.clip()
        if self.pixbuf:
            # cover-fit: scale the short edge up, centre the overflow
            pw, ph = self.pixbuf.get_width(), self.pixbuf.get_height()
            s = max(w / pw, h / ph)
            cr.save()
            cr.translate((w - pw * s) / 2, (h - ph * s) / 2)
            cr.scale(s, s)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            # no art yet: a tinted plate with three descending bars
            cr.set_source_rgba(*self.col("accent"), 0.14)
            cr.paint()
            cr.set_source_rgba(*self.col("accent"), 0.45)
            bw = w * 0.09
            for i, frac in enumerate((0.30, 0.46, 0.22)):
                cr.rectangle(w / 2 - bw * 2.4 + i * bw * 2.4,
                             h * (0.5 - frac / 2), bw, h * frac)
            cr.fill()

        # hairline ring, tinted by the accent, drawn inside the clip
        cr.set_source_rgba(*self.col("accent"), 0.28)
        cr.set_line_width(2)
        self._rounded(cr, w, h, 12)
        cr.stroke()
        return False


class Spectrum(Gtk.DrawingArea, Themed):
    """cava bars, drawn as rounded columns in the accent colour."""

    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 34)
        self.get_style_context().add_class("cairo-widget")
        self.values = [0.0] * CAVA_BARS     # target, straight from cava
        self.display = [0.0] * CAVA_BARS    # what is actually drawn
        self._tick_id = 0
        self._last = 0.0
        self.connect("draw", self._draw)

    def feed(self, vals):
        """cava delivers steps; the widget eases between them so the bars read
        as motion rather than a strobe."""
        if len(vals) != len(self.values):
            self.values = [0.0] * len(vals)
            self.display = [0.0] * len(vals)
        self.values = [float(v) for v in vals]
        if not self._tick_id:
            self._last = 0.0
            self._tick_id = self.add_tick_callback(self._step)
        return False

    def _step(self, _w, clock):
        now = clock.get_frame_time() / 1_000_000.0
        dt = 0.016 if not self._last else min(0.05, now - self._last)
        self._last = now
        moved = False
        for i, target in enumerate(self.values):
            # rises snap, falls drift -- the usual visualiser asymmetry
            rate = 30.0 if target > self.display[i] else 11.0
            nxt = approach(self.display[i], target, dt, rate)
            if abs(nxt - self.display[i]) > 0.05:
                moved = True
            self.display[i] = nxt
        self.queue_draw()
        if not moved:
            self._tick_id = 0
            return False
        return True

    def clear(self):
        self.values = [0.0] * len(self.values)

    def _draw(self, _w, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        n = len(self.display) or 1
        slot = w / n
        bw = max(2.0, slot * 0.46)
        for i, v in enumerate(self.display):
            # a gamma curve lifts the quiet bars so the row reads as a spectrum
            # instead of two spikes over a flat line
            level = pow(min(v, 100.0) / 100.0, 0.8)
            bh = max(2.0, h * level)
            x = i * slot + (slot - bw) / 2
            y = h - bh
            r = bw / 2
            cr.set_source_rgba(*self.col("accent"), 0.16 + 0.78 * level)
            if bh <= bw:
                cr.rectangle(x, y, bw, bh)
            else:
                cr.new_sub_path()
                cr.arc(x + r, y + r, r, math.pi, 2 * math.pi)
                cr.line_to(x + bw, h - r)
                cr.arc(x + r, h - r, r, 0, math.pi)
                cr.close_path()
            cr.fill()
        return False


class SliderRow(Gtk.Box):
    """icon + scale + a click target on the icon for mute."""

    def __init__(self, icon, on_change, on_mute):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.get_style_context().add_class("slider-row")
        self.icon_name = icon
        self.muted_icon = MUTED_ICON.get(icon, icon)

        self.btn = IconButton(icon, on_mute, size=28, font_px=14)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.get_style_context().add_class("slider")
        self._guard = False
        self._on_change = on_change
        self._pending = None
        self._flush_src = 0
        self.scale.connect("value-changed", self._changed)

        self.label = Gtk.Label(label="0%")
        self.label.get_style_context().add_class("slider-value")
        self.label.set_width_chars(4)
        self.label.set_xalign(1.0)

        self.pack_start(self.btn, False, False, 0)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.label, False, False, 0)

    def _changed(self, scale):
        """Coalesce drag updates: wpctl is a process spawn per call."""
        if self._guard:
            return
        self._pending = int(scale.get_value())
        if not self._flush_src:
            self._flush_src = GLib.timeout_add(70, self._flush)

    def _flush(self):
        self._flush_src = 0
        if self._pending is not None:
            self._on_change(self._pending)
            self._pending = None
        return False

    def sync(self, value, muted):
        self._guard = True
        if int(self.scale.get_value()) != value:
            self.scale.set_value(value)
        self._guard = False
        self.label.set_text("%d%%" % value)
        self.btn.set_tint("error" if muted else None)
        self.btn.set_glyph(self.muted_icon if muted else self.icon_name)


class IconButton(Gtk.DrawingArea, Themed):
    """A cairo-drawn button.

    GTK 3.24 has no CSS `transform`, so hover swell, the press ripple and the
    play/pause glyph morph are all drawn by hand. Animation runs off the frame
    clock and the tick callback removes itself once everything settles, so an
    idle island costs nothing.
    """

    def __init__(self, glyph, on_click, size=32, filled=False, font_px=15):
        super().__init__()
        # The widget is deliberately larger than the circle it draws: a
        # DrawingArea clips to its allocation, and the filled button's hover
        # glow (1.34x radius, on top of a 1.05x hover swell) was being cut into
        # a visible box. Unfilled buttons only need room for the swell.
        pad = math.ceil(size / 2 * (1.45 * 1.05 - 1)) + 1 if filled else 3
        self.set_size_request(size + 2 * pad, size + 2 * pad)
        self.get_style_context().add_class("cairo-widget")
        self.size = size
        self.filled = filled
        self.font_px = font_px
        self.on_click = on_click

        self.glyph = glyph
        self.old_glyph = None
        self.morph = 1.0        # 0 -> old glyph, 1 -> current glyph
        self.hover = 0.0
        self.hovered = False
        self.pressed = False
        self.press = 0.0        # depth of the push-in
        self.ripple = -1.0      # seconds since the click, <0 when idle
        self.tint = None        # palette key overriding the resting fg colour

        self._tick_id = 0
        self._last = 0.0

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.connect("draw", self._draw)
        self.connect("enter-notify-event", self._enter)
        self.connect("leave-notify-event", self._leave)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", self._release)

    # -- state ------------------------------------------------------------

    def set_glyph(self, glyph):
        """Swap the icon with a crossfade instead of an instant flip."""
        if glyph == self.glyph:
            return
        self.old_glyph = self.glyph
        self.glyph = glyph
        self.morph = 0.0
        self._animate()

    def set_tint(self, key):
        if key != self.tint:
            self.tint = key
            self.queue_draw()

    def _enter(self, *_):
        self.hovered = True
        self._animate()
        return False

    def _leave(self, *_):
        self.hovered = False
        self.pressed = False
        self._animate()
        return False

    def _press(self, _w, ev):
        if ev.button != 1:
            return False
        self.pressed = True
        self.ripple = 0.0
        self._animate()
        return True

    def _release(self, _w, ev):
        if ev.button != 1:
            return False
        was = self.pressed
        self.pressed = False
        self._animate()
        if was and self.on_click:
            self.on_click()
        return True

    # -- animation --------------------------------------------------------

    def _animate(self):
        if self._tick_id:
            return
        self._last = 0.0
        self._tick_id = self.add_tick_callback(self._step)

    def _step(self, _w, clock):
        now = clock.get_frame_time() / 1_000_000.0
        dt = 0.016 if not self._last else min(0.05, now - self._last)
        self._last = now

        self.hover = approach(self.hover, 1.0 if self.hovered else 0.0, dt, 16)
        self.press = approach(self.press, 1.0 if self.pressed else 0.0, dt, 26)
        if self.morph < 1.0:
            self.morph = min(1.0, self.morph + dt * 5.5)
        if self.ripple >= 0.0:
            self.ripple += dt
            if self.ripple > 0.45:
                self.ripple = -1.0

        self.queue_draw()

        settled = (
            abs(self.hover - (1.0 if self.hovered else 0.0)) < 0.004
            and abs(self.press - (1.0 if self.pressed else 0.0)) < 0.004
            and self.morph >= 1.0 and self.ripple < 0.0
        )
        if settled:
            self.hover = 1.0 if self.hovered else 0.0
            self.press = 1.0 if self.pressed else 0.0
            self._tick_id = 0
            return False
        return True

    # -- drawing ----------------------------------------------------------

    def _glyph(self, cr, text, cx, cy, alpha, scale, rgb):
        if not text or alpha <= 0.01:
            return
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription("JetBrainsMono Nerd Font")
        # absolute size keeps the icons honest on this monitor's lying EDID
        fd.set_absolute_size(self.font_px * Pango.SCALE)
        layout.set_font_description(fd)
        layout.set_text(text, -1)
        w, h = layout.get_pixel_size()
        cr.save()
        cr.translate(cx, cy)
        cr.scale(scale, scale)
        cr.set_source_rgba(*rgb, alpha)
        cr.move_to(-w / 2.0, -h / 2.0)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _draw(self, _w, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        cx, cy = w / 2.0, h / 2.0
        r = self.size / 2.0

        # the whole button eases down slightly while held
        sink = 1.0 - 0.07 * self.press
        radius = r * (1.0 + 0.05 * self.hover) * sink

        if self.filled:
            base = self.col("accent")
            bg_a = 1.0
            fg = self.col("on_primary")
            glow = 0.24 * self.hover
            if glow > 0.01:
                # a flat translucent circle reads as an ugly hard ring; fade it
                outer = radius * 1.45
                halo = cairo.RadialGradient(cx, cy, radius * 0.9, cx, cy, outer)
                halo.add_color_stop_rgba(0.0, *base, glow)
                halo.add_color_stop_rgba(1.0, *base, 0.0)
                cr.set_source(halo)
                cr.arc(cx, cy, outer, 0, 2 * math.pi)
                cr.fill()
        else:
            base = self.col("on_surface")
            bg_a = 0.05 + 0.11 * self.hover
            rest = self.col(self.tint) if self.tint else self.col("accent_muted")
            hot = self.col(self.tint) if self.tint else self.col("accent")
            fg = tuple(o + (p - o) * self.hover for o, p in zip(rest, hot))

        cr.set_source_rgba(*base, bg_a)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()

        # click ripple, clipped to the button so it reads as a fill sweep
        if self.ripple >= 0.0:
            t = min(1.0, self.ripple / 0.45)
            cr.save()
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.clip()
            ripple_rgb = self.col("on_primary") if self.filled else self.col("accent")
            cr.set_source_rgba(*ripple_rgb, 0.34 * (1.0 - t))
            cr.arc(cx, cy, radius * (0.15 + 1.15 * ease(t)), 0, 2 * math.pi)
            cr.fill()
            cr.restore()

        gs = sink * (1.0 + 0.06 * self.hover)
        if self.morph < 1.0 and self.old_glyph:
            m = ease(self.morph)
            self._glyph(cr, self.old_glyph, cx, cy, 1.0 - m, gs * (1.0 - 0.35 * m), fg)
            self._glyph(cr, self.glyph, cx, cy, m, gs * (0.62 + 0.38 * m), fg)
        else:
            self._glyph(cr, self.glyph, cx, cy, 1.0, gs, fg)
        return False


# --------------------------------------------------------------------------
# the island
# --------------------------------------------------------------------------

class Island:
    def __init__(self):
        self.player = Player()
        self.art = ArtLoader(self._on_art)
        self.cava = Cava(self._on_cava)
        self.expanded = False
        self.pinned = False        # SIGUSR2 holds the panel open (Super+I)
        self.dragging = False
        self.collapse_src = 0
        self.reveal_src = 0
        self.morph_src = 0
        self.fade_src = 0
        self.volume_until = 0.0
        self.last_sink_vol = None
        self.palette = dict(DEFAULT_PALETTE)
        self.optimistic = None     # (expected status, deadline) after a click

        # position: offsets from the home spot (top centre). The surface is
        # anchored top-left and placed by hand so that widening on expand still
        # grows symmetrically around wherever it has been dragged to.
        self.off_x = 0.0
        self.off_y = 0.0
        self._cur_w = COLLAPSED_W
        self.home_src = 0
        self.docked = True         # sitting on the top rail, in waybar's row
        self._press_at = None      # (x, y) of the button press, widget coords
        self._drag_live = False
        self._drag_tick = 0
        self._pending = None       # newest un-applied drag delta (fallback)
        self._grab = None          # (cursor at grab, offset at grab)
        self._last_margin = None

        self._build()
        self._load_css()
        self.win.show_all()
        self.panel_revealer.set_reveal_child(False)
        self._set_width(self._pill_width())

        GLib.timeout_add(1000, self._tick)
        GLib.timeout_add(250, self._fast_tick)
        threading.Thread(target=self._watch_audio, daemon=True).start()
        self._tick()

    # -- construction ------------------------------------------------------

    def _build(self):
        self.win = Gtk.Window()
        # Belt and braces for a genuinely transparent toplevel: no CSD frame,
        # an RGBA visual, app-paintable, and the draw handler below. (The grey
        # rectangle that plagued this was none of those -- see _clear_background.)
        self.win.set_decorated(False)
        self.win.set_app_paintable(True)
        vis = self.win.get_screen().get_rgba_visual()
        if vis:
            self.win.set_visual(vis)

        self.win.connect("draw", self._clear_background)

        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_namespace(self.win, "island")
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.TOP, True)
        # Anchoring left as well turns the margins into absolute coordinates,
        # which is what makes the island draggable; _apply_position() then does
        # the horizontal centring the compositor used to do for us.
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, MARGIN_TOP)
        # -1 = ignore other surfaces' exclusive zones (so it overlaps the bar
        # instead of being pushed below it) while claiming none of its own.
        GtkLayerShell.set_exclusive_zone(self.win, -1)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.get_style_context().add_class("island")

        # --- collapsed pill ---
        self.pill_icon = Gtk.Label()
        self.pill_icon.get_style_context().add_class("pill-icon")
        self.pill_text = Gtk.Label()
        self.pill_text.get_style_context().add_class("pill-text")
        self.pill_text.set_ellipsize(Pango.EllipsizeMode.END)
        self.pill_text.set_max_width_chars(30)

        self.pill = pill = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        pill.get_style_context().add_class("pill")
        pill.set_halign(Gtk.Align.CENTER)
        pill.pack_start(self.pill_icon, False, False, 0)
        pill.pack_start(self.pill_text, False, False, 0)

        # --- panel ---
        self.artwork = Artwork()
        self.title = Gtk.Label(xalign=0.0)
        self.title.get_style_context().add_class("track-title")
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.set_max_width_chars(24)
        self.artist = Gtk.Label(xalign=0.0)
        self.artist.get_style_context().add_class("track-artist")
        self.artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist.set_max_width_chars(28)

        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1000, 1)
        self.seek.set_draw_value(False)
        self.seek.get_style_context().add_class("seek")
        self.seek_guard = False
        self.seek.connect("button-press-event", self._drag_start)
        self.seek.connect("button-release-event", self._seek_commit)
        self.seek.connect("value-changed", self._seek_moved)

        self.time_now = Gtk.Label(label="0:00", xalign=0.0)
        self.time_now.get_style_context().add_class("time")
        self.time_end = Gtk.Label(label="0:00", xalign=1.0)
        self.time_end.get_style_context().add_class("time")
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        times.pack_start(self.time_now, False, False, 0)
        times.pack_end(self.time_end, False, False, 0)

        # the buttons carry their own padding for the glow, so spacing is small
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        controls.set_halign(Gtk.Align.CENTER)
        self.prev_btn = IconButton(ICON_PREV, lambda: Player.cmd("previous"),
                                   size=36, font_px=17)
        self.play_btn = IconButton(ICON_PLAY, self._toggle_play,
                                   size=54, filled=True, font_px=22)
        self.next_btn = IconButton(ICON_NEXT, lambda: Player.cmd("next"),
                                   size=36, font_px=17)
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            controls.pack_start(b, False, False, 0)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_valign(Gtk.Align.CENTER)
        meta.pack_start(self.title, False, False, 0)
        meta.pack_start(self.artist, False, False, 0)
        meta.pack_start(self.seek, False, False, 4)
        meta.pack_start(times, False, False, 0)

        media = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        media.pack_start(self.artwork, False, False, 0)
        media.pack_start(meta, True, True, 0)

        self.spectrum = Spectrum()

        self.vol_row = SliderRow(
            "󰕾",
            lambda v: Audio.set_volume(Audio.SINK, v),
            lambda: Audio.toggle_mute(Audio.SINK),
        )
        self.mic_row = SliderRow(
            "󰍬",
            lambda v: Audio.set_volume(Audio.SOURCE, v),
            lambda: Audio.toggle_mute(Audio.SOURCE),
        )
        for row in (self.vol_row, self.mic_row):
            row.scale.connect("button-press-event", self._drag_start)
            row.scale.connect("button-release-event", self._drag_end)

        self.dnd_btn = Gtk.Button()
        self.dnd_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.dnd_btn.get_style_context().add_class("dnd")
        self.dnd_label = Gtk.Label(label="󰂚  Notifications on")
        self.dnd_btn.add(self.dnd_label)
        self.dnd_btn.connect("clicked", self._toggle_dnd)

        self.panel = panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.get_style_context().add_class("panel")
        panel.set_opacity(0.0)
        panel.pack_start(media, False, False, 0)
        panel.pack_start(controls, False, False, 2)
        panel.pack_start(self.spectrum, True, True, 0)
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                         False, False, 0)
        panel.pack_start(self.vol_row, False, False, 0)
        panel.pack_start(self.mic_row, False, False, 0)
        panel.pack_start(self.dnd_btn, False, False, 0)

        self.icon_buttons = [self.prev_btn, self.play_btn, self.next_btn,
                             self.vol_row.btn, self.mic_row.btn]

        self.panel_revealer = Gtk.Revealer()
        # SLIDE_DOWN anchors the child to the bottom of the growing box, so the
        # panel's *lower* edge is revealed first and it reads as cropped.
        # SLIDE_UP anchors it to the top, which unrolls out of the pill.
        self.panel_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP)
        self.panel_revealer.set_transition_duration(MORPH_MS)
        self.panel_revealer.add(panel)

        self.root.pack_start(pill, False, False, 0)
        self.root.pack_start(self.panel_revealer, False, False, 0)

        ebox = Gtk.EventBox()
        ebox.add(self.root)
        ebox.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        ebox.connect("enter-notify-event", self._on_enter)
        ebox.connect("leave-notify-event", self._on_leave)
        # Only presses the controls did not want reach here, so grabbing the
        # play button or a slider still does what it always did.
        ebox.connect("button-press-event", self._win_press)
        ebox.connect("motion-notify-event", self._win_motion)
        ebox.connect("button-release-event", self._win_release)
        self.win.add(ebox)

    @staticmethod
    def _clear_background(_w, cr):
        """Punch the toplevel to fully transparent before anything else draws.

        Returning False lets the normal draw continue on top.

        Note for future debugging: the grey rectangle that used to surround the
        island was NOT this, and not the compositor blur either (it survived
        turning blur off). It was the `box-shadow` on .island -- see style.css.
        """
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.restore()
        return False

    # -- theming -----------------------------------------------------------

    def _load_css(self):
        """colors.css (matugen) and style.css load as one provider: in GTK3 an
        @define-color is only visible inside the provider that declared it.

        The palette is parsed out first so the island's own accent can be
        computed and injected as @island_accent before anything is loaded.
        """
        css = ""
        for name in ("colors.css", "style.css"):
            try:
                with open(os.path.join(CONF, name)) as fh:
                    css += fh.read() + "\n"
            except OSError:
                pass

        # The cairo widgets cannot read GTK colours, so every @define-color is
        # parsed into a palette they can sample.
        palette = dict(DEFAULT_PALETTE)
        for line in css.splitlines():
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

        # matugen has no on-accent tone that reads well; the background is what
        # the rest of the rice uses for that job.
        palette["on_primary"] = palette.get("background", (0, 0, 0))

        # The island's own accent, punchier and far more wallpaper-specific
        # than matugen's pastel `primary`.
        palette["accent"] = self._pick_accent(palette)
        palette["accent_soft"] = (vivid(palette["accent"], 0.45, 0.38, 0.44)
                                  or palette["accent"])
        # neutrals tinted towards the accent's hue rather than matugen's warm grey
        palette["accent_muted"] = tone(palette["accent"], 0.20, 0.75)
        palette["accent_dim"] = tone(palette["accent"], 0.15, 0.55)
        self.palette = palette
        for widget in self._themed():
            widget.set_palette(palette)

        if not hasattr(self, "provider"):
            self.provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), self.provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        header = "".join(
            "@define-color island_%s %s;\n" % (name, to_hex(palette[key]))
            for name, key in (("accent", "accent"),
                              ("accent_soft", "accent_soft"),
                              ("accent_muted", "accent_muted"),
                              ("accent_dim", "accent_dim")))
        try:
            self.provider.load_from_data((header + css).encode())
        except GLib.Error as exc:
            print("island: css error:", exc)

    def _pick_accent(self, palette):
        """Decide the island's accent for the current wallpaper.

        matugen only reports a seed colour, which says nothing about how much
        of the picture carries it. windows-11-dark yields a vivid #4285f4 from
        a ribbon on an otherwise black image; colouring the island from that
        reads as arbitrary. So the image itself is measured too, and a
        wallpaper that is mostly dark or grey gets the pale accent.
        """
        wallpaper = wallpaper_frame()
        name = os.path.basename(wallpaper or "").lower()

        for match, value in read_overrides():
            if match and match in name:
                if value == "auto":
                    break
                if value in ("white", "pale"):
                    return PALE_ACCENT
                if value.startswith("#") and len(value) == 7:
                    try:
                        return tuple(int(value[1:][i:i + 2], 16) / 255
                                     for i in (0, 2, 4))
                    except ValueError:
                        pass
                break

        seed = palette.get("source_color")
        if seed is None:
            return palette.get("primary", DEFAULT_PALETTE["primary"])
        seed_sat = colorsys.rgb_to_hls(*seed)[2]
        mass = colour_mass(wallpaper) if wallpaper else None

        if mass is not None:
            if mass < COLOUR_MASS_NONE:
                return PALE_ACCENT           # no real colour anywhere
            if mass < COLOUR_MASS_LOW and seed_sat < SEED_SAT_STRONG:
                return PALE_ACCENT           # sparse colour from a weak seed
        return vivid(seed) or PALE_ACCENT

    def _themed(self):
        return [self.artwork, self.spectrum, *self.icon_buttons]

    def reload(self, *_):
        self._load_css()
        return True

    def toggle_pin(self, *_):
        """Keep the panel open regardless of the pointer. Bound to Super+I."""
        self.pinned = not self.pinned
        ctx = self.root.get_style_context()
        if self.pinned:
            ctx.add_class("pinned")
            self._expand()
        else:
            ctx.remove_class("pinned")
            self._collapse()
        return True

    # -- expand / collapse -------------------------------------------------

    def _on_enter(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.collapse_src:
            GLib.source_remove(self.collapse_src)
            self.collapse_src = 0
        self._expand()
        return False

    def _on_leave(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.dragging or self.pinned or not self.docked:
            return False
        if self.collapse_src:
            GLib.source_remove(self.collapse_src)
        self.collapse_src = GLib.timeout_add(LEAVE_GRACE_MS, self._collapse)
        return False

    def _expand(self):
        if self.expanded:
            return
        self.expanded = True
        self.root.get_style_context().add_class("open")
        self._render_pill()
        self._reveal(True, MORPH_MS)
        self._morph(EXPANDED_W, 170)      # width first, so nothing is cut off
        self._fade(1.0, 300)
        self._sync_audio()
        self.cava.start()

    def _collapse(self):
        self.collapse_src = 0
        if not self.expanded:
            return False
        self.expanded = False
        self.root.get_style_context().remove_class("open")
        self._render_pill()
        # One timeline instead of three loose ones: the panel fades out first,
        # and only once it is all but invisible does the height start to roll
        # up, with the width following just behind it. Everything lands
        # together at ~320ms, so the close reads as a single movement rather
        # than a shrink that carries on after the fade has finished.
        self._fade(0.0, CLOSE_FADE_MS)
        self._reveal(False, CLOSE_REVEAL_MS, delay=CLOSE_HOLD_MS)
        self._morph(self._pill_width(), 210, delay=110)
        self.cava.stop()
        self.spectrum.clear()
        return False

    def _reveal(self, state, duration, delay=0):
        """Roll the panel open or shut, optionally after a beat."""
        if self.reveal_src:
            GLib.source_remove(self.reveal_src)
            self.reveal_src = 0

        def go():
            self.panel_revealer.set_transition_duration(duration)
            self.panel_revealer.set_reveal_child(state)
            self.reveal_src = 0
            return False

        if delay:
            self.reveal_src = GLib.timeout_add(delay, go)
        else:
            go()

    def _pill_width(self):
        """Collapsed, the island hugs its text instead of sitting at a fixed
        width -- a long track title makes it grow."""
        nat = self.pill.get_preferred_width()[1]
        return max(190, min(380, nat + 6))

    def _set_width(self, w):
        self._cur_w = int(w)
        self.root.set_size_request(self._cur_w, -1)
        self._apply_position()

    # -- position ----------------------------------------------------------

    def _mon_geom(self):
        dpy = Gdk.Display.get_default()
        gdkwin = self.win.get_window()
        mon = (dpy.get_monitor_at_window(gdkwin) if gdkwin else None) \
            or dpy.get_primary_monitor() or dpy.get_monitor(0)
        return mon.get_geometry()

    def _apply_position(self):
        """Place the surface from (off_x, off_y), clamping it to the monitor.

        The offsets are clamped in place rather than at the point of use, so
        dragging past an edge cannot build up a phantom offset that has to be
        unwound before the island moves again.
        """
        g = self._mon_geom()
        # Mid-animation the allocation is a frame behind the request; trust the
        # request then, and the real allocation once things have settled.
        w = self._cur_w if self.morph_src \
            else max(self._cur_w, self.root.get_allocated_width())
        h = max(1, self.win.get_allocated_height())

        span_x = max(0, (g.width - w) / 2.0)
        self.off_x = max(-span_x, min(span_x, self.off_x))
        self.off_y = max(-MARGIN_TOP,
                         min(max(0.0, g.height - h - MARGIN_TOP), self.off_y))

        left = round((g.width - w) / 2.0 + self.off_x)
        top = round(MARGIN_TOP + self.off_y)
        if self._last_margin == (left, top):
            return
        self._last_margin = (left, top)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.LEFT, int(left))
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, int(top))

    def _set_cursor(self, name):
        gdkwin = self.win.get_window()
        if not gdkwin:
            return
        cur = Gdk.Cursor.new_from_name(self.win.get_display(), name) if name else None
        gdkwin.set_cursor(cur)

    def _win_press(self, _w, ev):
        if ev.button != 1:
            return False
        if ev.type == DOUBLE_PRESS:
            self._end_drag()
            self._glide(0.0, 0.0, HOME_MS)
            return True
        self._stop_glide()
        self._press_at = (ev.x, ev.y)
        self._drag_live = False
        self._pending = None
        # Reference the grab from the press, not from the first motion event:
        # that event arrives ~45ms later and already carries movement with it,
        # and anchoring to it leaves the island trailing the grab point by
        # however far the pointer travelled in the meantime, for the whole drag.
        cur = hypr_cursor()
        self._grab = (cur, (self.off_x, self.off_y)) if cur else None
        if self._grab and not self._drag_tick:
            # Watch the pointer from the press rather than waiting to be told
            # it moved: the first motion event lands ~45ms after the movement
            # starts, and the drag should not be blind for three frames.
            self._drag_tick = self.win.add_tick_callback(self._drag_step)
        return False

    def _win_motion(self, _w, ev):
        if self._press_at is None or self._grab:
            return False        # the frame clock is driving it from cursorpos
        dx = ev.x - self._press_at[0]
        dy = ev.y - self._press_at[1]
        if not self._drag_live:
            if math.hypot(dx, dy) < DRAG_SLOP:
                return False
            self._start_drag()
            if not self._drag_tick:
                self._drag_tick = self.win.add_tick_callback(self._drag_step)
        # Motion is reported relative to the surface, so once the surface has
        # moved by dx the pointer lands back on the press point: the delta is
        # always measured from the same origin and never needs re-basing.
        # Nothing is applied here -- several events can arrive between two
        # frames, and because the surface has not moved between them they all
        # measure from the same origin, so the newest one IS the total. Summing
        # them (or applying each in turn) is what made the drag judder.
        self._pending = (dx, dy)
        return True

    def _drag_step(self, _w, _clock):
        """Once a frame, put the island where the pointer actually is."""
        if self._press_at is None and not self._drag_live:
            self._drag_tick = 0
            return False
        if not self._drag_live and not self._grab:
            return True             # motion events will start the drag instead

        cur = hypr_cursor() if self._grab else None
        if self._grab and not cur:
            self._grab = None       # compositor went quiet; limp along on the
            return True             # motion-event path rather than freeze

        if cur and not self._drag_live:
            (gx, gy), _ = self._grab
            if math.hypot(cur[0] - gx, cur[1] - gy) < DRAG_SLOP:
                return True         # still a click, not yet a drag
            self._start_drag()

        if not self._drag_live:
            self._drag_tick = 0
            return False

        moved = False
        if cur:
            (gx, gy), (ox, oy) = self._grab
            want = (ox + cur[0] - gx, oy + cur[1] - gy)
            self.off_x, self.off_y = want
            self._apply_position()          # clamps to the monitor
            if (self.off_x, self.off_y) != want:
                # Held against an edge: re-reference so the island picks the
                # pointer up again the moment it comes back, rather than
                # sitting in a dead zone the width of the overshoot.
                self._grab = (cur, (self.off_x, self.off_y))
            moved = True
        elif self._pending:
            dx, dy = self._pending
            self.off_x += dx
            self.off_y += dy
            moved = True
        self._pending = None
        if moved:
            self._apply_position()          # no-op if the grab path just did it
            self._check_dock()
            # The margin is double-buffered layer-shell state: it only takes
            # effect on the next surface commit, so a frame has to be asked for
            # or the island never actually moves. A 1px damage rectangle is
            # enough to get one -- invalidating the whole root repaints the
            # panel and its spectrum 60 times a second for nothing, which was
            # costing dropped frames.
            self.win.queue_draw_area(0, 0, 1, 1)
        return True

    def _start_drag(self):
        self._drag_live = True
        self.dragging = True           # also holds the panel open
        self._set_cursor("grabbing")

    def _win_release(self, _w, ev):
        if ev.button != 1:
            return False
        dragged = self._drag_live
        self._end_drag()
        if dragged and self.docked and abs(self.off_y) > 0.5:
            self._glide(self.off_x, 0.0, SNAP_MS)   # settle onto the top rail
        return False

    def _end_drag(self):
        self._press_at = None
        self._pending = None
        self._grab = None
        if self._drag_live:
            self._drag_live = False
            self.dragging = False
            self._set_cursor(None)
        if self._drag_tick:
            self.win.remove_tick_callback(self._drag_tick)
            self._drag_tick = 0

    def _check_dock(self):
        """Opening and closing follow the island's own position.

        On the top rail it behaves like part of the bar: closed until hovered,
        closing again when the pointer leaves. Dragged down onto the desktop it
        becomes a floating panel and stays open on its own. Crossing back up is
        therefore what closes it.
        """
        docked = self.off_y < DOCK_Y
        if docked == self.docked:
            return
        self.docked = docked
        if docked:
            if self.collapse_src:
                GLib.source_remove(self.collapse_src)
                self.collapse_src = 0
            self._collapse()
        else:
            self._expand()

    def _stop_glide(self):
        if self.home_src:
            GLib.source_remove(self.home_src)
            self.home_src = 0

    def _glide(self, tx, ty, duration):
        """Ease the island to a target offset (double-click home, dock snap)."""
        self._stop_glide()
        sx, sy = self.off_x, self.off_y
        if abs(sx - tx) < 0.5 and abs(sy - ty) < 0.5:
            return
        t0 = time.monotonic()

        def step():
            frac = (time.monotonic() - t0) * 1000.0 / duration
            if frac >= 1.0:
                self.off_x, self.off_y = tx, ty
                self._apply_position()
                self._check_dock()
                self.home_src = 0
                return False
            k = ease(frac)
            self.off_x = sx + (tx - sx) * k
            self.off_y = sy + (ty - sy) * k
            self._apply_position()
            self._check_dock()
            return True

        self.home_src = GLib.timeout_add(16, step)

    def _morph(self, target, duration=MORPH_MS, delay=0):
        """Animate the island's width.

        Width and height are deliberately NOT run on the same curve. The
        revealer clips its child to the revealed height, so if the surface is
        still narrow while the panel slides down, the panel gets cut off at the
        edge -- which reads as the content being cropped. Opening therefore
        widens fast and reveals slowly; closing does the reverse.
        """
        if self.morph_src:
            GLib.source_remove(self.morph_src)
            self.morph_src = 0
        start = self.root.get_size_request()[0]
        if start < 0:
            start = COLLAPSED_W
        t0 = time.monotonic() + delay / 1000.0

        def step():
            now = time.monotonic()
            if now < t0:
                return True
            frac = (now - t0) * 1000.0 / duration
            if frac >= 1.0:
                self._set_width(target)
                self.morph_src = 0
                return False
            self._set_width(start + (target - start) * ease(frac))
            return True

        self.morph_src = GLib.timeout_add(16, step)

    def _fade(self, target, duration):
        """Cross-fade the panel so any residual clipping is invisible."""
        if self.fade_src:
            GLib.source_remove(self.fade_src)
            self.fade_src = 0
        start = self.panel.get_opacity()
        t0 = time.monotonic()

        def step():
            frac = (time.monotonic() - t0) * 1000.0 / duration
            if frac >= 1.0:
                self.panel.set_opacity(target)
                self.fade_src = 0
                return False
            self.panel.set_opacity(start + (target - start) * ease(frac))
            return True

        self.fade_src = GLib.timeout_add(16, step)

    # -- interaction -------------------------------------------------------

    def _drag_start(self, *_):
        self.dragging = True
        return False

    def _drag_end(self, *_):
        self.dragging = False
        return False

    def _seek_moved(self, scale):
        if self.seek_guard or not self.player.length:
            return
        self.time_now.set_text(hms(scale.get_value() / 1000.0 * self.player.length))

    def _seek_commit(self, scale, _ev):
        self.dragging = False
        if self.player.length:
            Player.seek(scale.get_value() / 1000.0 * self.player.length / 1_000_000)
        return False

    def _toggle_play(self):
        """Flip the icon on click rather than waiting for the next poll.

        Spotify's MPRIS PlaybackStatus lags a second or more behind the command
        it just accepted, so polling for confirmation is exactly what made this
        button feel dead. Show the new state straight away and let the poll
        catch up; if it disagrees for more than 3s, the poll wins.
        """
        expect = "Paused" if self.player.status == "Playing" else "Playing"
        self.player.status = expect
        self.optimistic = (expect, time.monotonic() + 3.0)
        self.play_btn.set_glyph(ICON_PAUSE if expect == "Playing" else ICON_PLAY)
        self._render_pill()
        self._refit()
        Player.cmd("play-pause")

    def _toggle_dnd(self, _btn):
        Dnd.set(not Dnd.enabled())
        GLib.timeout_add(150, self._sync_dnd)

    def _sync_dnd(self):
        on = Dnd.enabled()
        self.dnd_label.set_text("󰂛  Do not disturb" if on else "󰂚  Notifications on")
        ctx = self.dnd_btn.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("active")
        return False

    # -- audio watching ----------------------------------------------------

    def _watch_audio(self):
        """`pactl subscribe` fires on plenty of things, so the popup only
        triggers when the sink volume actually moved."""
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
        except Exception:
            return
        for line in proc.stdout:
            if "on sink" not in line and "on server" not in line:
                continue
            vol, muted = Audio.sink()
            if self.last_sink_vol is None:
                self.last_sink_vol = (vol, muted)
                continue
            if (vol, muted) != self.last_sink_vol:
                self.last_sink_vol = (vol, muted)
                GLib.idle_add(self._volume_popup, vol, muted)

    def _volume_popup(self, vol, muted):
        self.volume_until = time.monotonic() + VOLUME_POPUP_S
        self._render_pill(force=(vol, muted))
        self._refit()
        return False

    def _sync_audio(self):
        self.vol_row.sync(*Audio.sink())
        self.mic_row.sync(*Audio.source())
        self._sync_dnd()

    def _on_art(self, pb):
        self.artwork.set_pixbuf(pb)
        return False

    def _on_cava(self, vals):
        return self.spectrum.feed(vals)

    # -- polling -----------------------------------------------------------

    _prev_cpu = (0, 0)

    def _stats(self):
        with open("/proc/stat") as fh:
            f = [int(x) for x in fh.readline().split()[1:]]
        idle, total = f[3], sum(f)
        pi, pt = self._prev_cpu
        cpu = int(100 * ((total - pt) - (idle - pi)) / (total - pt)) if total > pt else 0
        self._prev_cpu = (idle, total)

        temp = 0
        for base in ("/sys/class/hwmon",):
            for d in sorted(os.listdir(base)):
                try:
                    with open(os.path.join(base, d, "name")) as fh:
                        if fh.read().strip() != "k10temp":
                            continue
                    with open(os.path.join(base, d, "temp1_input")) as fh:
                        temp = int(fh.read()) // 1000
                except OSError:
                    continue
                break
        return cpu, temp

    def _render_pill(self, force=None):
        if force is not None:
            vol, muted = force
            self.pill_icon.set_text("󰖁" if muted or vol == 0 else "󰕾")
            filled = round(vol / 100 * 12)
            self.pill_text.set_text(
                "%s  %d%%" % ("━" * filled + "─" * (12 - filled), vol))
            self._pill_class("volume")
            return

        p = self.player
        if p.active:
            playing = p.status == "Playing"
            self.pill_icon.set_text("󰎈" if playing else "󰏤")
            if self.expanded:
                # the panel already shows title and artist; don't repeat them
                label = p.album or ("Playing" if playing else "Paused")
            else:
                label = p.title
                if p.artist:
                    label += "  ·  " + p.artist
            self.pill_text.set_text(label)
            self._pill_class("playing" if playing else "paused")
            return

        cpu, temp = self._stats()
        self.pill_icon.set_text("󰍛")
        self.pill_text.set_text("%d%%     󰔐  %d°" % (cpu, temp))
        self._pill_class("idle")

    def _refit(self):
        """Re-run the morph if the collapsed text changed width appreciably."""
        if self.expanded or self.morph_src:
            return
        want = self._pill_width()
        if abs(self.root.get_size_request()[0] - want) > 8:
            self._morph(want)

    def _pill_class(self, state):
        ctx = self.root.get_style_context()
        for c in ("playing", "paused", "idle", "volume"):
            ctx.remove_class(c)
        ctx.add_class(state)

    def _tick(self):
        self.player.poll()
        p = self.player

        if self.optimistic:
            want, until = self.optimistic
            if p.status == want or time.monotonic() > until:
                self.optimistic = None
            else:
                p.status = want

        if time.monotonic() >= self.volume_until:
            self._render_pill()
            self._refit()

        if p.active:
            self.title.set_text(p.title)
            self.artist.set_text(p.artist or "Unknown artist")
            self.play_btn.set_glyph(ICON_PAUSE if p.status == "Playing" else ICON_PLAY)
            self.art.request(p.art_url)
            self.time_end.set_text(hms(p.length) if p.length else "0:00")
        else:
            self.title.set_text("Nothing playing")
            self.artist.set_text("")
            self.play_btn.set_glyph(ICON_PLAY)
            self.art.request("")
            self.time_end.set_text("0:00")
            self.time_now.set_text("0:00")
        return True

    def _fast_tick(self):
        if not self.expanded:
            return True
        p = self.player
        if p.active and p.length and not self.dragging:
            pos = int(run("playerctl", "-p", PLAYERS, "position", "--format",
                          "{{position}}") or 0)
            p.position = pos
            self.seek_guard = True
            self.seek.set_value(max(0, min(1000, pos / p.length * 1000)))
            self.seek_guard = False
            self.time_now.set_text(hms(pos))
        self._sync_audio()
        return True


def main():
    os.makedirs(CACHE, exist_ok=True)
    island = Island()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, island.reload)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, island.toggle_pin)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    Gtk.main()
    island.cava.stop()


if __name__ == "__main__":
    main()
