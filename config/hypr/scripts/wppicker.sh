#!/usr/bin/env bash
# Wallpaper picker: grid of previews, names only, no paths.
# Selection is handed to `retheme`, which owns matugen + wallpaper painting.
set -uo pipefail
PATH="$HOME/.local/bin:$PATH"

WALLPAPER_DIR="$HOME/.config/wallpapers"
THUMBS="$HOME/.cache/wallpaper-thumbs"
mkdir -p "$THUMBS"

notify() { command -v notify-send >/dev/null 2>&1 && notify-send "$@" 2>/dev/null || true; }
[ -d "$WALLPAPER_DIR" ] || { notify "Wallpaper" "No such dir: $WALLPAPER_DIR"; exit 1; }

# "a_view_of-the_ocean.jpg" -> "A View Of The Ocean"
prettify() {
    local n="${1%.*}"
    n="${n//[-_.]/ }"
    n=$(printf '%s' "$n" | tr -s ' ')
    printf '%s' "$n" | sed -e 's/\b\(.\)/\u\1/g'
}

# rofi can't thumbnail video; cache one frame per clip.
thumb_for() {
    local f="$1" src="$WALLPAPER_DIR/$1" t
    case "${f,,}" in
        *.mp4|*.webm|*.mkv|*.mov|*.avi)
            t="$THUMBS/${f%.*}.png"
            if [ ! -f "$t" ] || [ "$src" -nt "$t" ]; then
                ffmpeg -y -ss 3 -i "$src" -frames:v 1 -vf scale=480:-1 "$t" >/dev/null 2>&1 \
                  || ffmpeg -y -i "$src" -frames:v 1 -vf scale=480:-1 "$t" >/dev/null 2>&1
            fi
            [ -f "$t" ] && printf '%s' "$t" || printf '%s' "$src"
            ;;
        *) printf '%s' "$src" ;;
    esac
}

FOLDER_ICON=/usr/share/icons/Adwaita/scalable/places/folder.svg
[ -f "$FOLDER_ICON" ] || FOLDER_ICON=folder

open_folder() {
    if command -v nautilus >/dev/null 2>&1; then
        setsid nautilus "$WALLPAPER_DIR" >/dev/null 2>&1 </dev/null &
    else
        setsid xdg-open "$WALLPAPER_DIR" >/dev/null 2>&1 </dev/null &
    fi
}

# Index 0 is the "open folder" tile, so wallpaper i lives at index i+1.
names=( "Open Folder" ); files=( "" ); icons=( "$FOLDER_ICON" )
while IFS= read -r f; do
    [ -n "$f" ] || continue
    names+=( "$(prettify "$f")" )
    files+=( "$f" )
    icons+=( "$(thumb_for "$f")" )
done < <(cd "$WALLPAPER_DIR" && ls -t -- *.jpg *.jpeg *.png *.gif *.mp4 *.webm *.mkv 2>/dev/null)

[ "${#files[@]}" -gt 0 ] || { notify "Wallpaper" "No wallpapers found"; exit 1; }

# NUL cannot survive a bash variable, so write the icon protocol straight to
# the pipe. Storing this in a string silently strips the \0 and rofi then
# renders the whole "name<NUL>icon<US>path" blob as the visible label.
emit() {
    local i
    for i in "${!files[@]}"; do
        printf '%s\0icon\x1f%s\n' "${names[$i]}" "${icons[$i]}"
    done
}

GRID='window { width: 1500px; }
      mainbox { children: [ "inputbar", "listview" ]; }
      listview { columns: 4; lines: 2; spacing: 14px; }
      element { orientation: vertical; padding: 10px; }
      element-icon { size: 300px; }
      element-text { horizontal-align: 0.5; vertical-align: 0.5; }'

# -format i returns the index, so the label never has to round-trip.
# rofi exits 10 when -kb-custom-1 (Ctrl+O) is pressed.
IDX=$(emit | rofi -dmenu -i -p "wallpaper" -show-icons -format i \
        -kb-custom-1 "Control+o" -theme-str "$GRID"); rc=$?
if [ "$rc" -eq 10 ]; then open_folder; exit 0; fi
[ "$rc" -eq 0 ] || exit 0
[ -n "${IDX:-}" ] || exit 0
case "$IDX" in ''|*[!0-9]*) exit 0 ;; esac

# The folder tile.
if [ "$IDX" -eq 0 ]; then open_folder; exit 0; fi

WP="$WALLPAPER_DIR/${files[$IDX]}"
[ -f "$WP" ] || { notify "Wallpaper" "Not found: ${files[$IDX]}"; exit 1; }

if out=$(retheme "$WP" 2>&1); then
    notify "Wallpaper" "${names[$IDX]}"
else
    notify "Wallpaper failed" "$(printf '%s' "$out" | tail -2)"
    printf '%s\n' "$out" >&2
    exit 1
fi
