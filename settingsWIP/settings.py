#!/usr/bin/env python3
"""
Settings panel for Hyprland -- Stage 1: skeleton + system monitors.

A normal tiled toplevel window (see the note in SettingsWindow.__init__ for
why this is NOT a GtkLayerShell overlay like island -- short version: a
settings app you tile wants Hyprland's own window management, not a
permanent floating HUD). Colours
come from ~/.config/settings/colors.css (matugen writes the same colors.css
template used by waybar/island; see palette.py for how the accent tiers are
derived from it). A SIGUSR1 reloads the palette in place, matching the
retheme convention every other surface in this rice follows.

Stage 1 scope: window shell, sidebar nav skeleton, and a live-updating
System panel (CPU%, RAM, GPU busy % + VRAM for the Vega/RDNA iGPU via
sysfs, network throughput). No external Python deps -- everything is read
straight out of /proc and /sys so this stage has zero install step beyond
GTK + GtkLayerShell, which island.py already requires.

Later stages (toggles, config editing) add sidebar pages here; the nav
switcher and palette plumbing are already wired for it.
"""

import os

_LOCAL_GIR = os.path.expanduser("~/.local/lib/girepository-1.0")
if os.path.isdir(_LOCAL_GIR):
    os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
        filter(None, [_LOCAL_GIR, os.environ.get("GI_TYPELIB_PATH", "")]))

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

import glob
import signal
import subprocess
import time

from palette import load_palette, palette_to_css_header  # local module

HOME = os.path.expanduser("~")
CONF = os.path.join(HOME, ".config", "settings")
COLORS_CSS = os.path.join(CONF, "colors.css")
STYLE_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")

WIDTH = 720
HEIGHT = 460
POLL_MS = 1000       # system monitors refresh once a second -- plenty for a
                     # settings panel and cheap enough to leave running


def spawn(*args):
    """Fire-and-forget a command, same helper island.py uses for wpctl/
    brightnessctl/etc. calls that don't need their output read back."""
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---- system stats, zero external deps ------------------------------------

class CpuSampler:
    """Reads /proc/stat and reports overall CPU% between successive calls.
    A single first call returns 0.0 since there's no prior sample yet."""

    def __init__(self):
        self._prev = self._read()

    @staticmethod
    def _read():
        with open("/proc/stat") as fh:
            fields = fh.readline().split()[1:]
        return [int(x) for x in fields]

    def percent(self):
        cur = self._read()
        prev = self._prev
        self._prev = cur
        prev_idle = prev[3] + prev[4]
        cur_idle = cur[3] + cur[4]
        prev_total = sum(prev)
        cur_total = sum(cur)
        total_d = cur_total - prev_total
        idle_d = cur_idle - prev_idle
        if total_d <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (total_d - idle_d) / total_d))


def read_uptime():
    """Returns a human string like '2d 4h 12m' from /proc/uptime."""
    try:
        with open("/proc/uptime") as fh:
            secs = float(fh.read().split()[0])
    except (OSError, ValueError):
        return "n/a"
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def read_disk_usage(path="/"):
    """statvfs on the given mountpoint -- returns (used_gb, total_gb, pct)."""
    st = os.statvfs(path)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    total_gb = total / (1024 ** 3)
    used_gb = used / (1024 ** 3)
    pct = (used / total * 100.0) if total else 0.0
    return used_gb, total_gb, pct


def find_cpu_temp_sensor():
    """Search /sys/class/hwmon/hwmon*/name for a sensor chip commonly used
    for CPU package/die temps (k10temp on AMD, coretemp on Intel), rather
    than hardcoding a hwmonN path -- hwmon numbers shuffle across boots,
    same lesson the repo's own waybar temperature module comment calls out
    for 'hwmon-path-abs'. Returns the temp1_input path, or None."""
    candidates = ("k10temp", "coretemp", "zenpower")
    for hwmon_dir in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name_path = os.path.join(hwmon_dir, "name")
        try:
            with open(name_path) as fh:
                name = fh.read().strip()
        except OSError:
            continue
        if name in candidates:
            temp_path = os.path.join(hwmon_dir, "temp1_input")
            if os.path.exists(temp_path):
                return temp_path
    return None


def read_cpu_temp(sensor_path):
    if not sensor_path:
        return None
    raw = _read_int(sensor_path)
    return raw / 1000.0 if raw is not None else None


class PerCoreCpuSampler:
    """Same idea as CpuSampler but keeps one previous-sample line per core,
    reading /proc/stat's 'cpuN' lines (line 0 is the aggregate, already
    covered by CpuSampler -- this is purely the per-core breakdown for a
    small bar-per-core readout)."""

    def __init__(self):
        self._prev = self._read()

    @staticmethod
    def _read():
        cores = {}
        with open("/proc/stat") as fh:
            for line in fh:
                if not line.startswith("cpu") or line.startswith("cpu "):
                    continue
                parts = line.split()
                cores[parts[0]] = [int(x) for x in parts[1:]]
        return cores

    def percents(self):
        cur = self._read()
        prev = self._prev
        self._prev = cur
        out = []
        for name in sorted(cur, key=lambda n: int(n[3:])):
            c, p = cur[name], prev.get(name)
            if not p:
                out.append(0.0)
                continue
            c_idle, p_idle = c[3] + c[4], p[3] + p[4]
            c_total, p_total = sum(c), sum(p)
            total_d = c_total - p_total
            idle_d = c_idle - p_idle
            out.append(0.0 if total_d <= 0 else
                       max(0.0, min(100.0, 100.0 * (total_d - idle_d) / total_d)))
        return out


def read_mem():
    """Returns (used_gb, total_gb, percent) from /proc/meminfo, using the
    same 'available' accounting `free -h` does rather than naive
    total-minus-free, which overcounts cache/buffers as 'used'."""
    info = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, val = line.split(":", 1)
            info[key] = int(val.strip().split()[0])  # kB
    total_kb = info.get("MemTotal", 0)
    avail_kb = info.get("MemAvailable", 0)
    used_kb = max(0, total_kb - avail_kb)
    total_gb = total_kb / (1024 * 1024)
    used_gb = used_kb / (1024 * 1024)
    pct = (used_kb / total_kb * 100.0) if total_kb else 0.0
    return used_gb, total_gb, pct


def find_amdgpu_card():
    """First DRM card with an amdgpu gpu_busy_percent node -- covers both
    the Vega iGPU today and a future RX 580, no hardcoded card number since
    that shuffles across boots the same way hwmonN does (see the repo's
    'hwmon-path-abs' comment in the waybar temperature module)."""
    for path in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        return os.path.dirname(path)
    return None


def read_gpu(card_dir):
    """Returns (busy_pct, vram_used_mb, vram_total_mb) or (None, None, None)
    if the sysfs nodes aren't there (non-AMD GPU, or kernel too old for
    this node)."""
    if not card_dir:
        return None, None, None
    busy = _read_int(os.path.join(card_dir, "gpu_busy_percent"))
    vram_used = _read_int(os.path.join(card_dir, "mem_info_vram_used"))
    vram_total = _read_int(os.path.join(card_dir, "mem_info_vram_total"))
    vram_used_mb = vram_used / (1024 * 1024) if vram_used is not None else None
    vram_total_mb = vram_total / (1024 * 1024) if vram_total is not None else None
    return busy, vram_used_mb, vram_total_mb


def _read_int(path):
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


# ---- network (nmcli) -------------------------------------------------------
#
# Best-effort by design: nmcli's presence/behaviour wasn't confirmed for this
# machine, so every call here degrades to an empty/`None` result rather than
# raising, the same defensive pattern _wpctl_list_devices already uses for
# wpctl. If this machine turns out to use iwd or systemd-networkd instead,
# these are the only functions that need swapping -- the page builder below
# only talks to them through NM_AVAILABLE / list_wifi_networks / etc.

def _nmcli(*args, timeout=4):
    try:
        return subprocess.run(
            ["nmcli", *args], capture_output=True, text=True, timeout=timeout,
        ).stdout
    except Exception:
        return None


NM_AVAILABLE = _nmcli("--version") is not None


def nm_radio_wifi_enabled():
    out = _nmcli("radio", "wifi")
    return (out or "").strip().lower() == "enabled"


def nm_set_wifi_enabled(enabled):
    spawn("nmcli", "radio", "wifi", "on" if enabled else "off")


def nm_list_connections():
    """Active connections (any type) as (name, type, device) tuples, via
    nmcli's stable terse `-t` output -- no locale-dependent column parsing."""
    out = _nmcli("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active")
    if not out:
        return []
    result = []
    for line in out.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 3:
            result.append((parts[0], parts[1], parts[2]))
    return result


def nm_list_wifi():
    """Nearby wifi networks as (ssid, signal, security, in_use) tuples,
    sorted by signal descending. Empty list if wifi is off/unsupported."""
    out = _nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    if not out:
        return []
    result = []
    seen = set()
    for line in out.strip().splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        if not ssid or ssid in seen:
            continue  # blank SSID (hidden) or duplicate BSS of one already seen
        seen.add(ssid)
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        result.append((ssid, sig, security or "Open", in_use == "*"))
    result.sort(key=lambda t: t[1], reverse=True)
    return result


def nm_connect_wifi(ssid, password=None):
    if password:
        spawn("nmcli", "device", "wifi", "connect", ssid, "password", password)
    else:
        spawn("nmcli", "connection", "up", ssid)


def nm_disconnect(device):
    spawn("nmcli", "device", "disconnect", device)


# ---- display (brightnessctl + hyprctl) -------------------------------------

def brightness_available():
    try:
        return subprocess.run(
            ["brightnessctl", "-l"], capture_output=True, text=True, timeout=2,
        ).returncode == 0
    except Exception:
        return False


def read_brightness_pct():
    try:
        out = subprocess.run(
            ["brightnessctl", "g"], capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        maxout = subprocess.run(
            ["brightnessctl", "m"], capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        cur, mx = int(out), int(maxout)
        return round(cur / mx * 100) if mx else None
    except Exception:
        return None


def set_brightness_pct(pct):
    spawn("brightnessctl", "set", f"{max(1, min(100, int(pct)))}%")


def hyprctl_json(*args):
    """Runs `hyprctl -j <args>` and parses the result, or None on any
    failure -- hyprctl isn't guaranteed to be on PATH in every context this
    module might be imported from (e.g. a lint pass off-machine)."""
    try:
        out = subprocess.run(
            ["hyprctl", "-j", *args], capture_output=True, text=True, timeout=2,
        ).stdout
        import json
        return json.loads(out)
    except Exception:
        return None


def hyprctl_monitors():
    data = hyprctl_json("monitors")
    return data if isinstance(data, list) else []


def hyprctl_get_option(name):
    """Reads a single hyprctl keyword's current value, e.g. 'general:gaps_out'.

    hyprctl's -j getoption output isn't one consistent shape:
      - plain scalars (border_size, rounding) come back as {"int": 10, ...}
      - gaps (gaps_in/gaps_out) come back as {"css": "10 10 10 10", ...} --
        a CSS-shorthand string (top right bottom left), even when all four
        sides are equal, which was the actual cause of gap sliders always
        resetting to their minimum: this function used to only look for
        int/float/str and silently returned None for every "css" key.
    For a "css" value this returns the first number, matching the common
    case (uniform gaps) well enough for a single slider; a truly
    non-uniform gap value will still show/set only that first side."""
    data = hyprctl_json("getoption", name)
    if not isinstance(data, dict):
        return None
    for key in ("int", "float", "str"):
        if key in data and data[key] not in (None, -1, ""):
            return data[key]
    if "css" in data and data["css"]:
        first = str(data["css"]).split()[0]
        try:
            return int(first)
        except ValueError:
            try:
                return float(first)
            except ValueError:
                return None
    return None


def hyprctl_set_keyword(name, value):
    """Applies a keyword live via `hyprctl keyword`. This is the ONLY write
    path for Hyprland settings from this panel -- see write_hypr_override
    below for the separate persistence step."""
    spawn("hyprctl", "keyword", name, str(value))


# ---- hyprland.lua persistence ----------------------------------------------
#
# Values set live via `hyprctl keyword` don't survive a Hyprland reload/
# relaunch. To persist them WITHOUT regex-editing the user's hand-written
# hyprland.lua (risking mangled comments/structure), this panel owns a
# single small file, ~/.config/hypr/settings-panel.lua, and only ever
# rewrites that whole file. It still needs one line added to hyprland.lua,
# once, by hand -- see the module docstring / README note this ships with.

HYPR_OVERRIDE_PATH = os.path.join(HOME, ".config", "hypr", "settings-panel.lua")

# name -> hyprland.lua keyword path, for every control the Hyprland page
# exposes. Keys are the same dotted keyword names hyprctl uses so
# hyprctl_get_option/hyprctl_set_keyword and this table never drift apart.
HYPR_CONTROLS = {
    "general:gaps_in":     ("Gaps (inner)", "int", 0, 20),
    "general:gaps_out":    ("Gaps (outer)", "int", 0, 40),
    "general:border_size": ("Border size", "int", 0, 8),
    "decoration:rounding": ("Corner rounding", "int", 0, 30),
    "general:layout":      ("Layout", "enum", ["dwindle", "master"], None),
    "animations:enabled":  ("Animations", "bool", None, None),
    "decoration:blur:enabled": ("Blur", "bool", None, None),
    "misc:disable_hyprland_logo": ("Hide Hyprland logo", "bool", None, None),
    "misc:vfr":            ("Variable frame rate", "bool", None, None),
}


def read_hypr_overrides():
    """Parses this panel's own generated Lua file back into a
    {keyword: value} dict, so re-opening the panel shows persisted values
    even before hyprctl_get_option would (e.g. panel opened before Hyprland
    finished applying settings-panel.lua on a fresh login)."""
    overrides = {}
    try:
        with open(HYPR_OVERRIDE_PATH) as fh:
            text = fh.read()
    except OSError:
        return overrides
    # Lines this module writes always look like:
    #   hyprctl_set("general:gaps_in", "8")
    # a deliberately narrow format so parsing it back is a single regex,
    # not a Lua parser.
    import re
    for m in re.finditer(r'hyprctl_set\("([^"]+)",\s*"([^"]*)"\)', text):
        overrides[m.group(1)] = m.group(2)
    return overrides


def write_hypr_overrides(overrides):
    """Rewrites settings-panel.lua in full from the given {keyword: value}
    dict. Called after every control change so the file always reflects
    current state -- last-write-wins, no partial-edit risk since the whole
    file is one generated block, never hand-edited."""
    os.makedirs(os.path.dirname(HYPR_OVERRIDE_PATH), exist_ok=True)
    lines = [
        "-- Generated by settings.py -- DO NOT EDIT BY HAND.",
        "-- Persists Hyprland keyword changes made from the settings panel's",
        "-- Hyprland page across reloads/relaunches. Applied at Hyprland",
        "-- startup/reload if hyprland.lua requires this file (see README/",
        "-- the panel's Hyprland page for the one-line hyprland.lua addition",
        "-- this needs: `require(\"settings-panel\")`).",
        "",
        "local function hyprctl_set(name, value)",
        '    hyprctl(\'keyword \' .. name .. \' \' .. value)',
        "end",
        "",
    ]
    for name, value in overrides.items():
        lines.append(f'hyprctl_set("{name}", "{value}")')
    try:
        with open(HYPR_OVERRIDE_PATH, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False


class NetSampler:
    """Aggregate rx/tx across all non-loopback interfaces, reported as a
    rate in KB/s between calls -- same idea as CpuSampler."""

    def __init__(self):
        self._prev_bytes = self._read()
        self._prev_time = time.monotonic()

    @staticmethod
    def _read():
        rx = tx = 0
        with open("/proc/net/dev") as fh:
            for line in fh.readlines()[2:]:
                iface, rest = line.split(":", 1)
                iface = iface.strip()
                if iface == "lo":
                    continue
                fields = rest.split()
                rx += int(fields[0])
                tx += int(fields[8])
        return rx, tx

    def rates_kbps(self):
        now_bytes = self._read()
        now_time = time.monotonic()
        dt = max(1e-6, now_time - self._prev_time)
        rx_rate = (now_bytes[0] - self._prev_bytes[0]) / dt / 1024
        tx_rate = (now_bytes[1] - self._prev_bytes[1]) / dt / 1024
        self._prev_bytes = now_bytes
        self._prev_time = now_time
        return max(0.0, rx_rate), max(0.0, tx_rate)


# ---- widgets ---------------------------------------------------------------

def metric_card(label_text):
    """A single glass card: label, big value, small sub-line, thin usage
    bar. Returns (card_widget, value_label, sub_label, bar_fill_widget) so
    the caller can update them on each poll tick."""
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    card.get_style_context().add_class("metric-card")

    label = Gtk.Label(label=label_text, xalign=0)
    label.get_style_context().add_class("metric-label")

    value = Gtk.Label(label="--", xalign=0)
    value.get_style_context().add_class("metric-value")

    sub = Gtk.Label(label="", xalign=0)
    sub.get_style_context().add_class("metric-sub")

    bar = Gtk.ProgressBar()
    bar.set_show_text(False)
    bar.get_style_context().add_class("usage-bar")
    fill_ctx = bar.get_style_context()  # class toggled for warn/crit thresholds

    card.pack_start(label, False, False, 0)
    card.pack_start(value, False, False, 0)
    card.pack_start(bar, False, False, 2)
    card.pack_start(sub, False, False, 0)
    return card, value, sub, bar


def set_bar_level(bar, pct):
    """Colour the fill green->accent->tertiary->error as usage climbs, and
    push the fraction into the ProgressBar."""
    bar.set_fraction(max(0.0, min(1.0, pct / 100.0)))
    ctx = bar.get_style_context()
    ctx.remove_class("warn")
    ctx.remove_class("crit")
    if pct >= 90:
        ctx.add_class("crit")
    elif pct >= 70:
        ctx.add_class("warn")


def per_core_card(n_cores):
    """A wide card holding one thin bar per core, for a denser CPU view
    than the single aggregate percentage -- fills the empty space below
    the four main metric cards on the System page."""
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.get_style_context().add_class("metric-card")

    label = Gtk.Label(label="PER-CORE", xalign=0)
    label.get_style_context().add_class("metric-label")
    card.pack_start(label, False, False, 0)

    grid = Gtk.Grid()
    grid.set_row_spacing(6)
    grid.set_column_spacing(10)
    bars = []
    cols = 4  # 4 columns wraps a 12-thread CPU into 3 rows, reasonably compact
    for i in range(n_cores):
        core_label = Gtk.Label(label=f"{i}", xalign=1)
        core_label.get_style_context().add_class("metric-sub")
        core_label.set_size_request(18, -1)
        bar = Gtk.ProgressBar()
        bar.set_show_text(False)
        bar.get_style_context().add_class("usage-bar")
        bar.set_hexpand(True)
        row, col = divmod(i, cols)
        grid.attach(core_label, (col * 2), row, 1, 1)
        grid.attach(bar, (col * 2) + 1, row, 1, 1)
        bars.append(bar)
    card.pack_start(grid, False, False, 4)
    return card, bars


def toggle_row(title_text, sub_text, initial, on_toggle):
    """A titled row with a GtkSwitch on the right -- used for every boolean
    control across Network/Hyprland (wifi radio, animations, blur, etc).
    Returns (row_widget, switch_widget) so callers can programmatically
    resync the switch (e.g. after an external state change) without
    re-triggering on_toggle."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    row.get_style_context().add_class("list-row")

    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    title = Gtk.Label(label=title_text, xalign=0)
    title.get_style_context().add_class("list-row-title")
    labels.pack_start(title, False, False, 0)
    if sub_text:
        sub = Gtk.Label(label=sub_text, xalign=0)
        sub.get_style_context().add_class("list-row-sub")
        labels.pack_start(sub, False, False, 0)

    switch = Gtk.Switch()
    switch.set_active(bool(initial))
    switch.set_valign(Gtk.Align.CENTER)
    switch.connect("notify::active", lambda w, _p: on_toggle(w.get_active()))

    row.pack_start(labels, True, True, 0)
    row.pack_start(switch, False, False, 0)
    return row, switch


def action_button(text, on_click, secondary=False):
    btn = Gtk.Label(label=text, xalign=0.5)
    ctx = btn.get_style_context()
    ctx.add_class("action-btn")
    if secondary:
        ctx.add_class("secondary")
    ebox = Gtk.EventBox()
    ebox.add(btn)
    ebox.connect("button-press-event", lambda w, e: on_click())
    return ebox


def status_label():
    """A small status line pages use to confirm a button actually fired --
    every action on Hyprland/Waybar/Appearance shells out via spawn() with
    no return value, so without this a press gives zero feedback and looks
    identical to a no-op. Returns the Label; call .set_label(text) after
    an action, and _clear_status_later below to fade it after a few
    seconds so it doesn't read as a permanent state."""
    label = Gtk.Label(label="", xalign=0)
    label.get_style_context().add_class("status-ok")
    return label


def labeled_row(title_text, sub_text=None):
    """Just the label/sub-label stack toggle_row uses, standalone -- for
    rows that need a custom trailing widget instead of a Switch (a
    ComboBoxText, a Scale, an action button)."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    box.get_style_context().add_class("list-row")
    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    title = Gtk.Label(label=title_text, xalign=0)
    title.get_style_context().add_class("list-row-title")
    labels.pack_start(title, False, False, 0)
    if sub_text:
        sub = Gtk.Label(label=sub_text, xalign=0)
        sub.get_style_context().add_class("list-row-sub")
        labels.pack_start(sub, False, False, 0)
    box.pack_start(labels, True, True, 0)
    return box, labels


class SettingsWindow:
    def __init__(self):
        self.palette = {}
        self.cpu_sampler = CpuSampler()
        self.per_core_sampler = PerCoreCpuSampler()
        self.net_sampler = NetSampler()
        self.gpu_card = find_amdgpu_card()
        self.cpu_temp_sensor = find_cpu_temp_sensor()

        # Plain top-level window, NOT a layer-shell overlay. This makes it a
        # normal application window that Hyprland's tiling layout manages
        # like any other -- it can be tiled, floated, moved between
        # workspaces, snapped, etc. via ordinary Hyprland window rules.
        #
        # Trade-off vs. island's approach: island uses GtkLayerShell because
        # it's meant to float above the tiling layout permanently, like a
        # HUD. A settings *app* you tile among your other windows should be
        # a real toplevel instead -- using layer-shell here is what caused
        # the double-border look, since Hyprland doesn't decorate layer-shell
        # surfaces at all, but it DOES decorate normal toplevels, and our own
        # CSS border on .settings-shell was stacking on top of that.
        #
        # app_id must match the Hyprland window rule below so Hyprland can
        # target this window specifically (borderless, opacity, workspace
        # rules, etc.) instead of guessing by title.
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_wmclass("settings-panel", "settings-panel")
        self.win.set_title("Settings")
        self.win.set_default_size(WIDTH, HEIGHT)
        self.win.set_decorated(False)  # Hyprland draws the border/titlebar instead
        self.win.set_app_paintable(True)

        visual = self.win.get_screen().get_rgba_visual()
        if visual:
            self.win.set_visual(visual)
        self.win.connect("draw", self._clear_background)

        self._build_ui()
        self.win.connect("destroy", Gtk.main_quit)
        self.win.connect("key-press-event", self._on_key)

        self._load_css()
        GLib.timeout_add(POLL_MS, self._poll)

    @staticmethod
    def _clear_background(_w, cr):
        cr.save()
        import cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.restore()
        return False

    def _on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            # A tiled window sitting hidden still occupies its tile slot in
            # Hyprland's layout, unlike island's layer-shell surface -- so
            # Escape closes it outright rather than hiding it.
            Gtk.main_quit()
            return True
        return False

    # -- layout --------------------------------------------------------

    def _build_ui(self):
        shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        shell.get_style_context().add_class("settings-shell")
        shell.set_size_request(WIDTH, HEIGHT)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.set_size_request(160, -1)

        # Gtk.Stack holds every page; sidebar rows just call set_visible_child_name.
        # Pages not yet built (Network/Display/Waybar/Hyprland/Appearance) get a
        # simple placeholder so clicking them doesn't do nothing silently.
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)

        self.stack.add_named(self._build_system_page(), "System")
        self.stack.add_named(self._build_audio_page(), "Audio")
        self.stack.add_named(self._build_network_page(), "Network")
        self.stack.add_named(self._build_display_page(), "Display")
        self.stack.add_named(self._build_waybar_page(), "Waybar")
        self.stack.add_named(self._build_hyprland_page(), "Hyprland")
        self.stack.add_named(self._build_appearance_page(), "Appearance")

        self.sidebar_items = {}
        for i, name in enumerate(
            ("System", "Audio", "Network", "Display", "Waybar", "Hyprland",
             "Appearance")
        ):
            label = Gtk.Label(label=name, xalign=0)
            label.get_style_context().add_class("sidebar-item")
            if i == 0:
                label.get_style_context().add_class("active")
            ebox = Gtk.EventBox()
            ebox.add(label)
            ebox.connect("button-press-event", self._on_sidebar_click, name)
            sidebar.pack_start(ebox, False, False, 0)
            self.sidebar_items[name] = label

        # Every page is wrapped in a ScrolledWindow rather than the bare
        # Stack -- Stage 1 assumed everything fit in HEIGHT (460px), but
        # the new pages (per-core grid, device lists, Hyprland keyword
        # rows) can run taller than that on a small monitor. Overlay mode
        # (GTK3 default when kinetic scrolling is left on) keeps the
        # scrollbar from claiming layout width at rest -- it only appears
        # on hover/scroll, so pages that DO fit in HEIGHT look identical
        # to before. min-content-height stays unset on purpose: pages size
        # to WIDTH/HEIGHT and only scroll when content actually overflows.
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(True)
        scroller.add(self.stack)

        shell.pack_start(sidebar, False, False, 0)
        shell.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
                          False, False, 0)
        shell.pack_start(scroller, True, True, 0)

        self.win.add(shell)
        self.win.show_all()

    def _on_sidebar_click(self, _widget, _event, name):
        self.stack.set_visible_child_name(name)
        for item_name, label in self.sidebar_items.items():
            ctx = label.get_style_context()
            if item_name == name:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")

    def _page_header(self, title_text, subtitle_text):
        title = Gtk.Label(label=title_text, xalign=0)
        title.get_style_context().add_class("section-title")
        subtitle = Gtk.Label(label=subtitle_text, xalign=0)
        subtitle.get_style_context().add_class("section-subtitle")
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.pack_start(title, False, False, 0)
        header.pack_start(subtitle, False, False, 0)
        return header

    def _build_placeholder_page(self, name):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_border_width(20)
        content.pack_start(
            self._page_header(name, "not built yet -- Stage 3/4"), False, False, 0)
        placeholder = Gtk.Label(label="Coming in a later stage.", xalign=0)
        placeholder.get_style_context().add_class("section-subtitle")
        content.pack_start(placeholder, False, False, 0)
        return content

    def _build_system_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("System", "live from /proc and /sys, no daemons"),
            False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(12)
        grid.set_column_homogeneous(True)

        self.cpu_card, self.cpu_value, self.cpu_sub, self.cpu_bar = metric_card("CPU")
        self.ram_card, self.ram_value, self.ram_sub, self.ram_bar = metric_card("MEMORY")
        self.gpu_card_w, self.gpu_value, self.gpu_sub, self.gpu_bar = metric_card("GPU")
        self.net_card, self.net_value, self.net_sub, self.net_bar = metric_card("NETWORK")
        self.disk_card, self.disk_value, self.disk_sub, self.disk_bar = metric_card("DISK (/)")
        self.temp_card, self.temp_value, self.temp_sub, self.temp_bar = metric_card("CPU TEMP")

        grid.attach(self.cpu_card, 0, 0, 1, 1)
        grid.attach(self.ram_card, 1, 0, 1, 1)
        grid.attach(self.gpu_card_w, 0, 1, 1, 1)
        grid.attach(self.net_card, 1, 1, 1, 1)
        grid.attach(self.disk_card, 0, 2, 1, 1)
        grid.attach(self.temp_card, 1, 2, 1, 1)

        # uptime as a plain readout, not a card -- it doesn't have a
        # percentage/usage dimension so a progress bar under it would be
        # meaningless
        self.uptime_label = Gtk.Label(label="Uptime: --", xalign=0)
        self.uptime_label.get_style_context().add_class("section-subtitle")

        n_cores = os.cpu_count() or 1
        self.core_card, self.core_bars = per_core_card(n_cores)

        content.pack_start(grid, False, False, 0)
        content.pack_start(self.core_card, False, False, 0)
        content.pack_start(self.uptime_label, False, False, 4)
        return content

    def _build_audio_page(self):
        """wpctl-backed volume/mute controls -- this repo is on PipeWire, so
        wpctl is the native tool rather than amixer/pactl. Every control here
        shells out on interaction; there's no persistent daemon connection,
        matching the 'no daemons' philosophy the System page's subtitle
        already states."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Audio", "wpctl -- PipeWire"), False, False, 0)

        # ---- output device picker ----
        out_dev_label = Gtk.Label(label="OUTPUT DEVICE", xalign=0)
        out_dev_label.get_style_context().add_class("metric-label")
        self.out_device_combo = Gtk.ComboBoxText()
        self.out_device_combo.connect("changed", self._on_output_device_selected)

        # ---- output volume ----
        out_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        out_label_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        out_label = Gtk.Label(label="OUTPUT VOLUME", xalign=0)
        out_label.get_style_context().add_class("metric-label")
        self.vol_value_label = Gtk.Label(label="--%", xalign=1)
        self.vol_value_label.get_style_context().add_class("slider-value")
        out_label_row.pack_start(out_label, True, True, 0)
        out_label_row.pack_start(self.vol_value_label, False, False, 0)

        vol_slider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.vol_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.vol_scale.set_draw_value(False)
        self.vol_scale.set_hexpand(True)
        self.vol_scale.connect("value-changed", self._on_volume_changed)
        vol_down_btn = self._step_button("−", self._on_vol_step, -5)
        vol_up_btn = self._step_button("+", self._on_vol_step, 5)
        vol_slider_row.pack_start(vol_down_btn, False, False, 0)
        vol_slider_row.pack_start(self.vol_scale, True, True, 0)
        vol_slider_row.pack_start(vol_up_btn, False, False, 0)

        self.mute_btn = Gtk.Label(label="MUTE", xalign=0)
        self.mute_btn.get_style_context().add_class("dnd")
        mute_ebox = Gtk.EventBox()
        mute_ebox.add(self.mute_btn)
        mute_ebox.connect("button-press-event", self._on_mute_toggle)

        out_row.pack_start(out_dev_label, False, False, 0)
        out_row.pack_start(self.out_device_combo, False, False, 4)
        out_row.pack_start(out_label_row, False, False, 6)
        out_row.pack_start(vol_slider_row, False, False, 0)
        out_row.pack_start(mute_ebox, False, False, 4)

        # ---- input device picker + mic volume ----
        in_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        in_dev_label = Gtk.Label(label="INPUT DEVICE", xalign=0)
        in_dev_label.get_style_context().add_class("metric-label")
        self.in_device_combo = Gtk.ComboBoxText()
        self.in_device_combo.connect("changed", self._on_input_device_selected)

        in_label_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        in_label = Gtk.Label(label="INPUT VOLUME (MIC)", xalign=0)
        in_label.get_style_context().add_class("metric-label")
        self.mic_value_label = Gtk.Label(label="--%", xalign=1)
        self.mic_value_label.get_style_context().add_class("slider-value")
        in_label_row.pack_start(in_label, True, True, 0)
        in_label_row.pack_start(self.mic_value_label, False, False, 0)

        self.mic_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.mic_scale.set_draw_value(False)
        self.mic_scale.connect("value-changed", self._on_mic_changed)

        self.mic_mute_btn = Gtk.Label(label="MUTE MIC", xalign=0)
        self.mic_mute_btn.get_style_context().add_class("dnd")
        mic_mute_ebox = Gtk.EventBox()
        mic_mute_ebox.add(self.mic_mute_btn)
        mic_mute_ebox.connect("button-press-event", self._on_mic_mute_toggle)

        in_row.pack_start(in_dev_label, False, False, 0)
        in_row.pack_start(self.in_device_combo, False, False, 4)
        in_row.pack_start(in_label_row, False, False, 6)
        in_row.pack_start(self.mic_scale, False, False, 0)
        in_row.pack_start(mic_mute_ebox, False, False, 4)

        content.pack_start(out_row, False, False, 6)
        content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                            False, False, 4)
        content.pack_start(in_row, False, False, 6)

        self._audio_refresh_pending = False
        self._refresh_device_lists()
        self._refresh_audio_state()
        return content

    # -- network page ------------------------------------------------------

    def _build_network_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Network", "nmcli -- best-effort"), False, False, 0)

        if not NM_AVAILABLE:
            warn = Gtk.Label(
                label="nmcli not found -- this page needs NetworkManager.",
                xalign=0)
            warn.get_style_context().add_class("status-error")
            content.pack_start(warn, False, False, 0)
            return content

        wifi_row, self.wifi_switch = toggle_row(
            "Wi-Fi", "Radio on/off", nm_radio_wifi_enabled(),
            self._on_wifi_radio_toggle)
        content.pack_start(wifi_row, False, False, 0)

        active_label = Gtk.Label(label="ACTIVE CONNECTIONS", xalign=0)
        active_label.get_style_context().add_class("metric-label")
        content.pack_start(active_label, False, False, 6)
        self.net_active_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.pack_start(self.net_active_box, False, False, 0)

        avail_row_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        avail_label = Gtk.Label(label="AVAILABLE WI-FI", xalign=0)
        avail_label.get_style_context().add_class("metric-label")
        avail_row_header.pack_start(avail_label, True, True, 0)
        avail_row_header.pack_start(
            action_button("RESCAN", self._refresh_network_page, secondary=True),
            False, False, 0)
        content.pack_start(avail_row_header, False, False, 6)

        self.net_wifi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.pack_start(self.net_wifi_box, False, False, 0)

        self._refresh_network_page()
        return content

    def _on_wifi_radio_toggle(self, enabled):
        nm_set_wifi_enabled(enabled)
        GLib.timeout_add(600, self._refresh_network_page_once)

    def _refresh_network_page_once(self):
        self._refresh_network_page()
        return False

    def _refresh_network_page(self):
        if not NM_AVAILABLE:
            return
        for child in self.net_active_box.get_children():
            self.net_active_box.remove(child)
        conns = nm_list_connections()
        if not conns:
            empty = Gtk.Label(label="No active connections", xalign=0)
            empty.get_style_context().add_class("list-row-sub")
            self.net_active_box.pack_start(empty, False, False, 0)
        for name, ctype, device in conns:
            row, _ = labeled_row(name, f"{ctype} -- {device}")
            disc_btn = action_button(
                "DISCONNECT",
                lambda d=device: (nm_disconnect(d),
                                   GLib.timeout_add(500, self._refresh_network_page_once)),
                secondary=True)
            row.pack_start(disc_btn, False, False, 0)
            self.net_active_box.pack_start(row, False, False, 0)
        self.net_active_box.show_all()

        for child in self.net_wifi_box.get_children():
            self.net_wifi_box.remove(child)
        networks = nm_list_wifi()
        if not networks:
            empty = Gtk.Label(
                label="No networks found (Wi-Fi off, or nmcli scan empty)",
                xalign=0)
            empty.get_style_context().add_class("list-row-sub")
            self.net_wifi_box.pack_start(empty, False, False, 0)
        for ssid, signal, security, in_use in networks[:8]:
            sub = f"{signal}%  --  {security}" + ("  --  connected" if in_use else "")
            row, _ = labeled_row(ssid, sub)
            if not in_use:
                connect_btn = action_button(
                    "CONNECT", lambda s=ssid: self._on_wifi_connect_click(s),
                    secondary=True)
                row.pack_start(connect_btn, False, False, 0)
            self.net_wifi_box.pack_start(row, False, False, 0)
        self.net_wifi_box.show_all()

    def _on_wifi_connect_click(self, ssid):
        """Tries a saved-profile connect first (no password needed if
        already known to NetworkManager). A network that needs a password
        for the first time isn't handled here -- that needs a text entry
        dialog, which is reasonable Stage 4 scope, not something to fake
        with a blocking terminal prompt from a GTK app."""
        nm_connect_wifi(ssid)
        GLib.timeout_add(1200, self._refresh_network_page_once)

    # -- display page --------------------------------------------------

    def _build_display_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Display", "hyprctl + brightnessctl"), False, False, 0)

        if brightness_available():
            bright_row, labels = labeled_row("BRIGHTNESS", None)
            self.bright_value_label = Gtk.Label(label="--%", xalign=1)
            self.bright_value_label.get_style_context().add_class("slider-value")
            labels.pack_start(self.bright_value_label, False, False, 0)
            content.pack_start(bright_row, False, False, 0)

            self.bright_scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 1, 100, 1)
            self.bright_scale.set_draw_value(False)
            self.bright_scale.set_hexpand(True)
            cur = read_brightness_pct()
            self.bright_scale.set_value(cur if cur is not None else 100)
            self._bright_refresh_pending = False
            self.bright_scale.connect("value-changed", self._on_brightness_changed)
            content.pack_start(self.bright_scale, False, False, 8)
        else:
            warn = Gtk.Label(
                label="brightnessctl not found or no controllable backlight.",
                xalign=0)
            warn.get_style_context().add_class("status-warn")
            content.pack_start(warn, False, False, 0)

        mon_label = Gtk.Label(label="MONITORS", xalign=0)
        mon_label.get_style_context().add_class("metric-label")
        content.pack_start(mon_label, False, False, 10)

        self.monitors_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.pack_start(self.monitors_box, False, False, 0)
        self._refresh_monitors()

        content.pack_start(
            action_button("REFRESH MONITORS", self._refresh_monitors, secondary=True),
            False, False, 8)
        return content

    def _on_brightness_changed(self, scale):
        pct = int(scale.get_value())
        self.bright_value_label.set_label(f"{pct}%")
        set_brightness_pct(pct)

    def _refresh_monitors(self):
        for child in self.monitors_box.get_children():
            self.monitors_box.remove(child)
        monitors = hyprctl_monitors()
        if not monitors:
            empty = Gtk.Label(
                label="hyprctl not reachable -- is this running under Hyprland?",
                xalign=0)
            empty.get_style_context().add_class("list-row-sub")
            self.monitors_box.pack_start(empty, False, False, 0)
        for mon in monitors:
            name = mon.get("name", "?")
            res = f'{mon.get("width", "?")}x{mon.get("height", "?")}@{mon.get("refreshRate", 0):.0f}Hz'
            scale = mon.get("scale", 1.0)
            sub = f"{res}  --  scale {scale:g}x" + (
                "  --  focused" if mon.get("focused") else "")
            row, _ = labeled_row(name, sub)
            self.monitors_box.pack_start(row, False, False, 0)
        self.monitors_box.show_all()

    # -- waybar page -----------------------------------------------------

    def _build_waybar_page(self):
        """No config editor here on purpose -- waybar's config.jsonc/style
        are hand-authored files this repo already treats as source of
        truth (see the repo's alternate presets in waybar/style/ and
        waybar/configs/). A GUI editor for that risks fighting the user's
        own edits. This page is process control only."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Waybar", "process control"), False, False, 0)

        self.waybar_status = status_label()

        row, _ = labeled_row(
            "Restart waybar",
            "killall waybar; waybar & -- picks up config/style changes")
        row.pack_start(
            action_button("RESTART", self._on_waybar_restart),
            False, False, 0)
        content.pack_start(row, False, False, 0)

        row2, _ = labeled_row("Toggle waybar", "hide/show without killing it")
        row2.pack_start(
            action_button("TOGGLE", self._on_waybar_toggle, secondary=True),
            False, False, 0)
        content.pack_start(row2, False, False, 0)

        content.pack_start(self.waybar_status, False, False, 4)

        note = Gtk.Label(
            label="Edit config/waybar/config.jsonc and style.css directly, "
                  "then Restart here to apply.",
            xalign=0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("list-row-sub")
        content.pack_start(note, False, False, 10)
        return content

    def _on_waybar_restart(self):
        self.waybar_status.set_label("Restarting waybar...")
        spawn("pkill", "-x", "waybar")
        GLib.timeout_add(300, self._waybar_relaunch_once)

    def _waybar_relaunch_once(self):
        spawn("waybar")
        self.waybar_status.set_label("Restarted.")
        GLib.timeout_add(3000, self._clear_waybar_status_once)
        return False  # one-shot

    def _on_waybar_toggle(self):
        spawn("sh", "-c", "pkill -SIGUSR1 -x waybar")
        self.waybar_status.set_label("Toggled.")
        GLib.timeout_add(3000, self._clear_waybar_status_once)

    def _clear_waybar_status_once(self):
        self.waybar_status.set_label("")
        return False  # one-shot

    # -- hyprland page -----------------------------------------------------

    def _build_hyprland_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Hyprland", "live via hyprctl + persisted"),
            False, False, 0)

        persisted = read_hypr_overrides()
        self._hypr_widgets = {}

        for keyword, (label_text, kind, *rest) in HYPR_CONTROLS.items():
            current = persisted.get(keyword)
            if current is None:
                live = hyprctl_get_option(keyword)
                current = str(live) if live is not None else None

            if kind == "bool":
                initial = str(current).strip().lower() in ("1", "true", "yes")
                row, switch = toggle_row(
                    label_text, keyword,
                    initial,
                    lambda val, kw=keyword: self._on_hypr_bool(kw, val))
                self._hypr_widgets[keyword] = switch
                content.pack_start(row, False, False, 0)

            elif kind == "int":
                lo, hi = rest[0], rest[1]
                row, labels = labeled_row(label_text, keyword)
                value_label = Gtk.Label(label=str(current or lo), xalign=1)
                value_label.get_style_context().add_class("slider-value")
                labels.pack_start(value_label, False, False, 0)
                content.pack_start(row, False, False, 0)

                scale = Gtk.Scale.new_with_range(
                    Gtk.Orientation.HORIZONTAL, lo, hi, 1)
                scale.set_draw_value(False)
                scale.set_hexpand(True)
                try:
                    scale.set_value(float(str(current).split()[0]))
                except (TypeError, ValueError, IndexError):
                    scale.set_value(lo)
                scale.connect(
                    "value-changed",
                    lambda s, kw=keyword, vl=value_label: self._on_hypr_int(kw, s, vl))
                content.pack_start(scale, False, False, 6)
                self._hypr_widgets[keyword] = scale

            elif kind == "enum":
                options = rest[0]
                row, labels = labeled_row(label_text, keyword)
                combo = Gtk.ComboBoxText()
                for opt in options:
                    combo.append_text(opt)
                # set_active() below fires "changed" immediately -- connect
                # the handler AFTER setting the initial value so opening
                # this page doesn't itself issue a live hyprctl write for
                # every enum control before the user has touched anything.
                if current in options:
                    combo.set_active(options.index(current))
                else:
                    combo.set_active(0)
                combo.connect(
                    "changed",
                    lambda c, kw=keyword, opts=options: self._on_hypr_enum(kw, c, opts))
                labels.pack_start(combo, False, False, 4)
                content.pack_start(row, False, False, 0)
                self._hypr_widgets[keyword] = combo

        self.hypr_status = status_label()
        content.pack_start(self.hypr_status, False, False, 4)

        note = Gtk.Label(
            label="Changes apply live immediately. To persist across a "
                  "Hyprland reload, add this line once to hyprland.lua:\n"
                  'require("settings-panel")',
            xalign=0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("list-row-sub")
        content.pack_start(note, False, False, 10)
        return content

    def _flash_hypr_status(self, text):
        self.hypr_status.set_label(text)
        GLib.timeout_add(2500, self._clear_hypr_status_once)

    def _clear_hypr_status_once(self):
        self.hypr_status.set_label("")
        return False  # one-shot

    def _persist_hypr(self, keyword, value):
        overrides = read_hypr_overrides()
        overrides[keyword] = str(value)
        write_hypr_overrides(overrides)

    def _on_hypr_bool(self, keyword, enabled):
        val = "true" if enabled else "false"
        hyprctl_set_keyword(keyword, val)
        self._persist_hypr(keyword, val)
        self._flash_hypr_status(f"{keyword} -> {val}")

    def _on_hypr_int(self, keyword, scale, value_label):
        val = int(scale.get_value())
        value_label.set_label(str(val))
        hyprctl_set_keyword(keyword, val)
        self._persist_hypr(keyword, val)
        self._flash_hypr_status(f"{keyword} -> {val}")

    def _on_hypr_enum(self, keyword, combo, options):
        idx = combo.get_active()
        if idx < 0 or idx >= len(options):
            return
        val = options[idx]
        hyprctl_set_keyword(keyword, val)
        self._persist_hypr(keyword, val)
        self._flash_hypr_status(f"{keyword} -> {val}")

    # -- appearance page -----------------------------------------------------

    def _build_appearance_page(self):
        """Deliberately no wallpaper picker/preview here -- that's owned by
        the existing set-wallpaper / retheme flow this repo already has a
        button for elsewhere. This page only triggers that flow and shows
        current palette info + a reload."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(20)
        content.pack_start(
            self._page_header("Appearance", "matugen -- shared across the rice"),
            False, False, 0)

        row, _ = labeled_row(
            "Reload palette",
            "re-reads colors.css + style.css (same as SIGUSR1)")
        row.pack_start(
            action_button("RELOAD", self._on_reload_click), False, False, 0)
        content.pack_start(row, False, False, 0)

        row2, _ = labeled_row(
            "Re-run retheme",
            "regenerates colours for every surface from the CURRENT "
            "wallpaper -- use your wallpaper picker first to change it")
        row2.pack_start(
            action_button("RETHEME", self._on_retheme_click, secondary=True),
            False, False, 0)
        content.pack_start(row2, False, False, 0)

        self.appearance_status = status_label()
        content.pack_start(self.appearance_status, False, False, 0)

        swatch_label = Gtk.Label(label="CURRENT ACCENT TIERS", xalign=0)
        swatch_label.get_style_context().add_class("metric-label")
        content.pack_start(swatch_label, False, False, 10)

        self.swatch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.pack_start(self.swatch_box, False, False, 4)
        self._refresh_swatches()
        return content

    def _on_reload_click(self):
        self._load_css()
        self._refresh_swatches()
        self._flash_appearance_status("Palette reloaded.")

    def _on_retheme_click(self):
        self.appearance_status.set_label("Running retheme...")
        spawn("retheme")
        # retheme's post-hooks reload every surface via SIGUSR1 including
        # this one (see reload()), which already refreshes swatches --
        # this timeout just clears the "running" status after giving it a
        # moment to actually finish, since spawn() doesn't wait for exit.
        GLib.timeout_add(2000, self._retheme_done_once)

    def _retheme_done_once(self):
        self._flash_appearance_status("Retheme applied.")
        return False  # one-shot

    def _flash_appearance_status(self, text):
        self.appearance_status.set_label(text)
        GLib.timeout_add(2500, self._clear_appearance_status_once)

    def _clear_appearance_status_once(self):
        self.appearance_status.set_label("")
        return False  # one-shot

    def _refresh_swatches(self):
        for child in self.swatch_box.get_children():
            self.swatch_box.remove(child)
        from palette import to_hex
        for name in ("settings_accent", "settings_accent_muted", "settings_accent_dim"):
            rgb = self.palette.get(name)
            if not rgb:
                continue
            chip = Gtk.Box()
            chip.set_size_request(48, 28)
            ctx = chip.get_style_context()
            provider = Gtk.CssProvider()
            provider.load_from_data(
                f"box {{ background-color: {to_hex(rgb)}; border-radius: 8px; }}".encode())
            ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.swatch_box.pack_start(chip, False, False, 0)
        self.swatch_box.show_all()

    def _step_button(self, text, handler, delta):
        btn = Gtk.Label(label=text, xalign=0.5)
        btn.get_style_context().add_class("dnd")
        btn.set_size_request(28, -1)
        ebox = Gtk.EventBox()
        ebox.add(btn)
        ebox.connect("button-press-event", handler, delta)
        return ebox

    def _on_vol_step(self, _widget, _event, delta):
        new_val = max(0, min(150, self.vol_scale.get_value() + delta))
        self.vol_scale.set_value(new_val)  # fires _on_volume_changed itself

    def _on_mic_mute_toggle(self, _widget, _event):
        spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle")
        GLib.timeout_add(120, self._refresh_audio_state_once)

    @staticmethod
    def _wpctl_list_devices(kind):
        """Parses `wpctl status` for Sinks or Sources. kind is 'Sinks' or
        'Sources'. Returns a list of (id, name, is_default) tuples.

        wpctl has no JSON output mode, so this scrapes plain text -- fragile
        in principle, but the format has been stable across PipeWire
        releases and this avoids pulling in a PipeWire python binding as a
        dependency just to enumerate devices.

        Section body lines look like (leading box-drawing chars vary):
            │      50. Some Device [vol: 0.45]
            │  *   52. Other Device [vol: 0.60]
        A line belongs to the section once it starts with an optional '*'
        and a digit id; the section ends at the first line under it that
        does NOT match that shape (a blank separator or the next heading)."""
        try:
            out = subprocess.run(
                ["wpctl", "status"], capture_output=True, text=True, timeout=2,
            ).stdout
        except Exception:
            return []

        devices = []
        in_section = False
        for line in out.splitlines():
            if f"{kind}:" in line:
                in_section = True
                continue
            if not in_section:
                continue

            # strip box-drawing/prefix characters, keep the "* NN. name" body
            body = line.strip(" │├─└")
            is_default = body.startswith("*")
            body = body.lstrip("* ").strip()

            dev_id, _, rest = body.partition(". ")
            if not dev_id.isdigit():
                # first non-matching line after entries means this section ended
                if devices:
                    break
                continue

            name = rest.rsplit(" [vol:", 1)[0].strip()
            devices.append((dev_id, name, is_default))
        return devices

    def _refresh_device_lists(self):
        """Repopulates the output/input device combo boxes from wpctl
        status and selects whichever is currently marked default."""
        out_devices = self._wpctl_list_devices("Sinks")
        in_devices = self._wpctl_list_devices("Sources")

        self.out_device_combo.remove_all()
        self._out_device_ids = []
        for dev_id, name, is_default in out_devices:
            self.out_device_combo.append_text(name)
            self._out_device_ids.append(dev_id)
            if is_default:
                self.out_device_combo.set_active(len(self._out_device_ids) - 1)

        self.in_device_combo.remove_all()
        self._in_device_ids = []
        for dev_id, name, is_default in in_devices:
            self.in_device_combo.append_text(name)
            self._in_device_ids.append(dev_id)
            if is_default:
                self.in_device_combo.set_active(len(self._in_device_ids) - 1)

    def _on_output_device_selected(self, combo):
        idx = combo.get_active()
        if idx < 0 or idx >= len(self._out_device_ids):
            return
        spawn("wpctl", "set-default", self._out_device_ids[idx])
        GLib.timeout_add(150, self._refresh_audio_state_once)

    def _on_input_device_selected(self, combo):
        idx = combo.get_active()
        if idx < 0 or idx >= len(self._in_device_ids):
            return
        spawn("wpctl", "set-default", self._in_device_ids[idx])
        GLib.timeout_add(150, self._refresh_audio_state_once)

    # -- audio backend (wpctl) ------------------------------------------

    @staticmethod
    def _wpctl_get_volume(target):
        """target: '@DEFAULT_AUDIO_SINK@' or '@DEFAULT_AUDIO_SOURCE@'.
        Returns (pct, muted) or (None, None) if wpctl isn't available or the
        device can't be read -- callers must handle that gracefully rather
        than assume audio control always works (e.g. running this over SSH,
        or before PipeWire has started)."""
        try:
            out = subprocess.run(
                ["wpctl", "get-volume", target],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
        except Exception:
            return None, None
        if not out:
            return None, None
        # wpctl prints "Volume: 0.45" or "Volume: 0.45 [MUTED]"
        muted = "MUTED" in out
        try:
            frac = float(out.split()[1])
        except (IndexError, ValueError):
            return None, None
        return round(frac * 100), muted

    def _refresh_audio_state(self):
        """Pull current volume from wpctl and set the sliders WITHOUT firing
        their value-changed handlers (which would immediately write it back
        via wpctl) -- see the _audio_refresh_pending guard in the handlers."""
        self._audio_refresh_pending = True
        vol_pct, vol_muted = self._wpctl_get_volume("@DEFAULT_AUDIO_SINK@")
        if vol_pct is not None:
            self.vol_scale.set_value(vol_pct)
            self.vol_value_label.set_label(f"{vol_pct}%")
            ctx = self.mute_btn.get_style_context()
            if vol_muted:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        else:
            self.vol_value_label.set_label("n/a")

        mic_pct, _mic_muted = self._wpctl_get_volume("@DEFAULT_AUDIO_SOURCE@")
        if mic_pct is not None:
            self.mic_scale.set_value(mic_pct)
            self.mic_value_label.set_label(f"{mic_pct}%")
        else:
            self.mic_value_label.set_label("n/a")
        self._audio_refresh_pending = False

    def _on_volume_changed(self, scale):
        if self._audio_refresh_pending:
            return  # programmatic set from _refresh_audio_state, not a user drag
        pct = int(scale.get_value())
        self.vol_value_label.set_label(f"{pct}%")
        spawn("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{pct / 100:.2f}")

    def _on_mic_changed(self, scale):
        if self._audio_refresh_pending:
            return
        pct = int(scale.get_value())
        self.mic_value_label.set_label(f"{pct}%")
        spawn("wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{pct / 100:.2f}")

    def _on_mute_toggle(self, _widget, _event):
        spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
        # wpctl's own state is the source of truth; re-read rather than
        # guess the new state locally, so a stale guess can't drift from
        # what's actually muted (e.g. if something else toggled it too).
        GLib.timeout_add(120, self._refresh_audio_state_once)

    def _refresh_audio_state_once(self):
        self._refresh_audio_state()
        return False  # one-shot, not a repeating timeout

    # -- theming ---------------------------------------------------------

    def _load_css(self):
        """Same one-provider-per-load pattern as island._load_css: parse the
        palette first so @settings_accent exists before colors.css/style.css
        load, then load header + colors.css + style.css together."""
        self.palette = load_palette(COLORS_CSS)
        header = palette_to_css_header(self.palette)

        try:
            with open(COLORS_CSS) as fh:
                colors_css = fh.read()
        except OSError:
            colors_css = ""
        try:
            with open(STYLE_CSS) as fh:
                style_css = fh.read()
        except OSError:
            style_css = ""

        if not hasattr(self, "provider"):
            self.provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), self.provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        try:
            self.provider.load_from_data(
                (header + colors_css + "\n" + style_css).encode())
        except GLib.Error as exc:
            print("settings: css error:", exc)

    def reload(self, *_args):
        """SIGUSR1 handler -- matches retheme's post-hook convention for
        every other surface in the rice."""
        self._load_css()
        if hasattr(self, "swatch_box"):
            self._refresh_swatches()
        return True

    # -- polling -----------------------------------------------------------

    def _poll(self):
        cpu_pct = self.cpu_sampler.percent()
        self.cpu_value.set_label(f"{cpu_pct:.0f}%")
        self.cpu_sub.set_label(f"{os.cpu_count()} threads")
        set_bar_level(self.cpu_bar, cpu_pct)

        used_gb, total_gb, ram_pct = read_mem()
        self.ram_value.set_label(f"{ram_pct:.0f}%")
        self.ram_sub.set_label(f"{used_gb:.1f} / {total_gb:.1f} GB")
        set_bar_level(self.ram_bar, ram_pct)

        busy, vram_used, vram_total = read_gpu(self.gpu_card)
        if busy is not None:
            self.gpu_value.set_label(f"{busy:.0f}%")
            if vram_used is not None and vram_total:
                self.gpu_sub.set_label(f"{vram_used:.0f} / {vram_total:.0f} MB VRAM")
            else:
                self.gpu_sub.set_label("VRAM n/a")
            set_bar_level(self.gpu_bar, busy)
        else:
            self.gpu_value.set_label("n/a")
            self.gpu_sub.set_label("no amdgpu sysfs node found")
            set_bar_level(self.gpu_bar, 0)

        rx, tx = self.net_sampler.rates_kbps()
        total_kbps = rx + tx
        if total_kbps > 1024:
            self.net_value.set_label(f"{total_kbps / 1024:.1f} MB/s")
        else:
            self.net_value.set_label(f"{total_kbps:.0f} KB/s")
        self.net_sub.set_label(f"↓{rx:.0f} KB/s  ↑{tx:.0f} KB/s")
        set_bar_level(self.net_bar, min(100.0, total_kbps / 50))  # rough scale

        used_disk, total_disk, disk_pct = read_disk_usage("/")
        self.disk_value.set_label(f"{disk_pct:.0f}%")
        self.disk_sub.set_label(f"{used_disk:.0f} / {total_disk:.0f} GB")
        set_bar_level(self.disk_bar, disk_pct)

        temp = read_cpu_temp(self.cpu_temp_sensor)
        if temp is not None:
            self.temp_value.set_label(f"{temp:.0f}°C")
            self.temp_sub.set_label("package")
            # temperature isn't a 0-100 usage fraction, so scale the bar
            # against a rough 30-95°C band instead of raw degrees
            temp_pct = max(0.0, min(100.0, (temp - 30) / (95 - 30) * 100))
            set_bar_level(self.temp_bar, temp_pct)
        else:
            self.temp_value.set_label("n/a")
            self.temp_sub.set_label("no k10temp/coretemp sensor found")
            set_bar_level(self.temp_bar, 0)

        for bar, pct in zip(self.core_bars, self.per_core_sampler.percents()):
            set_bar_level(bar, pct)

        self.uptime_label.set_label(f"Uptime: {read_uptime()}")

        return True  # keep the GLib timeout alive


def main():
    settings = SettingsWindow()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, settings.reload)
    Gtk.main()


if __name__ == "__main__":
    main()
