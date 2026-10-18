# Satsuma: zero-click offline file converter for Linux

Clean-room Linux take on Tangerine for Mac (tangerineformac.com). Behavior is copied, branding is NOT:
name is **Satsuma**, original icon, original website copy. Never use the word "Tangerine" in the
product UI, the site, or the package name (README may say "inspired by Tangerine for Mac").

Starting point: `tangerine.py` (working GTK4 + cairo wheel, real converters) and `test_tangerine.py`.
Keep what works, restructure into a proper package. Target: Ubuntu 24.04+, Debian 12+, Fedora 40+,
X11 and Wayland, x86_64 and aarch64. Python 3.11+, system PyGObject (GTK 4.12+). Apt/dnf deps only,
no pip deps at runtime (so it ships as a plain .deb with Architecture: all).

## 1. Layout
```
satsuma/                 python package
  __main__.py            CLI + GUI entry
  formats.py             kind detection (by extension AND `file --mime-type` fallback), option tables
  convert.py             conversion engine, one function per family
  tools.py               file tools
  actions.py             file actions
  jobs.py                job runner: thread pool, progress, cancel (kill subprocess), batch
  config.py              ~/.config/satsuma/config.json, defaults, load/save
  ui/wheel.py            the radial wheel widget (cairo, the existing look, animated)
  ui/window.py           main window, popup-at-cursor mode, settings dialog, toasts
  ui/dialogs.py          trim / crop / resize / split / quality prompts
data/                    .desktop, icons (svg + 48/128/256/512 png), metainfo.xml, nautilus/nemo/dolphin/thunar integrations
packaging/               build-deb.sh, rpm spec, AppImage recipe optional
web/                     landing page (Next.js static export OR plain HTML+CSS, your call, plain is fine)
tests/test_satsuma.py    single test file, plain asserts, runs real conversions, no pytest needed
.github/workflows/ci.yml lint (ruff), tests (ubuntu-24.04 + ubuntu-24.04-arm), build .deb, attach to release on tag
install.sh, uninstall.sh, README.md, LICENSE (MIT)
```

## 2. Conversions (parity with Tangerine's 249 options, real tools only)
| Family | In | Out | Tool |
|---|---|---|---|
| Images | jpg png webp heic avif tiff gif bmp svg ico | jpg png webp heic avif tiff gif pdf ico | ImageMagick `convert` (heif-enc for HEIC out) |
| Audio | mp3 m4a wav flac ogg opus aiff wma aac | mp3 m4a wav flac ogg opus aiff | ffmpeg |
| Video | mp4 mov mkv webm gif avi wmv m4v | mp4 mov mkv webm gif, mp3/m4a (audio only) | ffmpeg |
| PDF | pdf | docx odt pptx xlsx jpg png (all pages 300dpi, folder) txt md html epub | pdftoppm/pdftotext, LibreOffice (`--infilter=writer_pdf_import` for docx/odt), pandoc |
| Docs | docx doc odt rtf md txt html epub pages(zip preview) | docx odt pdf md txt html epub rtf | pandoc, LibreOffice for pdf/doc/rtf |
| Slides | ppt pptx odp key? | pdf pptx odp jpg png (per slide) | LibreOffice headless (then pdftoppm for images) |
| Sheets | xls xlsx ods csv tsv | xlsx ods csv tsv pdf html | LibreOffice headless, stdlib csv for csv<->tsv |
| Subtitles | srt vtt ass | srt vtt txt | ffmpeg + stdlib |
| Archives | zip tar tgz gz bz2 xz 7z rar | extract to folder | stdlib shutil, `unar` for rar/7z |

LibreOffice rule: always run headless with a private profile
(`-env:UserInstallation=file:///tmp/satsuma-lo-<uid>`) so it works while the user has LO open,
and with a timeout. Every converter: output next to source, never overwrite (`name 2.ext`),
write to a temp file in the same dir then atomic rename (no half files on cancel/crash).
Missing tool -> option hidden, Settings shows "install libreoffice-nogui to unlock N options".

## 3. File tools (26ish, same set as Tangerine)
Compress (image/video/audio/pdf, quality preset from settings), Resize (%, or max side), Crop (image/video/pdf, aspect presets + custom), Trim (audio/video: start/end), Split (pdf pages, pdf every N pages, video/audio into N parts or at timestamps), Merge (multi-select: pdfs, images->pdf, videos (concat), audio (concat)), Rotate 90/180/270, Flip, Grayscale, Strip metadata, Extract audio, Mute video, Change speed (0.5x/1.5x/2x), Video to GIF with trim, Image to PDF, PDF to images, Reduce frame rate, Normalize audio loudness (ffmpeg loudnorm), Fade in/out, Extract frames, Zip, Tar.gz, Encrypt PDF (qpdf, password prompt), Decrypt PDF.
Prompts (ui/dialogs.py) are small, keyboard-first, prefilled with sensible defaults, Enter confirms.

## 4. Actions
Copy (to clipboard as file uri list so pasting in a file manager works), Copy path, Move to... (folder chooser, remembers last), Open containing folder (select file via org.freedesktop.FileManager1 DBus ShowItems, fall back to xdg-open), Open in terminal, Trash (Gio), Float (small always-visible preview window of the file, image/video/pdf first page), Send (LocalSend or KDE Connect if installed, else hidden). Actions work on folders and mixed selections and never count toward anything.

## 5. Interaction (the point of the product)
- **Wheels**: Convert (Shift), Tools (Ctrl), Actions (Alt). Keys configurable in Settings. Tab / Shift+Tab cycles. Arrow keys move, Enter applies, Esc cancels. Mouse hover highlights, click applies. Slices animate (hover color ease 120ms, wheel scale-in 160ms on open, ease-out). Too many options (>10) -> two rings or paging with a "More" slice, never tiny unreadable text.
- **Popup mode** `satsuma --popup FILE...`: borderless wheel window that opens centered on the mouse pointer (X11: query pointer; Wayland: center of screen is acceptable), closes after the action or on focus loss / Esc. This is what file manager integrations call.
- **File manager integration** (installed by the .deb/install.sh): Nautilus script + nautilus-python extension menu item "Satsuma…" if python3-nautilus present, Nemo action, Dolphin service menu, Thunar custom action. Multi-select passes all files.
- **Drop window** (default launch): the existing window, drop one or many files, then pick. Also accepts paste (Ctrl+V of files) and a "Choose files" button for accessibility.
- Keyboard shortcut: README documents binding `satsuma --popup` to a global key; optional `--selection` reads the current Nautilus selection via the clipboard if feasible, else skip.
- **Batch**: multiple files of the same kind -> one wheel showing options common to all, runs as a batch with a combined progress ring drawn around the wheel. Mixed kinds -> Actions + Zip only.
- **Progress & results**: progress ring on the wheel (ffmpeg `-progress pipe:1` parsed against duration from ffprobe; others indeterminate spinner). Cancel with Esc while running kills the subprocess and removes the temp file. On finish: desktop notification (Gio.Notification) with "Show in folder" action, and a toast in the window. Errors show plain-language messages (e.g. "This video has no audio track"), full stderr in ~/.cache/satsuma/satsuma.log.

## 6. Settings (gear button, Gtk dialog, same visual language)
Wheel key per wheel, output location (next to source | fixed folder), image quality, video quality (crf preset: smaller/balanced/better), keep metadata toggle, open folder after convert toggle, notifications toggle, theme (light default, dark), "missing tools" panel with exact install commands per distro.

## 7. Visual design (must stay classy)
Keep the current look: warm light-grey card, 3D keycap row at top, rounded donut segments with gaps, orange #FD5400 active slice with white bold label, white pill in the center with the file type, caption below ("Convert to JPG"). Add a matching dark theme. Typography: Inter if installed else Noto Sans; DejaVu Sans Mono only for the ⇧⌃⌥ glyphs. No glassmorphism, no gradients beyond the subtle segment shine. HiDPI correct (use widget scale factor). Icon: an original flat satsuma (orange segment wheel), SVG.

## 8. Packaging & distribution
- `packaging/build-deb.sh` -> `dist/satsuma_<ver>_all.deb`, installs to /usr/lib/satsuma, /usr/bin/satsuma, desktop file, icons, metainfo, FM integrations. Depends: python3 (>=3.11), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, ffmpeg, imagemagick, poppler-utils, pandoc. Recommends: libreoffice-nogui (or libreoffice-core), unar, libheif-examples, ghostscript, qpdf, python3-nautilus. Must pass `lintian` with no errors (warnings ok) and `desktop-file-validate`.
- `install.sh` for non-deb distros: installs deps via apt/dnf/pacman when run with sudo, copies files to ~/.local, registers desktop file. `uninstall.sh` reverses it.
- RPM spec in packaging/ (build tested only if rpmbuild exists, do not block on it).
- Version from `satsuma/__init__.py`.

## 9. Website (web/)
Static landing page, deployable to Vercel as plain static files. Dark Stripe/Linear quality, original copy, not a clone of tangerineformac.com text. Sections: hero with an interactive wheel demo (drag the sample file, tap Shift/Ctrl/Alt, simulated), format grid, tools grid, privacy (everything local), install (one-liner `curl -fsSL .../install.sh | bash`, .deb download from GitHub Releases latest, link to repo), footer. Lighthouse-friendly, no frameworks required, responsive, accessible (keyboard works for the demo). OG image + favicon from the icon.

## 10. Tests (tests/test_satsuma.py, plain asserts, `python3 tests/test_satsuma.py`)
Generate fixtures with ffmpeg/convert/pandoc/soffice in a temp dir. Cover: every family at least one real conversion and output validated (ffprobe stream exists / identify works / file is non-empty and has right magic bytes), office via LibreOffice (docx->pdf, xlsx->csv, pptx->pdf), pdf->docx, rar/7z extract if tools present, every tool on a matching fixture, merge of 2 pdfs page count == sum (qpdf --show-npages), trim duration within 0.2s, no-overwrite naming, atomic write (cancel mid-job leaves no output), config load/save roundtrip, option tables never offer same-format conversion, GUI smoke test under GDK_BACKEND=broadway (start gtk4-broadwayd on a free display, launch window, exit 0 within 5s). Skips clearly print SKIP with reason when an optional tool is missing.

## Done means
- `python3 tests/test_satsuma.py` passes locally with every optional tool present (they are installed on this box).
- `ruff check .` clean (install ruff via `uv tool install ruff` if missing).
- `bash packaging/build-deb.sh` produces the .deb; `sudo apt install ./dist/satsuma_*_all.deb` works on this box; `satsuma --version` and `satsuma --convert x.png webp` work from the installed package; `lintian` no errors.
- Screenshots of: drop window, convert wheel on PNG, tools wheel on MP4 with a slice hovered, actions wheel, settings dialog, dark theme, progress ring mid-job. Capture via the broadway + headless chromium method (chromium at ~/.cache/ms-playwright/chromium-1234/chrome-linux*/chrome, `gtk4-broadwayd :N`, port 8080+N, `--screenshot`). Save to docs/screenshots/*.png and reference in README.
- web/ builds as static files (index.html at web root or web/out).
- Git commits along the way, author email anmolxlight@gmail.com. Do not push, do not create remotes, do not deploy.
- Final message: what works, what was skipped and why, exact test output tail.

Do NOT ask questions. Make reasonable defaults and note them in README "Decisions".
