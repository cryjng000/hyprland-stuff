
-- Hyprland config. Edited by hand -- see https://wiki.hypr.land
-- Backups of earlier versions: hyprland.lua.bak*

-- This is an example Hyprland Lua config file.
-- Refer to the wiki for more information.
-- https://wiki.hypr.land/Configuring/Start/

-- Please note not all available settings / options are set here.
-- For a full list, see the wiki

-- You can (and should!!) split this configuration into multiple files
-- Create your files separately and then require them like this:
-- require("myColors")


------------------
---- MONITORS ----
------------------

-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
hl.monitor({
    output   = "HDMI-A-1",
    mode     = "1920x1080@60",
    position = "0x0",
    scale    = 1,
})


---------------------
---- MY PROGRAMS ----
---------------------

-- Set programs that you use
-- kitty from ~/.local/kitty.app, not /usr/bin: Ubuntu ships 0.32.2, which
-- predates cursor_trail. Absolute path because Hyprland spawns without
-- ~/.local/bin on PATH.
local terminal    = "$HOME/.local/kitty.app/bin/kitty"
local fileManager = "nautilus"
local menu        = "rofi -show drun"  -- matugen-themed; fuzzel.ini kept as a fallback


-------------------
---- AUTOSTART ----
-------------------

-- See https://wiki.hypr.land/Configuring/Basics/Autostart/

-- Autostart necessary processes (like notifications daemons, status bars, etc.)
-- Or execute your favorite apps at launch like this:
--
-- hl.on("hyprland.start", function () 
--   hl.exec_cmd(terminal)
--   hl.exec_cmd("nm-applet")
--   hl.exec_cmd("waybar & hyprpaper & firefox")
-- end)

-- Ubuntu ships waybar 0.9.24, which looks for Hyprland's IPC socket in
-- /tmp/hypr. Hyprland 0.56 moved it to $XDG_RUNTIME_DIR/hypr, and /tmp is
-- cleared on boot -- so relink it every start, before waybar comes up.
hl.on("hyprland.start", function()
    hl.exec_cmd("ln -sfn \"$XDG_RUNTIME_DIR/hypr\" /tmp/hypr")
    hl.exec_cmd("waybar")
    hl.exec_cmd("mako")                                       -- notifications

    -- Cursor: hyprctl setcursor makes the compositor's own cursor Bibata even
    -- if a client never asks; the env vars below cover clients it spawns.
    hl.exec_cmd("~/.local/bin/fix-cursor.sh")

    -- Repaint the wallpaper pywal last themed from (path lives in ~/.cache/wal/wal).
    -- set-wallpaper picks swaybg or mpvpaper depending on the file type.
    hl.exec_cmd("~/.local/bin/set-wallpaper \"$(cat ~/.cache/current_wallpaper)\"")

    -- Audio-reactive beat + colour daemon (Spotify UI, waybar, window borders).
    hl.exec_cmd("~/.local/bin/beatd")

    -- Dynamic island: layer-shell overlay in the gap left in waybar's centre.
    hl.exec_cmd("python3 ~/.config/island/island.py")

    -- Not installed yet:
    -- hl.exec_cmd("swayidle -w timeout 600 'swaylock -f'")   -- lock when idle
end)


-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Environment-variables/

hl.env("XCURSOR_THEME", "Bibata_Ghost")
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")


-----------------------
----- PERMISSIONS -----
-----------------------

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Permissions/
-- Please note permission changes here require a Hyprland restart and are not applied on-the-fly
-- for security reasons

-- hl.config({
--   ecosystem = {
--     enforce_permissions = true,
--   },
-- })

-- hl.permission("/usr/(bin|local/bin)/grim", "screencopy", "allow")
-- hl.permission("/usr/(lib|libexec|lib64)/xdg-desktop-portal-hyprland", "screencopy", "allow")
-- hl.permission("/usr/(bin|local/bin)/hyprpm", "plugin", "allow")


-----------------------
---- LOOK AND FEEL ----
-----------------------

-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    general = {
        gaps_in  = 5,
        gaps_out = 10,

        border_size = 2,

        col = {
            active_border   = { colors = {"rgba(33ccffee)", "rgba(00ff99ee)"}, angle = 45 },
            inactive_border = "rgba(595959aa)",
        },

        -- Set to true to enable resizing windows by clicking and dragging on borders and gaps
        resize_on_border = true,

        -- Please see https://wiki.hypr.land/Configuring/Advanced-and-Cool/Tearing/ before you turn this on
        allow_tearing = false,

        layout = "dwindle",
    },

    decoration = {
        rounding       = 10,
        rounding_power = 2,

        -- Change transparency of focused and unfocused windows
        active_opacity   = 1.0,
        inactive_opacity = 1.0,  -- 0.8 made unfocused windows look ghosted

        shadow = {
            enabled      = false,
            range        = 4,
            render_power = 3,
            color        = 0xee1a1a1a,
        },

        blur = {
            enabled           = true,
            size              = 8,
            passes            = 3,
            ignore_opacity    = true,
            new_optimizations = true,
            xray              = true,   -- blur shows the wallpaper, not windows behind
            popups            = true,
            special           = false,
            vibrancy          = 0.1696,
        },
    },

    animations = {
        enabled = true,
    },
})

-- Window border colours from matugen's generated palette.
-- ~/.config/hypr/colors.conf is regenerated by `matugen image <wallpaper>`
-- and holds Material You roles as $name = rgba(rrggbbaa).
local function matugen_colors()
    local f = io.open(os.getenv("HOME") .. "/.config/hypr/colors.conf", "r")
    if not f then return nil end
    local c = {}
    for line in f:lines() do
        local name, hex = line:match("^%$([%w_]+)%s*=%s*rgba%((%x+)%)")
        if name and hex then c[name] = hex end
    end
    f:close()
    return c
end

local mc = matugen_colors()
if mc and mc.outline and mc.outline_variant then
    hl.config({
        general = {
            col = {
                active_border   = "rgba(" .. mc.outline .. ")",
                inactive_border = "rgba(" .. mc.outline_variant .. ")",
            },
        },
    })
end

-- Default curves and animations, see https://wiki.hypr.land/Configuring/Advanced-and-Cool/Animations/
hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1}    } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1}    } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}       } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1}    } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}     } })

-- Default springs
hl.curve("easy",           { type = "spring", mass = 1, stiffness = 238.1191, dampening = 24.21279333 })

hl.animation({ leaf = "global",        enabled = true,  speed = 10,   bezier = "default" })
hl.animation({ leaf = "border",        enabled = true,  speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows",       enabled = true,  speed = 4.79, spring = "easy" })
hl.animation({ leaf = "windowsIn",     enabled = true,  speed = 4.1,  spring = "easy",         style = "popin 87%" })
hl.animation({ leaf = "windowsOut",    enabled = true,  speed = 1.49, bezier = "linear",       style = "popin 87%" })
hl.animation({ leaf = "fadeIn",        enabled = true,  speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut",       enabled = true,  speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade",          enabled = true,  speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers",        enabled = true,  speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn",      enabled = true,  speed = 4,    bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut",     enabled = true,  speed = 1.5,  bezier = "linear",       style = "fade" })
hl.animation({ leaf = "fadeLayersIn",  enabled = true,  speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true,  speed = 1.39, bezier = "almostLinear" })
hl.animation({ leaf = "workspaces",    enabled = true,  speed = 2.8, bezier = "easeOutQuint", style = "slidevert fade" })
hl.animation({ leaf = "workspacesIn",  enabled = true,  speed = 3.2, bezier = "easeOutQuint",         style = "slidevert 40%" })
hl.animation({ leaf = "workspacesOut", enabled = true,  speed = 1.9, bezier = "linear",       style = "fade" })
hl.animation({ leaf = "zoomFactor",    enabled = true,  speed = 7,    bezier = "quick" })

-- Ref https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
-- "Smart gaps" / "No gaps when only"
-- uncomment all if you wish to use that.
-- hl.workspace_rule({ workspace = "w[tv1]", gaps_out = 0, gaps_in = 0 })
-- hl.workspace_rule({ workspace = "f[1]",   gaps_out = 0, gaps_in = 0 })
-- hl.window_rule({
--     name  = "no-gaps-wtv1",
--     match = { float = false, workspace = "w[tv1]" },
--     border_size = 0,
--     rounding    = 0,
-- })
-- hl.window_rule({
--     name  = "no-gaps-f1",
--     match = { float = false, workspace = "f[1]" },
--     border_size = 0,
--     rounding    = 0,
-- })

-- See https://wiki.hypr.land/Configuring/Layouts/Dwindle-Layout/ for more
hl.config({
    dwindle = {
        preserve_split = true, -- You probably want this
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Master-Layout/ for more
hl.config({
    master = {
        new_status = "master",
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Scrolling-Layout/ for more
hl.config({
    scrolling = {
        fullscreen_on_one_column = true,
    },
})

----------------
----  MISC  ----
----------------

hl.config({
    misc = {
        force_default_wallpaper = -1,    -- Set to 0 or 1 to disable the anime mascot wallpapers
        disable_hyprland_logo   = true,  -- If true disables the random hyprland logo / anime girl background. :(
    },
})


---------------
---- INPUT ----
---------------

hl.config({
    input = {
        kb_layout  = "tr",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        follow_mouse = 1,

        sensitivity = 0, -- -1.0 - 1.0, 0 means no modification.

        touchpad = {
            natural_scroll = false,
        },
    },
})

hl.gesture({
    fingers = 3,
    direction = "horizontal",
    action = "workspace"
})

-- Example per-device config
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/ for more
hl.device({
    name        = "epic-mouse-v1",
    sensitivity = -0.5,
})


---------------------
---- KEYBINDINGS ----
---------------------

local mainMod = "SUPER" -- Sets "Windows" key as main modifier

-- Example binds, see https://wiki.hypr.land/Configuring/Basics/Binds/ for more
hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal))
local closeWindowBind = hl.bind(mainMod .. " + C", hl.dsp.window.close())
-- closeWindowBind:set_enabled(false)
hl.bind(mainMod .. " + M", hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + F", hl.dsp.exec_cmd(fileManager))  -- same as E; F for "files"
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(menu))
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd("$HOME/.local/kitty.app/bin/kitty --class cava -e cava"))  -- audio visualiser
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd("~/.local/bin/island toggle"))  -- pin the island open
hl.bind(mainMod .. " + W", hl.dsp.exec_cmd("~/.config/hypr/scripts/wppicker.sh"))  -- wallpaper picker

-- Screenshots -> ~/Pictures/Screenshots + clipboard. Logic lives in
-- ~/.local/bin/screenshot so the shell quoting stays out of this file.
hl.bind("Print",                 hl.dsp.exec_cmd("~/.local/bin/screenshot full"))
hl.bind("SHIFT + Print",         hl.dsp.exec_cmd("~/.local/bin/screenshot region"))
hl.bind(mainMod .. " + Print",   hl.dsp.exec_cmd("~/.local/bin/screenshot window"))
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo())
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"))    -- dwindle only

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Alt + Tab cycles windows on the CURRENT workspace (Shift reverses).
hl.bind("ALT + Tab",         hl.dsp.window.cycle_next())
hl.bind("ALT + SHIFT + Tab", hl.dsp.window.cycle_next({ next = false }))

-- Switch workspaces with mainMod + [0-9]
-- Move active window to a workspace with mainMod + SHIFT + [0-9]
for i = 1, 10 do
    local key = i % 10 -- 10 maps to key 0
    hl.bind(mainMod .. " + " .. key,             hl.dsp.focus({ workspace = i}))
    hl.bind(mainMod .. " + SHIFT + " .. key,     hl.dsp.window.move({ workspace = i }))
end

-- Example special workspace (scratchpad)
hl.bind(mainMod .. " + S",         hl.dsp.workspace.toggle_special("magic"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

-- Super + N: hide everything by jumping to the first EMPTY workspace.
-- Shift takes the focused window along to that fresh desktop.
hl.bind(mainMod .. " + N",         hl.dsp.focus({ workspace = "empty" }))
hl.bind(mainMod .. " + SHIFT + N", hl.dsp.window.move({ workspace = "empty" }))

-- Scroll through existing workspaces with mainMod + scroll
hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

-- Move/resize windows with mainMod + LMB/RMB and dragging
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Laptop multimedia keys for volume and LCD brightness
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),                  { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),                  { locked = true, repeating = true })

-- Requires playerctl.
-- `-p spotify,%any` matters: with no -p, playerctl targets whichever MPRIS
-- player it happens to enumerate first, and a stale WebKit app sorts ahead of
-- Spotify -- so the headset's media button was toggling a dead player. This
-- prefers Spotify and falls back to anything else that is running.
local PLAYER = "playerctl -p spotify,%any"
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd(PLAYER .. " next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd(PLAYER .. " play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd(PLAYER .. " play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd(PLAYER .. " previous"),   { locked = true })
hl.bind("XF86AudioStop",  hl.dsp.exec_cmd(PLAYER .. " stop"),       { locked = true })


--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- and https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/

-- Example window rules that are useful

local suppressMaximizeRule = hl.window_rule({
    -- Ignore maximize requests from all apps. You'll probably like this.
    name  = "suppress-maximize-events",
    match = { class = ".*" },

    suppress_event = "maximize",
})
-- suppressMaximizeRule:set_enabled(false)

hl.window_rule({
    -- Fix some dragging issues with XWayland
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = true,
})

-- Layer rules also return a handle.
-- local overlayLayerRule = hl.layer_rule({
--     name  = "no-anim-overlay",
--     match = { namespace = "^my-overlay$" },
--     no_anim = true,
-- })
-- overlayLayerRule:set_enabled(false)

-- Frosted glass behind the dynamic island overlay. ignore_alpha keeps the
-- transparent area outside its rounded corners from being blurred into a
-- visible square.
hl.layer_rule({
    name  = "blur-island",
    match = { namespace = "^island$" },

    blur         = true,
    ignore_alpha = 0.35,
})

-- Same frosted-glass treatment for the two surfaces matugen now themes.
-- mako's layer surface is called `notifications`, fuzzel's is `launcher`.
-- Both panes sit at ~0.65-0.72 alpha over surface_container, which is only
-- legible with the blur behind them; ignore_alpha 0.35 keeps the fully
-- transparent area outside their rounded corners from blurring into a
-- visible rectangle (same reason as the island).
hl.layer_rule({
    name  = "blur-notifications",
    match = { namespace = "^notifications$" },

    blur         = true,
    ignore_alpha = 0.35,
})

hl.layer_rule({
    name  = "blur-launcher",
    match = { namespace = "^launcher$" },

    blur         = true,
    ignore_alpha = 0.35,
})

-- Hyprland-run windowrule
-- cava floats, centred, and keeps the terminal's transparency.
hl.window_rule({
    name  = "float-cava",
    match = { class = "^cava$" },

    float  = true,
    size   = "900 380",
    center = true,
})

hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})

-- OpenWhip's overlay is a fullscreen transparent window. Global blur (with
-- xray) paints the wallpaper through it, so it reads as a blurry rectangle
-- instead of being invisible. Strip every decoration off it.
hl.window_rule({
    name  = "openwhip-overlay",
    match = { class = "^openwhip$" },

    no_blur     = true,
    no_shadow   = true,
    no_dim      = true,
    no_anim     = true,
    rounding    = 0,
    border_size = 0,
    float       = true,
    pin         = true,

    -- The overlay must be hit-testable or the whip never sees mousemove.
    -- Hyprland's ViewHitTester skips windows that are no_focus or
    -- X11ShouldntFocus (Electron sets focusable:false); allows_input clears
    -- both. no_follow_mouse then keeps KEYBOARD focus on the terminal, so
    -- wtype's Ctrl-C still lands there while the pointer drives the whip.
    allows_input     = true,
    no_follow_mouse  = true,
    no_initial_focus = true,
})

-- Glassmorphic Spotify.
--
-- Unlike Vesktop, Spotify cannot be made transparent from the inside: it is
-- CEF (Chromium 146), and its switch table has no `enable-transparent-visuals`
-- (checked with `strings /usr/share/spotify/spotify`), so the BrowserWindow is
-- always opaque no matter what the Spicetify theme's CSS says. The window
-- alpha therefore has to come from here.
--
-- This fades text along with everything else, which is exactly what
-- inactive_opacity was rejected for above -- so it is kept mild at 0.85 and
-- the Glass theme compensates by pushing type contrast back up. blur is
-- already global (size 8 / passes 3 / xray), and ignore_opacity means the
-- wallpaper behind still gets blurred at full strength.
--
-- Same value active and inactive: Spotify is usually the unfocused window,
-- and a window that ghosts when you look away is the thing to avoid.
hl.window_rule({
    name  = "glass-spotify",
    match = { class = "^Spotify$" },

    opacity = "0.85 0.85",
})

-- Sober (Roblox) on the 5600G's Vega iGPU.
--
-- Decorations are per-frame GPU work, and on an APU that work competes with
-- the CPU for the same DDR4 bandwidth -- the actual bottleneck on Cezanne, not
-- shader throughput. The bigger reason to strip them is direct scanout:
-- Hyprland can hand a buffer straight to the display controller and skip
-- compositing entirely, but only for a plain, opaque, fullscreen window.
-- Rounding, a border, blur or a shadow each disqualify it. So this rule is
-- what makes fullscreen Sober cost the compositor nothing.
--
-- Note this only removes Hyprland's own drawing. Roblox's render settings --
-- texture quality included -- are untouched.
hl.window_rule({
    name  = "sober-perf",
    match = { class = "^org\\.vinegarhq\\.Sober$" },

    no_blur     = true,
    no_shadow   = true,
    no_dim      = true,
    no_anim     = true,
    rounding    = 0,
    border_size = 0,
    opacity     = "1.0 1.0",
})
