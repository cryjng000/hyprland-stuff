#!/usr/bin/env bash
# Link this repo into place. Anything already there is moved aside first.
#
#   ./install.sh          link everything
#   ./install.sh --dry    show what would happen, touch nothing
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP="$HOME/.local/share/dotfiles-backup-$(date +%Y%m%d-%H%M%S)"
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

link() {
    local src="$REPO/$1" dst="$HOME/$2"
    if [ $DRY -eq 1 ]; then
        printf '  %s -> %s\n' "${dst/#$HOME/\~}" "${src/#$REPO/repo}"
        return
    fi
    mkdir -p "$(dirname "$dst")"
    # Already the right symlink? nothing to do.
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        printf '  ok   %s\n' "${dst/#$HOME/\~}"
        return
    fi
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        mkdir -p "$BACKUP/$(dirname "$2")"
        mv "$dst" "$BACKUP/$2"
        printf '  bak  %s\n' "${dst/#$HOME/\~}"
    fi
    ln -s "$src" "$dst"
    printf '  link %s\n' "${dst/#$HOME/\~}"
}

echo "==> config"
# Whole directories: these hold nothing but tracked, hand-written files.
for d in hypr waybar island matugen beatsync; do
    link "config/$d" ".config/$d"
done
# Single files: these directories also hold matugen-generated colour files,
# so linking the directory itself would fight the generator.
link config/kitty/kitty.conf      .config/kitty/kitty.conf
link config/rofi/config.rasi      .config/rofi/config.rasi
link config/gtk-3.0/settings.ini  .config/gtk-3.0/settings.ini
link config/gtk-3.0/gtk.css       .config/gtk-3.0/gtk.css
link config/gtk-4.0/settings.ini  .config/gtk-4.0/settings.ini
link config/gtk-4.0/gtk.css       .config/gtk-4.0/gtk.css

echo "==> scripts"
for f in "$REPO"/local/bin/*; do
    link "local/bin/$(basename "$f")" ".local/bin/$(basename "$f")"
done

if [ $DRY -eq 1 ]; then
    echo; echo "dry run -- nothing changed."
    exit 0
fi

[ -d "$BACKUP" ] && { echo; echo "displaced files -> $BACKUP"; }

cat <<'NOTE'

==> next
  1. Colour files are NOT tracked -- matugen generates them. Paint them once:
       retheme ~/.config/wallpapers/<some-wallpaper>
     Nothing is themed until this has run at least once.
  2. Put wallpapers in ~/.config/wallpapers (not tracked -- see README).
  3. Restart Hyprland, or: hyprctl reload
NOTE
