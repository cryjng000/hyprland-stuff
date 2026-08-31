#!/usr/bin/env bash
# Waybar "dynamic island" — the always-visible half of group/island.
#
# It shows whatever is most interesting right now, in priority order:
#   offline  >  music playing  >  music paused  >  system stats
# Hovering the pill opens the drawer (network/cpu/mem/temp/disk) defined in
# UserModules; this script only drives the collapsed state and the tooltip.
#
# Runs as a continuous module (no "interval" in the config): the loop keeps its
# own state, so the CPU delta needs no cache file and we fork once per tick
# instead of four times.

MAX_TITLE=38          # characters before the track line gets an ellipsis
PLAYERS="${ISLAND_PLAYERS:-spotify,%any}"   # bare playerctl grabs a stale WebKit player, see memory

# k10temp lands on a different hwmonN across boots; resolve it by name once.
cpu_temp_file=""
for h in /sys/class/hwmon/hwmon*; do
    [[ -r "$h/name" ]] || continue
    if [[ "$(<"$h/name")" == "k10temp" ]]; then cpu_temp_file="$h/temp1_input"; break; fi
done
[[ -z $cpu_temp_file ]] && cpu_temp_file="/sys/class/thermal/thermal_zone0/temp"

# JSON string escaping. Titles routinely contain quotes and the odd backslash.
jesc() {
    local s=${1//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    s=${s//$'\r'/}
    s=${s//$'\t'/ }
    printf '%s' "$s"
}

# Pango escaping. Waybar parses both label and tooltip as markup, so an
# ampersand in an album name would otherwise blank the module.
pesc() {
    # bash 5.2 expands an unescaped & in the replacement to the matched text,
    # so every & below has to be backslash-escaped.
    local s=${1//&/\&amp;}
    s=${s//</\&lt;}
    s=${s//>/\&gt;}
    printf '%s' "$s"
}

trunc() {
    local s=$1
    (( ${#s} > MAX_TITLE )) && s="${s:0:MAX_TITLE-1}…"
    printf '%s' "$s"
}

hms() { # microseconds -> m:ss
    local t=$(( ${1:-0} / 1000000 ))
    printf '%d:%02d' $(( t / 60 )) $(( t % 60 ))
}

prev_idle=0 prev_total=0
read_cpu() {
    local _ u n s i rest idle total
    read -r _ u n s i rest < /proc/stat
    idle=$i
    total=$(( u + n + s + i ))
    for f in $rest; do total=$(( total + f )); done
    if (( prev_total > 0 && total > prev_total )); then
        cpu_pct=$(( 100 * ( (total - prev_total) - (idle - prev_idle) ) / (total - prev_total) ))
    else
        cpu_pct=0
    fi
    prev_idle=$idle prev_total=$total
}

read_mem() {
    local kb_total=0 kb_avail=0 k v
    while read -r k v _; do
        case $k in
            MemTotal:)     kb_total=$v ;;
            MemAvailable:) kb_avail=$v; break ;;
        esac
    done < /proc/meminfo
    mem_used_gb=$(( (kb_total - kb_avail) * 10 / 1048576 ))   # tenths of a GiB
    mem_total_gb=$(( kb_total * 10 / 1048576 ))
    (( kb_total > 0 )) && mem_pct=$(( 100 * (kb_total - kb_avail) / kb_total )) || mem_pct=0
}

read_temp() {
    if [[ -r $cpu_temp_file ]]; then
        cpu_c=$(( $(<"$cpu_temp_file") / 1000 ))
    else
        cpu_c=0
    fi
}

read_net() {
    net_iface=$(ip -o route show default 2>/dev/null | awk '{print $5; exit}')
    if [[ -z $net_iface ]]; then
        net_up=0 net_label="Offline" net_ip=""
        return
    fi
    net_up=1
    net_ip=$(ip -o -4 addr show dev "$net_iface" 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')
    if [[ -d /sys/class/net/$net_iface/wireless ]]; then
        net_label=$(iwgetid -r 2>/dev/null); [[ -z $net_label ]] && net_label="Wi-Fi"
    else
        net_label="Ethernet"
    fi
}

emit() { # text, tooltip, class
    printf '{"text":"%s","tooltip":"%s","class":%s}\n' \
        "$(jesc "$1")" "$(jesc "$2")" "$3"
}

while :; do
    read_cpu; read_mem; read_temp; read_net

    stats=$(printf '󰍛 %d%%   󰾆 %d.%dG   󰔐 %d°' \
        "$cpu_pct" "$((mem_used_gb/10))" "$((mem_used_gb%10))" "$cpu_c")

    sys_tip=$(printf 'CPU  %d%%  ·  %d°C\nRAM  %d.%dG / %d.%dG  (%d%%)\nNet  %s' \
        "$cpu_pct" "$cpu_c" \
        "$((mem_used_gb/10))" "$((mem_used_gb%10))" \
        "$((mem_total_gb/10))" "$((mem_total_gb%10))" "$mem_pct" \
        "$( ((net_up)) && printf '%s  %s' "$net_label" "$net_ip" || printf 'disconnected' )")

    # One dbus round trip for everything we need about the player.
    if md=$(playerctl -p "$PLAYERS" metadata \
            --format '{{status}}|{{xesam:title}}|{{xesam:artist}}|{{xesam:album}}|{{mpris:length}}|{{position}}' 2>/dev/null); then
        IFS='|' read -r p_status p_title p_artist p_album p_len p_pos <<< "$md"
    else
        p_status="" p_title=""
    fi

    if (( net_up == 0 )); then
        emit "󰤭  Offline" "$(pesc "No default route — check the cable or nmcli")" '["alert"]'

    elif [[ -n $p_title && ( $p_status == Playing || $p_status == Paused ) ]]; then
        if [[ $p_status == Playing ]]; then icon="󰎈"; cls='["music","playing"]'
        else                                icon="󰏤"; cls='["music","paused"]'; fi

        # escape=false on the module, so the label needs pango-escaping too
        line="$icon  $(pesc "$(trunc "$p_title")")"
        [[ -n $p_artist ]] && line="$line · $(pesc "$(trunc "$p_artist")")"

        # 16-cell progress bar, filled from the current position.
        bar=""
        if [[ ${p_len:-0} =~ ^[0-9]+$ ]] && (( p_len > 0 )); then
            filled=$(( 16 * ${p_pos:-0} / p_len )); (( filled > 16 )) && filled=16
            for ((i = 0; i < 16; i++)); do
                (( i < filled )) && bar+="━" || bar+="─"
            done
            bar=$(printf '\n%s  %s / %s' "$bar" "$(hms "${p_pos:-0}")" "$(hms "$p_len")")
        fi

        tip=$(printf '%s\n%s%s%s\n\n%s' \
            "$(pesc "$p_title")" \
            "$(pesc "$p_artist")" \
            "$( [[ -n $p_album ]] && printf '  ·  %s' "$(pesc "$p_album")" )" \
            "$bar" \
            "$sys_tip")
        emit "$line" "$tip" "$cls"

    else
        emit "$stats" "$(pesc "$sys_tip")" '["system"]'
    fi

    sleep 1
done
