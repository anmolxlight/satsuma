#!/usr/bin/env bash
# Removes what install.sh put in ~/.local (tools installed with your package manager stay).
set -euo pipefail
ID=io.github.anmolxlight.Satsuma
L="$HOME/.local"
[ -x "$L/share/satsuma/integrate-user.sh" ] && sh "$L/share/satsuma/integrate-user.sh" --remove || true
rm -rf "$L/lib/satsuma" "$L/share/satsuma"
rm -f "$L/bin/satsuma" "$L/share/applications/$ID.desktop" "$L/share/icons/hicolor/scalable/apps/$ID.svg" \
  "$L/share/nautilus-python/extensions/satsuma.py" "$L/share/nemo/actions/satsuma.nemo_action" \
  "$L/share/kio/servicemenus/satsuma.desktop"
for s in 48 128 256 512; do rm -f "$L/share/icons/hicolor/${s}x${s}/apps/$ID.png"; done
command -v update-desktop-database >/dev/null && update-desktop-database -q "$L/share/applications" || true
echo "Satsuma removed. Settings remain in ~/.config/satsuma (delete it if you like)."
