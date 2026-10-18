#!/usr/bin/env bash
# Regenerate docs/screenshots/*.png: gtk4-broadwayd + headless Chromium (driven over CDP, see shoot.mjs).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/docs/screenshots"
CHROME=${CHROME:-$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | tail -1)}
PY=/usr/bin/python3
export CHROME
F=$(mktemp -d)
trap 'rm -rf "$F"' EXIT
mkdir -p "$OUT"
convert -size 1200x800 gradient:'#FFB37A'-'#FD5400' "$F/photo.png"
ffmpeg -loglevel error -f lavfi -i testsrc2=d=10:s=640x360 -f lavfi -i sine=d=10 -shortest -pix_fmt yuv420p "$F/clip.mp4"
ffmpeg -loglevel error -f lavfi -i testsrc2=d=120:s=1280x720:r=30 -f lavfi -i sine=d=120 -shortest \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$F/long.mp4"
export XDG_CONFIG_HOME="$F/config"   # default settings, never the user's

shot() {  # shot NAME WAIT_MS DEMO_JSON ARGS...
  local name=$1 wait=$2 demo=$3; shift 3
  local n=$((40 + RANDOM % 40))
  gtk4-broadwayd ":$n" >/dev/null 2>&1 & local bd=$!
  sleep 0.5
  GDK_BACKEND=broadway BROADWAY_DISPLAY=":$n" SATSUMA_DEMO="$demo" PYTHONPATH="$ROOT" \
    "$PY" -m satsuma "$@" >/dev/null 2>&1 & local app=$!
  sleep 1.2
  node "$ROOT/docs/shoot.mjs" "http://127.0.0.1:$((8080 + n))/" "$OUT/$name.png" "$wait" 520 700
  kill "$app" "$bd" 2>/dev/null || true
  wait "$app" "$bd" 2>/dev/null || true
}

shot drop-window 1500 '{}'
shot convert-wheel 1500 '{"hover": 1}' "$F/photo.png"
shot tools-wheel 1500 '{"mode": 1, "hover": 3}' "$F/clip.mp4"
shot actions-wheel 1500 '{"mode": 2, "hover": 0}' "$F/photo.png"
shot settings 2000 '{"settings": true}' "$F/photo.png"
shot dark-theme 1500 '{"theme": "dark", "mode": 1, "hover": 0}' "$F/clip.mp4"
shot progress 12000 '{"run": ["convert", "webm"]}' "$F/long.mp4"
rm -f "$F"/long*.webm "$F"/.satsuma-*
ls -la "$OUT"
