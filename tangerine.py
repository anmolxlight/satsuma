#!/usr/bin/python3
"""Tangerine for Linux: drag a file onto the window, pick a slice of the wheel, drop.
Wheels: default = Convert, hold Ctrl = Tools, hold Alt = Actions (Tab cycles too).
Drop in the middle to pin the file, then click a slice. Esc cancels.
All work runs locally via ffmpeg / ImageMagick / pandoc / poppler."""
import csv, math, os, re, shutil, subprocess, sys, tempfile, threading
from pathlib import Path

IMG_IN = {"jpg", "jpeg", "png", "webp", "heic", "heif", "tiff", "tif", "avif", "svg", "bmp"}
IMG_OUT = ["png", "jpg", "webp", "tiff", "avif", "pdf"]  # ponytail: no HEIC out, IM6 here reads it only
AUD_IN = {"mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff", "aif", "wma"}
AUD_OUT = ["mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff"]
VID_IN = {"mp4", "mov", "mkv", "webm", "gif", "avi", "wmv"}
VID_OUT = ["mp4", "mov", "mkv", "webm", "gif", "mp3"]
DOC_IN = {"docx", "md", "markdown", "txt", "epub", "rtf", "html", "htm", "odt"}
DOC_OUT = ["docx", "md", "txt", "epub", "html", "odt"]
SHEET_IN = {"csv", "tsv"}  # ponytail: xlsx/ods need LibreOffice, add when installed
SUB_IN = {"srt", "vtt"}
ARC_IN = {"zip", "tar", "gz", "tgz", "bz2", "xz"}


def ext(p):
    return Path(p).suffix.lower().lstrip(".")


def kind(p):
    if os.path.isdir(p):
        return "folder"
    e = ext(p)
    for k, s in (("image", IMG_IN), ("audio", AUD_IN), ("video", VID_IN), ("doc", DOC_IN),
                 ("sheet", SHEET_IN), ("sub", SUB_IN), ("archive", ARC_IN)):
        if e in s:
            return k
    return "pdf" if e == "pdf" else "other"


def out_path(src, new_ext, tag=""):
    """Next to the source, never overwrite: 'a.png' -> 'a.jpg', 'a 2.jpg', ..."""
    p = Path(src)
    base = p.parent / f"{p.stem}{tag}"
    cand, n = Path(f"{base}.{new_ext}") if new_ext else base, 2
    while cand.exists():
        cand = Path(f"{base} {n}.{new_ext}") if new_ext else Path(f"{base} {n}")
        n += 1
    return str(cand)


def run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        if "does not contain any stream" in r.stderr:
            raise RuntimeError("file has no audio track")
        raise RuntimeError(f"{cmd[0]} failed: {(r.stderr or r.stdout).strip()[-300:]}")


def ff(src, dst, *args):
    run("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, *args, dst)


def convert(src, to):
    k, e, dst = kind(src), ext(src), out_path(src, to)
    if k == "image":
        run("convert", src + ("[0]" if e in {"gif", "tiff", "tif"} else ""), "-auto-orient", dst)
    elif k == "audio":
        ff(src, dst, "-vn", *(["-c:a", "aac"] if to == "m4a" else []))
    elif k == "video":
        if to == "gif":
            ff(src, dst, "-vf", "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse")
        elif to == "mp3":
            ff(src, dst, "-vn")
        elif to == "webm":
            ff(src, dst, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-c:a", "libopus")
        else:
            ff(src, dst, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart")
    elif k == "pdf":
        if to in ("png", "jpg"):  # all pages at 300 DPI, like the original
            d = out_path(src, "", " pages")
            os.makedirs(d)
            run("pdftoppm", "-r", "300", "-png" if to == "png" else "-jpeg", src, os.path.join(d, Path(src).stem))
            return d
        if to == "txt":
            run("pdftotext", "-layout", src, dst)
        else:  # md / docx / epub / html: text layer through pandoc
            with tempfile.NamedTemporaryFile(suffix=".txt") as t:
                run("pdftotext", src, t.name)
                run("pandoc", "-f", "markdown", t.name, "-o", dst)
    elif k == "doc":
        fmt = {"txt": "markdown", "md": "markdown", "markdown": "markdown", "htm": "html"}.get(e, e)
        run("pandoc", "-f", fmt, src, "-t", {"txt": "plain", "md": "gfm"}.get(to, to), "-s", "-o", dst)
    elif k == "sheet":
        with open(src, newline="", encoding="utf-8-sig") as f, open(dst, "w", newline="") as o:
            csv.writer(o, delimiter="\t" if to == "tsv" else ",").writerows(
                csv.reader(f, delimiter="\t" if e == "tsv" else ","))
    elif k == "sub":
        if to == "txt":
            lines = Path(src).read_text(encoding="utf-8-sig").splitlines()
            keep = [l for l in lines if l.strip() and "-->" not in l and not l.strip().isdigit() and l.strip() != "WEBVTT"]
            Path(dst).write_text("\n".join(re.sub(r"<[^>]+>", "", l) for l in keep) + "\n")
        else:
            ff(src, dst)
    elif k == "archive":
        d = out_path(src, "", "")
        if d.endswith(".tar"):
            d = out_path(d, "")
        shutil.unpack_archive(src, d)
        return d
    else:
        raise RuntimeError("no conversions for this file")
    return dst


def options(p):
    k, e = kind(p), ext(p)
    same = lambda xs: [x for x in xs if x != {"jpeg": "jpg", "tif": "tiff", "aif": "aiff"}.get(e, e)]
    return {"image": same(IMG_OUT), "audio": same(AUD_OUT), "video": same(VID_OUT),
            "pdf": ["png", "jpg", "txt", "md", "docx", "epub"], "doc": same(DOC_OUT),
            "sheet": same(["csv", "tsv"]), "sub": same(["srt", "vtt", "txt"]),
            "archive": ["extract"]}.get(k, [])


# ---- tools (Ctrl wheel) ----
def compress(src):
    k, dst = kind(src), out_path(src, ext(src), " compressed")
    if k == "image":
        run("convert", src, "-strip", "-quality", "70", dst)
    elif k == "video":
        ff(src, dst, "-c:v", "libx264", "-crf", "28", "-preset", "slow", "-c:a", "aac", "-b:a", "96k")
    elif k == "audio":
        ff(src, dst, "-b:a", "96k")
    elif k == "pdf":
        run("gs", "-q", "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/ebook", "-o", dst, src)
    return dst


def half(src):
    dst = out_path(src, ext(src), " half")
    if kind(src) == "image":
        run("convert", src, "-resize", "50%", dst)
    else:
        ff(src, dst, "-vf", "scale=trunc(iw/4)*2:trunc(ih/4)*2")
    return dst


def strip_meta(src):
    dst = out_path(src, ext(src), " clean")
    if kind(src) == "image":
        run("convert", src, "-strip", dst)
    else:
        ff(src, dst, "-map_metadata", "-1", "-c", "copy")
    return dst


def rotate(src):
    dst = out_path(src, ext(src), " rotated")
    if kind(src) == "image":
        run("convert", src, "-rotate", "90", dst)
    else:
        ff(src, dst, "-vf", "transpose=1", "-c:a", "copy")
    return dst


def split_pdf(src):
    d = out_path(src, "", " split")
    os.makedirs(d)
    run("pdfseparate", src, os.path.join(d, Path(src).stem + "-%d.pdf"))
    return d


def zip_it(src):
    base = out_path(src, "zip")[:-4]
    return shutil.make_archive(base, "zip", Path(src).parent, Path(src).name)


def tar_gz(src):
    base = out_path(src, "tar.gz")[:-7]
    return shutil.make_archive(base, "gztar", Path(src).parent, Path(src).name)


def tools(p):
    k = kind(p)
    t = {"image": [("compress", compress), ("half size", half), ("rotate", rotate), ("strip meta", strip_meta)],
         "video": [("compress", compress), ("half size", half), ("rotate", rotate), ("strip meta", strip_meta)],
         "audio": [("compress", compress), ("strip meta", strip_meta)],
         "pdf": [("compress", compress), ("split pages", split_pdf)]}.get(k, [])
    if k == "pdf" and not shutil.which("gs"):
        t = t[1:]
    return t + [("zip", zip_it), ("tar.gz", tar_gz)]


# ---- actions (Alt wheel) ----
def actions():
    def opener(p): subprocess.Popen(["xdg-open", str(Path(p).parent)]); return None
    def term(p):
        d = p if os.path.isdir(p) else str(Path(p).parent)
        for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "alacritty", "kitty", "xterm"):
            if shutil.which(t):
                subprocess.Popen([t], cwd=d); return None
        raise RuntimeError("no terminal found")
    return [("copy path", "copy_path"), ("open folder", opener), ("terminal", term), ("trash", lambda p: run("gio", "trash", p))]


# ---------------------------------------------------------------- GUI
def gui(pinned=None):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk, Gdk, GLib, Gio

    MODES = ["Convert", "Tools", "Actions"]
    S = {"file": pinned, "mode": 0, "hover": -1, "status": "", "busy": False}

    def slices():
        f = S["file"]
        if not f:
            return []
        if S["mode"] == 0:
            return [(o.upper(), lambda p, o=o: convert(p, o)) for o in options(f)]
        if S["mode"] == 1:
            return tools(f)
        return actions()

    ORANGE = (0.99, 0.33, 0.0)
    KEYS = [("⇧", "shift", "Convert formats"), ("⌃", "ctrl", "File tools"), ("⌥", "alt", "File actions")]

    def geom(w, h):
        R = min(w - 40, h - 230) / 2
        return w / 2, 150 + R, R, R * 0.40

    def hit(x, y, w, h):
        n = len(slices())
        cx, cy, R, r = geom(w, h)
        d = math.hypot(x - cx, y - cy)
        if not n or d < r or d > R:
            return -1
        a = (math.atan2(y - cy, x - cx) + math.pi / 2 + math.pi / n) % (2 * math.pi)  # slice 0 centered on top
        return int(a / (2 * math.pi / n))

    def rrect(c, x, y, w, h, rad):
        c.new_sub_path()
        for ax, ay, a in ((x + w - rad, y + rad, -math.pi / 2), (x + w - rad, y + h - rad, 0),
                          (x + rad, y + h - rad, math.pi / 2), (x + rad, y + rad, math.pi)):
            c.arc(ax, ay, rad, a, a + math.pi / 2)
        c.close_path()

    def segment(c, cx, cy, R, r, a0, a1, gap=5, rad=14):
        """Donut slice with rounded corners: a gap-inset ring sector, corners filleted by arcs."""
        # ponytail: fillet = small arcs at the four corners, good enough at these sizes
        go, gi = gap / R, gap / r  # angular half-gap at outer / inner radius
        ro, ri = rad / R, rad / (r + rad)
        c.new_path()
        c.arc(cx, cy, R, a0 + go + ro, a1 - go - ro)
        p = lambda rr, a: (cx + rr * math.cos(a), cy + rr * math.sin(a))
        c.curve_to(*p(R, a1 - go), *p(R, a1 - go), *p(R - rad, a1 - go * R / (R - rad)))
        c.line_to(*p(r + rad, a1 - gap / (r + rad)))
        c.curve_to(*p(r, a1 - gi), *p(r, a1 - gi), *p(r, a1 - gi - ri))
        c.arc_negative(cx, cy, r, a1 - gi - ri, a0 + gi + ri)
        c.curve_to(*p(r, a0 + gi), *p(r, a0 + gi), *p(r + rad, a0 + gap / (r + rad)))
        c.line_to(*p(R - rad, a0 + go * R / (R - rad)))
        c.curve_to(*p(R, a0 + go), *p(R, a0 + go), *p(R, a0 + go + ro))
        c.close_path()

    def draw(_a, c, w, h):
        import cairo
        c.set_source_rgb(0.965, 0.965, 0.96); c.paint()
        cx, cy, R, r = geom(w, h)
        c.select_font_face("Noto Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        def text(s, x, y, rgb=(0.13, 0.13, 0.13), size=12, bold=False, left=False, font="Noto Sans"):
            c.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
            c.set_font_size(size); e = c.text_extents(s)
            c.set_source_rgb(*rgb)
            c.move_to(x if left else x - e.width / 2 - e.x_bearing, y - e.height / 2 - e.y_bearing); c.show_text(s)

        # keycaps
        kw, kh, gapk = 76, 66, 22
        x0 = w / 2 - (3 * kw + 2 * gapk) / 2
        for i, (sym, name, cap) in enumerate(KEYS):
            x, y, on = x0 + i * (kw + gapk), 22, i == S["mode"]
            c.push_group()
            rrect(c, x, y + 5, kw, kh, 11); c.set_source_rgb(0.86, 0.87, 0.83); c.fill()      # bottom lip
            rrect(c, x, y + (3 if on else 0), kw, kh, 11)
            g = cairo.LinearGradient(0, y, 0, y + kh); g.add_color_stop_rgb(0, 1, 1, 1); g.add_color_stop_rgb(1, 0.95, 0.95, 0.93)
            c.set_source(g); c.fill_preserve(); c.set_source_rgb(0.85, 0.85, 0.83); c.set_line_width(1); c.stroke()
            dy = 3 if on else 0
            text(sym, x + 14, y + 20 + dy, (0.45, 0.45, 0.45), 18, left=True, font="DejaVu Sans Mono")  # Noto lacks ⇧⌃⌥
            text(name, x + 14, y + 47 + dy, (0.4, 0.4, 0.4), 11, left=True)
            c.pop_group_to_source(); c.paint_with_alpha(1 if on else 0.45)
            if on:
                text(cap, x + kw / 2, y + kh + 22, (0.4, 0.4, 0.4), 12)

        # ring base
        c.arc(cx, cy, R + 10, 0, 2 * math.pi); c.set_source_rgb(0.925, 0.93, 0.925); c.fill()
        c.arc(cx, cy, R + 10, 0, 2 * math.pi); c.set_source_rgb(0.88, 0.885, 0.88); c.set_line_width(1); c.stroke()
        sl = slices()
        if not S["file"]:
            c.arc(cx, cy, R - 4, 0, 2 * math.pi); c.set_source_rgb(0.985, 0.985, 0.98); c.fill()
            c.set_dash([5, 6]); c.arc(cx, cy, R - 18, 0, 2 * math.pi); c.set_source_rgb(0.8, 0.8, 0.78); c.stroke(); c.set_dash([])
            text("Drop a file", cx, cy - 10, size=18, bold=True)
            text("Ctrl for tools  ·  Alt for actions", cx, cy + 16, (0.5, 0.5, 0.5), 11)
        else:
            n = max(len(sl), 1); step = 2 * math.pi / n
            size = 15 if n <= 8 else 12
            for i, (label, _) in enumerate(sl):
                a0 = -math.pi / 2 - step / 2 + i * step
                on = i == S["hover"]
                segment(c, cx, cy, R, r + 8, a0, a0 + step)
                if on:
                    c.set_source_rgb(*ORANGE)
                else:
                    g = cairo.RadialGradient(cx, cy, r, cx, cy, R)
                    g.add_color_stop_rgb(0, 0.92, 0.925, 0.925); g.add_color_stop_rgb(1, 0.985, 0.985, 0.985)
                    c.set_source(g)
                c.fill_preserve(); c.set_source_rgba(1, 1, 1, 0.9 if not on else 0); c.set_line_width(1.2); c.stroke()
                am = a0 + step / 2; rm = (R + r + 8) / 2
                text(label.upper() if S["mode"] == 0 else label.capitalize(), cx + rm * math.cos(am), cy + rm * math.sin(am),
                     (1, 1, 1) if on else (0.08, 0.08, 0.08), size if S["mode"] == 0 else 13, bold=True)
            # center hole + chip
            c.arc(cx, cy, r, 0, 2 * math.pi); c.set_source_rgb(0.965, 0.965, 0.96); c.fill()
            e = ext(S["file"]).upper() or ("FOLDER" if kind(S["file"]) == "folder" else "FILE")
            cw = max(80, len(e) * 10 + 40)
            rrect(c, cx - cw / 2, cy - 18, cw, 36, 18); c.set_source_rgb(1, 1, 1); c.fill()
            text(e, cx, cy, (0.1, 0.1, 0.1), 13)
            if not sl:
                text("Nothing here for this file", cx, cy + R + 30, (0.45, 0.45, 0.45), 12)

        # caption + status
        cap = ""
        if S["file"] and 0 <= S["hover"] < len(sl):
            lab = sl[S["hover"]][0]
            cap = f"Convert to {lab.upper()}" if S["mode"] == 0 else lab[:1].upper() + lab[1:]
        if S["status"]:
            cap = S["status"]
        bad = cap.startswith("✗")
        text(cap, w / 2, cy + R + 32, (0.8, 0.2, 0.15) if bad else (0.4, 0.4, 0.4), 12)

    def apply(i):
        sl = slices()
        if S["busy"] or not (0 <= i < len(sl)):
            return
        label, fn, f = *sl[i], S["file"]
        if fn == "copy_path":
            area.get_clipboard().set(f); done(f"copied {f}"); return
        S["busy"] = True; S["status"] = f"{label.lower()}…"; area.queue_draw()

        def work():
            try:
                out = fn(f)
                msg = f"✓ {Path(out).name}" if out else f"✓ {label}"
            except Exception as e:
                msg = f"✗ {e}"
            GLib.idle_add(done, msg)
        threading.Thread(target=work, daemon=True).start()

    def done(msg):
        S.update(busy=False, status=msg, hover=-1)
        if not pinned:
            S["file"] = None
        area.queue_draw()

    def set_mode_from(ctrl):
        st = ctrl.get_current_event_state()
        m = 1 if st & Gdk.ModifierType.CONTROL_MASK else 2 if st & Gdk.ModifierType.ALT_MASK else S["mode"] if S["sticky"] else 0
        if m != S["mode"]:
            S["mode"] = m

    S["sticky"] = False

    def first_path(val):
        try:
            files = val.get_files() if hasattr(val, "get_files") else [val]
            return files[0].get_path() if files else None
        except Exception:
            return None

    def on_enter(dt, x, y):
        S["sticky"] = False
        return Gdk.DragAction.COPY

    def on_motion(dt, x, y):
        v = dt.get_value()
        if v is not None:
            S["file"] = first_path(v) or S["file"]
        set_mode_from(dt)
        S["hover"] = hit(x, y, area.get_width(), area.get_height()); area.queue_draw()
        return Gdk.DragAction.COPY

    def on_leave(dt):
        S["hover"] = -1; area.queue_draw()

    def on_drop(dt, val, x, y):
        S["file"] = first_path(val)
        i = hit(x, y, area.get_width(), area.get_height())
        S["sticky"] = True
        if i >= 0:
            apply(i)
        else:
            S["status"] = "pinned: click a slice (Tab switches wheel)"; area.queue_draw()
        return True

    def on_click(g, n, x, y):
        if S["file"]:
            apply(hit(x, y, area.get_width(), area.get_height()))

    def on_move(c, x, y):
        h = hit(x, y, area.get_width(), area.get_height())
        if h != S["hover"]:
            S["hover"] = h; area.queue_draw()

    def on_key(c, kv, code, st):
        if kv == Gdk.KEY_Escape:
            S.update(file=pinned, status="", hover=-1)
        elif kv in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            S["mode"] = (S["mode"] + (-1 if st & Gdk.ModifierType.SHIFT_MASK else 1)) % 3; S["hover"] = -1
        elif kv in (Gdk.KEY_Right, Gdk.KEY_Down) and slices():
            S["hover"] = (S["hover"] + 1) % len(slices())
        elif kv in (Gdk.KEY_Left, Gdk.KEY_Up) and slices():
            S["hover"] = (S["hover"] - 1) % len(slices())
        elif kv == Gdk.KEY_Return:
            apply(S["hover"])
        else:
            return False
        area.queue_draw(); return True

    def activate(app):
        global area
        win = Gtk.ApplicationWindow(application=app, title="Tangerine", default_width=480, default_height=660)
        area = Gtk.DrawingArea(); area.set_draw_func(draw); win.set_child(area)
        dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY); dt.set_preload(True)
        dt.connect("enter", on_enter); dt.connect("motion", on_motion); dt.connect("leave", on_leave); dt.connect("drop", on_drop)
        area.add_controller(dt)
        g = Gtk.GestureClick(); g.connect("pressed", on_click); area.add_controller(g)
        m = Gtk.EventControllerMotion(); m.connect("motion", on_move); area.add_controller(m)
        k = Gtk.EventControllerKey(); k.connect("key-pressed", on_key); win.add_controller(k)
        win.present()
        if os.environ.get("TANGERINE_MODE"):  # testing hook: preselect wheel + hover
            S.update(mode=int(os.environ["TANGERINE_MODE"]), hover=0)

    app = Gtk.Application(application_id="dev.tangerine.linux", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate); app.run([])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--convert":  # CLI: tangerine.py --convert FILE FORMAT
        print(convert(a[1], a[2]))
    elif a and a[0] == "--list":
        print(kind(a[1]), options(a[1]), [t for t, _ in tools(a[1])])
    else:
        gui(os.path.abspath(a[0]) if a else None)
