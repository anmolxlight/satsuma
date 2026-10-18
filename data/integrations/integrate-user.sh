#!/bin/sh
# Per-user file manager hooks that can't be installed system-wide: Nautilus script + Thunar action.
# Usage: integrate-user.sh [--remove]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus/scripts/Satsuma…"
UCA="${XDG_CONFIG_HOME:-$HOME/.config}/Thunar/uca.xml"

if [ "${1:-}" = "--remove" ]; then
  rm -f "$SCRIPT"
  [ -f "$UCA" ] && python3 - "$UCA" <<'PY'
import sys, xml.etree.ElementTree as ET
t = ET.parse(sys.argv[1]); root = t.getroot()
for a in root.findall("action"):
    if a.findtext("unique-id") == "satsuma-popup":
        root.remove(a)
t.write(sys.argv[1], encoding="UTF-8", xml_declaration=True)
PY
  exit 0
fi

mkdir -p "$(dirname "$SCRIPT")"
cp "$HERE/nautilus-script.sh" "$SCRIPT"
chmod 755 "$SCRIPT"
if command -v thunar >/dev/null 2>&1 || [ -f "$UCA" ]; then
  mkdir -p "$(dirname "$UCA")"
  [ -f "$UCA" ] || printf '<?xml version="1.0" encoding="UTF-8"?>\n<actions>\n</actions>\n' > "$UCA"
  python3 - "$UCA" "$HERE/thunar-uca.xml" <<'PY'
import sys, xml.etree.ElementTree as ET
t = ET.parse(sys.argv[1]); root = t.getroot()
if not any(a.findtext("unique-id") == "satsuma-popup" for a in root.findall("action")):
    root.append(ET.parse(sys.argv[2]).getroot())
    t.write(sys.argv[1], encoding="UTF-8", xml_declaration=True)
PY
fi
echo "Satsuma file manager hooks installed for $USER"
