#!/usr/bin/env bash
# Satsuma installer for any distro: files go to ~/.local, nothing system-wide except packages.
#   curl -fsSL https://raw.githubusercontent.com/anmolxlight/satsuma/main/install.sh | bash
#   sudo ./install.sh      also installs the tools with apt / dnf / pacman
set -euo pipefail
ID=io.github.anmolxlight.Satsuma
TARBALL=https://github.com/anmolxlight/satsuma/archive/refs/heads/main.tar.gz

SRC=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)
if [ ! -f "$SRC/satsuma/__init__.py" ]; then  # piped from curl: fetch the source
  SRC=$(mktemp -d)
  trap 'rm -rf "$SRC"' EXIT
  curl -fsSL "$TARBALL" | tar xz -C "$SRC" --strip-components=1
fi

# when run with sudo: install tools as root, files for the user who called sudo
if [ "$(id -u)" -eq 0 ]; then USER_NAME=${SUDO_USER:-root}; else USER_NAME=$(id -un); fi
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
if [ "$(id -u)" -eq 0 ]; then
  if command -v apt-get >/dev/null; then
    apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 ffmpeg imagemagick poppler-utils pandoc \
      libreoffice-nogui unar libheif-examples ghostscript qpdf file || true
  elif command -v dnf >/dev/null; then
    dnf install -y python3 python3-gobject gtk4 ffmpeg-free ImageMagick poppler-utils pandoc libreoffice-core \
      libreoffice-writer libreoffice-calc libreoffice-impress unar libheif-tools ghostscript qpdf file || true
  elif command -v pacman >/dev/null; then
    pacman -S --needed --noconfirm python python-gobject gtk4 ffmpeg imagemagick poppler pandoc libreoffice-fresh \
      unarchiver libheif ghostscript qpdf file || true
  fi
else
  echo "Tip: run with sudo to install ffmpeg, ImageMagick, pandoc, LibreOffice and friends too."
fi

as_user() { if [ "$(id -u)" -eq 0 ] && [ "$USER_NAME" != root ]; then sudo -u "$USER_NAME" "$@"; else "$@"; fi; }
L="$USER_HOME/.local"
PY=/usr/bin/python3; [ -x "$PY" ] || PY=$(command -v python3)

as_user mkdir -p "$L/lib/satsuma" "$L/bin" "$L/share/applications" "$L/share/icons/hicolor/scalable/apps" \
  "$L/share/nautilus-python/extensions" "$L/share/nemo/actions" "$L/share/kio/servicemenus" "$L/share/satsuma"
as_user rm -rf "$L/lib/satsuma/satsuma"
as_user cp -r "$SRC/satsuma" "$L/lib/satsuma/"
as_user find "$L/lib/satsuma" -name __pycache__ -prune -exec rm -rf {} +
as_user sh -c "printf '#!%s\nimport sys\n\nsys.path.insert(0, \"%s\")\nfrom satsuma.__main__ import main  # noqa: E402\n\nmain()\n' '$PY' '$L/lib/satsuma' > '$L/bin/satsuma' && chmod 755 '$L/bin/satsuma'"
as_user sh -c "sed 's|^Exec=satsuma|Exec=$L/bin/satsuma|' '$SRC/data/$ID.desktop' > '$L/share/applications/$ID.desktop'"
as_user cp "$SRC/data/icons/$ID.svg" "$L/share/icons/hicolor/scalable/apps/"
for s in 48 128 256 512; do
  as_user mkdir -p "$L/share/icons/hicolor/${s}x${s}/apps"
  as_user cp "$SRC/data/icons/$ID-$s.png" "$L/share/icons/hicolor/${s}x${s}/apps/$ID.png"
done
I="$SRC/data/integrations"
as_user cp "$I/satsuma-nautilus.py" "$L/share/nautilus-python/extensions/satsuma.py"
as_user cp "$I/satsuma.nemo_action" "$L/share/nemo/actions/"
as_user cp "$I/satsuma-dolphin.desktop" "$L/share/kio/servicemenus/satsuma.desktop"
as_user chmod 755 "$L/share/kio/servicemenus/satsuma.desktop"  # Dolphin only runs executable local menus
as_user cp "$I/integrate-user.sh" "$I/nautilus-script.sh" "$I/thunar-uca.xml" "$L/share/satsuma/"
as_user env HOME="$USER_HOME" sh "$L/share/satsuma/integrate-user.sh"
command -v update-desktop-database >/dev/null && as_user update-desktop-database -q "$L/share/applications" || true
command -v gtk-update-icon-cache >/dev/null && as_user gtk-update-icon-cache -qtf "$L/share/icons/hicolor" || true

echo "Satsuma installed: $L/bin/satsuma"
case ":$PATH:" in *":$L/bin:"*) ;; *) echo "Add $L/bin to your PATH to use 'satsuma' from a terminal." ;; esac
