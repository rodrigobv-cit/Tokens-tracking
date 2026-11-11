#!/bin/sh
# Status line: model · dir basename · ctx %
input=$(cat)
if command -v jq >/dev/null 2>&1; then
  model=$(printf '%s' "$input" | jq -r '.model.display_name // empty' 2>/dev/null)
  dir=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // empty' 2>/dev/null)
  pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty' 2>/dev/null)
  sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
else
  out=$(printf '%s' "$input" | python3 -I -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
def g(o, *k):
    for x in k:
        if not isinstance(o, dict): return ""
        o = o.get(x)
    return "" if o is None else o
print(g(d, "model", "display_name"))
print(g(d, "workspace", "current_dir") or g(d, "cwd"))
print(g(d, "context_window", "used_percentage"))
print(g(d, "session_id"))
' 2>/dev/null)
  model=$(printf '%s\n' "$out" | sed -n 1p)
  dir=$(printf '%s\n' "$out" | sed -n 2p)
  pct=$(printf '%s\n' "$out" | sed -n 3p)
  sid=$(printf '%s\n' "$out" | sed -n 4p)
fi
[ -z "$model" ] && model="Claude"
base=$(basename "${dir:-.}")
if [ -n "$pct" ]; then
  n=$(LC_ALL=C awk -v p="$pct" 'BEGIN { printf "%d", p + 0.5 }' 2>/dev/null)
  # green below 25%, yellow 25-40%, red above 40%
  if [ "$n" -lt 25 ] 2>/dev/null; then color='\033[32m'
  elif [ "$n" -le 40 ] 2>/dev/null; then color='\033[33m'
  else color='\033[31m'
  fi
  ctx=$(printf '%b' "${color}ctx ${n}%\033[0m")
  # share the percentage with the token-log plugin (read by /token-start), one file per session
  case "$sid" in
    ''|*[!A-Za-z0-9_-]*) ;;
    *) d="${CLAUDE_CONTEXT_PCT_DIR:-$HOME/.claude/context-pct}"
       mkdir -p "$d" 2>/dev/null && printf '%s' "$n" > "$d/$sid.tmp" 2>/dev/null && mv "$d/$sid.tmp" "$d/$sid" 2>/dev/null ;;
  esac
else
  ctx="ctx n/a"
fi
printf '%s · %s · %s\n' "$model" "$base" "$ctx"
