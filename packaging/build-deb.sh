#!/usr/bin/env bash
# Build dist/satsuma_<version>_all.deb from the source tree. Needs dpkg-deb (and gzip).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/satsuma/__init__.py")
ID=io.github.anmolxlight.Satsuma
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
P="$STAGE/satsuma"

install -d "$P/DEBIAN" "$P/usr/bin" "$P/usr/lib/satsuma" "$P/usr/share/applications" "$P/usr/share/metainfo" \
  "$P/usr/share/icons/hicolor/scalable/apps" "$P/usr/share/doc/satsuma" "$P/usr/share/man/man1" \
  "$P/usr/share/nautilus-python/extensions" "$P/usr/share/nemo/actions" "$P/usr/share/kio/servicemenus" \
  "$P/usr/share/satsuma"

# app: the package (no bytecode) + launcher pinned to the system python (has python3-gi)
(cd "$ROOT" && find satsuma -name '*.py' -print0 | xargs -0 -I{} install -D -m 644 {} "$P/usr/lib/satsuma/{}")
cat > "$P/usr/bin/satsuma" <<'PY'
#!/usr/bin/python3
import sys

sys.path.insert(0, "/usr/lib/satsuma")
from satsuma.__main__ import main  # noqa: E402

main()
PY
chmod 755 "$P/usr/bin/satsuma"

# desktop integration
install -m 644 "$ROOT/data/$ID.desktop" "$P/usr/share/applications/"
install -m 644 "$ROOT/data/$ID.metainfo.xml" "$P/usr/share/metainfo/"
install -m 644 "$ROOT/data/icons/$ID.svg" "$P/usr/share/icons/hicolor/scalable/apps/"
for s in 48 128 256 512; do
  install -D -m 644 "$ROOT/data/icons/$ID-$s.png" "$P/usr/share/icons/hicolor/${s}x${s}/apps/$ID.png"
done
gzip -9n -c "$ROOT/data/satsuma.1" > "$P/usr/share/man/man1/satsuma.1.gz"
chmod 644 "$P/usr/share/man/man1/satsuma.1.gz"

# file managers: Nautilus (python3-nautilus), Nemo, Dolphin system-wide; Nautilus script + Thunar per user
I="$ROOT/data/integrations"
install -m 644 "$I/satsuma-nautilus.py" "$P/usr/share/nautilus-python/extensions/satsuma.py"
install -m 644 "$I/satsuma.nemo_action" "$P/usr/share/nemo/actions/"
install -m 644 "$I/satsuma-dolphin.desktop" "$P/usr/share/kio/servicemenus/satsuma.desktop"
install -m 755 "$I/integrate-user.sh" "$I/nautilus-script.sh" "$P/usr/share/satsuma/"
install -m 644 "$I/thunar-uca.xml" "$P/usr/share/satsuma/"

# docs
cat > "$P/usr/share/doc/satsuma/copyright" <<COPY
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: satsuma
Source: https://github.com/anmolxlight/satsuma

Files: *
Copyright: 2026 anmolxlight <anmolxlight@gmail.com>
License: Expat
$(sed -n '3,$p' "$ROOT/LICENSE" | sed 's/^$/./; s/^/ /')
COPY
printf 'satsuma (%s) unstable; urgency=medium\n\n  * Release %s.\n\n -- anmolxlight <anmolxlight@gmail.com>  %s\n' \
  "$VER" "$VER" "$(date -R -d @"${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}")" \
  | gzip -9n > "$P/usr/share/doc/satsuma/changelog.gz"
chmod 644 "$P/usr/share/doc/satsuma/"*

SIZE=$(du -sk --exclude=DEBIAN "$P" | cut -f1)
cat > "$P/DEBIAN/control" <<CTL
Package: satsuma
Version: $VER
Section: utils
Priority: optional
Architecture: all
Maintainer: anmolxlight <anmolxlight@gmail.com>
Installed-Size: $SIZE
Depends: python3 (>= 3.11), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, ffmpeg, imagemagick, poppler-utils, pandoc
Recommends: libreoffice-nogui | libreoffice-core, unar, libheif-examples, libheif-plugin-x265, libheif-plugin-aomenc, libheif-plugin-libde265, ghostscript, qpdf, file, fonts-inter, python3-nautilus
Homepage: https://github.com/anmolxlight/satsuma
Description: zero-click offline file converter
 Drop a file on a radial wheel and pick a slice: Satsuma converts images,
 audio, video, PDFs, documents, slides, spreadsheets, subtitles and archives
 with the tools already installed (ffmpeg, ImageMagick, poppler, pandoc,
 LibreOffice). Hold Shift for formats, Ctrl for file tools (compress, trim,
 crop, merge, split, ...) and Alt for actions. Nothing leaves the computer.
 .
 Includes Nautilus, Nemo, Dolphin and Thunar integration.
CTL
(cd "$P" && find usr -type f -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)
chmod 644 "$P/DEBIAN/control" "$P/DEBIAN/md5sums"
find "$P" -type d -exec chmod 755 {} +

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/satsuma_${VER}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$P" "$OUT" >/dev/null
echo "$OUT"
