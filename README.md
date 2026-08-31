# dotfiles

A Hyprland desktop built on Zorin OS 18.1 (Ubuntu 24.04 base), on a Ryzen 5 5600G
with Vega integrated graphics. Everything that has a colour is generated from the
current wallpaper by [matugen](https://github.com/InioX/matugen), so the whole
shell re-skins from one command.

- **Compositor** — Hyprland 0.56.2, configured in **Lua** (`hyprland.lua`), not `hyprland.conf`
- **Bar** — Waybar 0.9.24, on the [JaKooLit](https://github.com/JaKooLit) module layout
- **Notifications** — mako · **Launcher** — rofi 1.7.5 (fuzzel as fallback)
- **Terminal** — kitty 0.48.2 · **Wallpaper** — swaybg for images, mpvpaper for video
- **Extras** — a GTK dynamic island, and an audio-reactive beat daemon
- **Apps** — Spotify (spicetify) and Discord (Vesktop) themed to match

## The idea

There is exactly one source of colour. `~/.config/matugen/templates/` holds a
template per target; `retheme <wallpaper>` runs matugen over all of them and each
post-hook reloads the app in place. Nine surfaces re-skin together — Hyprland
window borders, waybar, the island, kitty, rofi, cava, fuzzel, mako, and GTK 3/4.

**The rendered colour files are deliberately not tracked here.** Only the
templates are. That keeps the repo from churning on every wallpaper change, and
it means a fresh clone has no colours until you run `retheme` once.

## Layout

```
config/
  hypr/        hyprland.lua + wallpaper picker
  waybar/      config.jsonc, Modules*, style.css, alternate presets in style/ and configs/
  island/      island.py — GTK layer-shell overlay in the bar's centre gap
  matugen/     config.toml + templates/  <- the source of truth for all colour
  beatsync/    beat-detection daemon settings
  kitty/ rofi/ gtk-3.0/ gtk-4.0/
  spicetify/   Glass theme for Spotify + the beatsync extension
  vesktop/     Vencord settings + the Glass Discord quickCss
local/bin/
  retheme          re-theme everything from a wallpaper (the main entry point)
  set-wallpaper    swaybg for images, mpvpaper for video
  rice             snapshot / restore a whole configuration
  beatd, beatctl   audio-reactive beat + colour daemon
  island           start/stop/toggle the dynamic island
  screenshot, powermenu, fix-cursor.sh, cava-colors
```

Every file is `$HOME`-relative — there are no hardcoded paths, so it installs
under any username.

## Install

```sh
git clone <this repo> ~/dotfiles
cd ~/dotfiles
./install.sh --dry     # see what would be linked
./install.sh           # link it; anything displaced is backed up with a timestamp
retheme ~/.config/wallpapers/some-wallpaper.jpg
```

`install.sh` symlinks whole directories where a directory holds only tracked
files, and single files where matugen also writes generated colours into the same
directory (kitty, rofi, gtk-3.0, gtk-4.0).

### Spotify and Discord

Both need one step that `install.sh` cannot do for you.

**Spotify** — the theme and extension are linked into `~/.config/spicetify`, but
spicetify still has to inject them:

```sh
spicetify config current_theme Glass color_scheme base
spicetify config extensions beatsync.js
spicetify apply
```

`config-xpui.ini` itself is **not tracked** — spicetify rewrites it on every
`apply` and it stores absolute paths to the Spotify install, which differ per
machine. The commands above set everything from it that matters.

**Discord** — the Vesktop files are copied into the flatpak's config directory
(see below for why they are not linked). Restart Vesktop afterwards; Vencord
reads `quickCss.css` at startup. `transparent: true` in the Vencord settings and
the Hyprland window rule are both required — either one alone leaves the window
opaque.

### Dependencies

From the repos: `waybar mako rofi cava swaybg grim slurp wl-clipboard
brightnessctl playerctl nautilus python3-gi gir1.2-gtk-3.0 python3-cairo`.

Not packaged on Ubuntu/Zorin, install separately:

- **matugen** — `cargo install matugen` (needs 4.x; the config uses the 4.x template syntax)
- **kitty** — the upstream installer, not the distro package. Zorin ships 0.32.2,
  which predates `cursor_trail`; `hyprland.lua` calls kitty by absolute path out of
  `~/.local/kitty.app` for this reason.
- **mpvpaper** — only needed for video wallpapers
- **Fonts** — JetBrainsMono Nerd Font (the bar, island, mako and kitty all assume it)
- **GTK theme** — [WhiteSur-gtk-theme](https://github.com/vinceliuice/WhiteSur-gtk-theme)
  into `~/.themes`, and [Bibata](https://github.com/ful1e5/Bibata_Cursor) cursors
  into `~/.icons` (this setup uses a recoloured `Bibata_Ghost`)

## Things worth knowing

These are all deliberate, and each is commented where it applies.

- **Waybar 0.9.24 looks for Hyprland's IPC socket in `/tmp/hypr`**, but Hyprland
  0.56 moved it to `$XDG_RUNTIME_DIR/hypr`. `hyprland.lua` relinks it on every
  start, before waybar comes up. Newer waybar doesn't need this.
- **Waybar's centre is intentionally empty.** The floating GTK island owns that
  gap and would be drawn over by anything placed there. A waybar-native island
  (`group/island` in `UserModules`, `scripts/island.sh`) is kept for reference but
  is in no module list.
- **`temperature` uses `hwmon-path-abs`, not `hwmon-path`.** The `hwmonN` numbers
  shuffle across boots, and the stock module drifted onto the nvme sensor.
- **`playerctl` is always called as `-p spotify,%any`.** With no `-p` it targets
  whichever MPRIS player it enumerates first, and a stale WebKit player sorts
  ahead of Spotify — media keys end up driving a dead player.
- **Spotify's transparency comes from a Hyprland window rule**, not from CSS.
  Spotify is CEF and its switch table has no `enable-transparent-visuals`, so the
  window is opaque no matter what a Spicetify theme asks for.
- **Vesktop's config is copied, not symlinked.** Vesktop is a flatpak and its
  sandbox is granted only `xdg-download`, `xdg-pictures`, `xdg-videos`,
  `~/.icons` and `~/.steam`. A symlink into `~/dotfiles` resolves to nothing
  from inside the app, so `install.sh` copies those three files in. Edit them
  here and re-run it; changes made inside the client have to be copied back.
- **Discord's transparency is two-layered, unlike Spotify's.** Electron does
  honour `transparent: true`, so the window itself can be see-through — but
  every surface inside it is painted by Discord's own CSS tokens, which
  `quickCss.css` has to clear one family at a time. Tune the four `--glass-*`
  alphas at the top of that file; the rest derives from them.
- **Sober (Roblox) has every decoration stripped.** Rounding, borders, blur and
  shadows each disqualify a window from direct scanout; without them Hyprland can
  hand the buffer straight to the display controller, which matters on an APU
  where the GPU and CPU share DDR4 bandwidth.
- **`cava-colors` is superseded.** It reads the old pywal palette; cava is now
  themed by matugen through `templates/matugen-cava`. Kept only for reference.

## Not included

- **Wallpapers** (`~/.config/wallpapers`) — ~218 MB, too big to track. Point
  `retheme` at any directory of images or videos.
- **Generated colour files** — see `.gitignore`; run `retheme` to produce them.

## Known gaps

Honest list of what this setup does not have yet.

- **No lock screen and no idle daemon.** hyprlock/hypridle/swaylock/swayidle are
  all absent, so the machine never locks. `powermenu`'s Lock entry detects this
  and says so rather than failing silently.
- **No `xdg-desktop-portal-hyprland`.** Screencast and screenshot are routed to
  `xdg-desktop-portal-wlr` via `~/.config/xdg-desktop-portal/hyprland-portals.conf`.
  That works, but wlr can only share a whole output — there is no per-window picker.
- **The `WhiteSur-dark` icon theme is referenced but not installed.** Both
  `gtk-3.0/settings.ini` and gsettings ask for it; with nothing to resolve, GTK
  falls back to Adwaita. Install
  [WhiteSur-icon-theme](https://github.com/vinceliuice/WhiteSur-icon-theme) to get
  the intended icons.
- **No clipboard history manager.**

## Credit

Waybar module layout and the alternate presets in `waybar/style/` and
`waybar/configs/` come from [JaKooLit's Hyprland dotfiles](https://github.com/JaKooLit).
