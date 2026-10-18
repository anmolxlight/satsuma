"""Main drop window, popup-at-pointer mode, settings, toasts, float preview, notifications."""
import ctypes
import ctypes.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .. import APP_ID, actions, config, formats, jobs, tools  # noqa: E402
from ..convert import convert  # noqa: E402
from . import dialogs  # noqa: E402
from .wheel import MODES, Slice, Wheel  # noqa: E402

KEYVAL_MOD = {Gdk.KEY_Shift_L: "shift", Gdk.KEY_Shift_R: "shift", Gdk.KEY_Control_L: "ctrl",
              Gdk.KEY_Control_R: "ctrl", Gdk.KEY_Alt_L: "alt", Gdk.KEY_Alt_R: "alt", Gdk.KEY_Meta_L: "alt",
              Gdk.KEY_Super_L: "super", Gdk.KEY_Super_R: "super"}
MASK_MOD = ((Gdk.ModifierType.SHIFT_MASK, "shift"), (Gdk.ModifierType.CONTROL_MASK, "ctrl"),
            (Gdk.ModifierType.ALT_MASK, "alt"), (Gdk.ModifierType.SUPER_MASK, "super"))

CSS = """
* { font-family: Inter, "Noto Sans", sans-serif; }
window.satsuma, window.satsuma-prompt, window.satsuma-settings { background: #F6F6F5; color: #141414; }
window.dark.satsuma, window.dark.satsuma-prompt, window.dark.satsuma-settings { background: #1B1B1C; color: #EDEDED; }
window.satsuma-prompt { border: 1px solid #DCDCD8; border-radius: 14px; }
window.dark.satsuma-prompt { border-color: #333336; }
window.popup { border: 1px solid #DCDCD8; }
window.dark.popup { border-color: #333336; }
.prompt-title { font-weight: 700; font-size: 15px; }
.prompt-label, .dim { color: #6A6A6A; font-size: 12px; }
window.dark .prompt-label, window.dark .dim { color: #9A9AA0; }
.section { font-weight: 700; font-size: 13px; margin-top: 8px; }
button.accent { background: #FD5400; color: #FFFFFF; font-weight: 700; border-radius: 10px; border: none;
                box-shadow: none; padding: 6px 16px; }
button.accent:hover { background: #FF6A1F; }
button.chip { border-radius: 999px; padding: 2px 12px; min-height: 24px; font-size: 12px; }
button.pillbtn { border-radius: 999px; padding: 4px 16px; }
button.gear { border-radius: 999px; min-width: 34px; min-height: 34px; padding: 0; font-size: 17px; }
.toast { background: rgba(24, 24, 24, 0.94); color: #FFFFFF; border-radius: 999px; padding: 6px 8px 6px 18px; }
.toast button { color: #FD5400; font-weight: 700; background: none; border: none; box-shadow: none; }
.toast.bad { background: rgba(150, 30, 20, 0.95); }
switch:checked { background: #FD5400; }
spinbutton:focus-within, entry:focus-within { outline-color: rgba(253, 84, 0, 0.6); }
.cmd { font-family: "DejaVu Sans Mono", monospace; font-size: 11px; }
"""


# ---------------------------------------------------------------- X11 helpers (no-ops elsewhere)
def _xid(win):
    try:
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
    except (ValueError, ImportError):
        return None
    surf = win.get_surface()
    return surf.get_xid() if isinstance(surf, GdkX11.X11Surface) else None


def _xlib():
    x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    vp, ul, i, pi, pu = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.POINTER(ctypes.c_int), \
        ctypes.POINTER(ctypes.c_uint)
    x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = vp, [ctypes.c_char_p]
    x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = ul, [vp]
    x.XQueryPointer.argtypes = [vp, ul, ctypes.POINTER(ul), ctypes.POINTER(ul), pi, pi, pi, pi, pu]
    x.XMoveWindow.argtypes = [vp, ul, i, i]
    x.XInternAtom.restype, x.XInternAtom.argtypes = ul, [vp, ctypes.c_char_p, i]
    x.XSendEvent.argtypes = [vp, ul, i, ctypes.c_long, vp]
    x.XDisplayWidth.argtypes = x.XDisplayHeight.argtypes = [vp, i]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [vp]
    return x


class _XClient(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _XEvent(ctypes.Union):
    _fields_ = [("xclient", _XClient), ("pad", ctypes.c_long * 24)]


def x11_center_on_pointer(win):
    """X11: move the window so it's centered on the mouse. Wayland can't; the compositor centers it."""
    xid = _xid(win)
    if not xid:
        return
    try:
        x = _xlib()
        dpy = x.XOpenDisplay(None)
        root = x.XDefaultRootWindow(dpy)
        r, ch, m = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        px, py, wx, wy = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        x.XQueryPointer(dpy, root, ctypes.byref(r), ctypes.byref(ch), ctypes.byref(px), ctypes.byref(py),
                        ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
        w, h = win.get_width(), win.get_height()
        sw, sh = x.XDisplayWidth(dpy, 0), x.XDisplayHeight(dpy, 0)
        x.XMoveWindow(dpy, xid, max(0, min(px.value - w // 2, sw - w)), max(0, min(py.value - h // 2, sh - h)))
        x.XFlush(dpy)
        x.XCloseDisplay(dpy)
    except OSError:
        pass


def x11_keep_above(win):
    """X11: ask the window manager for _NET_WM_STATE_ABOVE. GTK 4 has no API for it; Wayland has no way."""
    xid = _xid(win)
    if not xid:
        return
    try:
        x = _xlib()
        dpy = x.XOpenDisplay(None)
        ev = _XEvent()
        ev.xclient.type, ev.xclient.window, ev.xclient.format = 33, xid, 32  # ClientMessage
        ev.xclient.message_type = x.XInternAtom(dpy, b"_NET_WM_STATE", 0)
        ev.xclient.data[0], ev.xclient.data[1] = 1, x.XInternAtom(dpy, b"_NET_WM_STATE_ABOVE", 0)
        ev.xclient.data[3] = 1
        x.XSendEvent(dpy, x.XDefaultRootWindow(dpy), 0, (1 << 19) | (1 << 20), ctypes.byref(ev))
        x.XFlush(dpy)
        x.XCloseDisplay(dpy)
    except OSError:
        pass


# ---------------------------------------------------------------- application
class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = config.load()
        self.demo = {}

    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_data(CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        show = Gio.SimpleAction.new("show", GLib.VariantType.new("s"))
        show.connect("activate", lambda _a, p: actions.show_in_folder([p.get_string()]))
        self.add_action(show)
        jobs.setup_logging()

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        popup = "--popup" in args
        wheel = None
        if "--wheel" in args:
            i = args.index("--wheel")
            wheel = args[i + 1] if i + 1 < len(args) else None
            del args[i:i + 2]
        files = [os.path.abspath(os.path.join(cl.get_cwd() or "", a)) for a in args if a != "--popup"]
        self.demo = json.loads(cl.getenv("SATSUMA_DEMO") or "{}")
        if self.demo.get("theme"):
            self.cfg["theme"] = self.demo["theme"]
        self.apply_theme()
        existing = [w for w in self.get_windows() if isinstance(w, WheelWindow) and not w.popup]
        if existing and not popup:
            win = existing[0]
            if files:
                win.set_files(files, pinned=True)
        else:
            win = WheelWindow(self, files, popup, wheel)
        win.present()
        if self.demo:
            GLib.timeout_add(250, win.run_demo, self.demo)
            if self.demo.get("quit_after"):
                GLib.timeout_add(int(self.demo["quit_after"] * 1000), lambda: (self.quit(), False)[1])
        return 0

    def apply_theme(self):
        dark = self.cfg["theme"] == "dark"
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", dark)
        for w in self.get_windows():
            (w.add_css_class if dark else w.remove_css_class)("dark")
            if isinstance(w, WheelWindow):
                w.wheel.set_theme(self.cfg["theme"])

    def save(self):
        config.save(self.cfg)
        self.apply_theme()
        for w in self.get_windows():
            if isinstance(w, WheelWindow):
                w.wheel.keys = self.cfg["keys"]
                w.wheel.refresh(animate=False)

    def notify(self, title, body, path=None):
        if not self.cfg["notifications"]:
            return
        n = Gio.Notification.new(title)
        n.set_body(body)
        if path:
            n.add_button_with_target("Show in folder", "app.show", GLib.Variant("s", path))
            n.set_default_action_and_target("app.show", GLib.Variant("s", path))
        self.send_notification("satsuma-done", n)


def styled(win, app, *classes):
    for c in classes:
        win.add_css_class(c)
    if app.cfg["theme"] == "dark":
        win.add_css_class("dark")


# ---------------------------------------------------------------- the wheel window
class WheelWindow(Gtk.ApplicationWindow):
    def __init__(self, app, files, popup=False, wheel=None):
        super().__init__(application=app, title="Satsuma", default_width=420 if popup else 480,
                         default_height=560 if popup else 660)
        self.app, self.popup, self.files, self.pinned = app, popup, [], bool(files)
        self.job, self.modal_open, self.was_active = None, False, False
        styled(self, app, "satsuma", *(["popup"] if popup else []))
        if popup:
            self.set_decorated(False)
            self.set_resizable(False)
        self.wheel = Wheel(self.slices_for, self.apply, app.cfg["keys"], app.cfg["theme"])
        overlay = Gtk.Overlay()
        overlay.set_child(self.wheel)
        self.set_child(overlay)

        gear = Gtk.Button(halign=Gtk.Align.END, valign=Gtk.Align.START, margin_top=10, margin_end=10,
                          tooltip_text="Settings")
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        if theme.has_icon("emblem-system-symbolic"):
            gear.set_icon_name("emblem-system-symbolic")
        else:
            gear.set_label("⚙")
        gear.add_css_class("gear")
        gear.add_css_class("flat")
        gear.update_property([Gtk.AccessibleProperty.LABEL], ["Settings"])
        gear.connect("clicked", lambda *_: self.open_settings())
        overlay.add_overlay(gear)

        self.choose = Gtk.Button(label="Choose files…", halign=Gtk.Align.CENTER, valign=Gtk.Align.END,
                                 margin_bottom=26)
        self.choose.add_css_class("pillbtn")
        self.choose.connect("clicked", lambda *_: self.choose_files())
        overlay.add_overlay(self.choose)

        self.toast = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, halign=Gtk.Align.CENTER,
                                  valign=Gtk.Align.END, margin_bottom=22, transition_duration=160)
        tbox = Gtk.Box(spacing=8)
        tbox.add_css_class("toast")
        self.toast_label = Gtk.Label(ellipsize=3, max_width_chars=40)
        self.toast_btn = Gtk.Button(label="Show")
        self.toast_btn.connect("clicked", lambda *_: self._toast_path and actions.show_in_folder([self._toast_path]))
        tbox.append(self.toast_label)
        tbox.append(self.toast_btn)
        self.toast.set_child(tbox)
        self._toast_path, self._toast_timer = None, 0
        overlay.add_overlay(self.toast)

        # input
        dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        dt.set_preload(True)
        dt.connect("enter", self.on_drag)
        dt.connect("motion", self.on_drag)
        dt.connect("leave", lambda *_: self.wheel.hover_at(-1, -1))
        dt.connect("drop", self.on_drop)
        self.wheel.add_controller(dt)
        click = Gtk.GestureClick()
        click.connect("released", self.on_click)
        self.wheel.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self.wheel.hover_at(x, y))
        self.wheel.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        if popup:
            self.connect("notify::is-active", self.on_active)
            self.connect("map", lambda *_: GLib.idle_add(lambda: x11_center_on_pointer(self) and False))
            if not files:  # global shortcut: files copied in the file manager are the selection
                GLib.idle_add(lambda: self.paste() and False)
        self.set_files(files, pinned=bool(files))
        if wheel in MODES:
            self.wheel.set_mode(MODES.index(wheel))

    # ------------------------------------------------------------ selection
    def set_files(self, files, pinned=False):
        self.files = [f for f in files if os.path.exists(f)]
        self.pinned = pinned and bool(self.files)
        self.wheel.files = self.files
        exts = {formats.ext(f) or ("folder" if os.path.isdir(f) else "file") for f in self.files}
        kinds = {formats.kind(f) for f in self.files}
        n = len(self.files)
        if n == 1:
            self.wheel.label = (formats.ext(self.files[0]) or ("FOLDER" if os.path.isdir(self.files[0]) else "FILE")).upper()
        elif len(exts) == 1:
            self.wheel.label = f"{n} × {exts.pop().upper()}"
        else:
            self.wheel.label = f"{n} FILES"
        if len(kinds) > 1 and self.wheel.mode == 0:
            self.wheel.mode = 2  # mixed selection: nothing to convert, actions first
        self.wheel.hover = -1
        self.choose.set_visible(not self.files)
        self.wheel.refresh()

    def slices_for(self, mode):
        fs = self.files
        if not fs:
            return []
        many = len(fs) > 1
        if mode == 0:
            out = []
            for o in formats.common_options(fs):
                if o == "extract":
                    out.append(Slice("Extract", "Extract here" if not many else f"Extract {len(fs)} archives", ("convert", o)))
                else:
                    what = f"{len(fs)} files" if many else ("pages" if formats.kind(fs[0]) == "pdf" and o in ("jpg", "png") else "")
                    out.append(Slice(o.upper(), f"Convert {what + ' ' if what else ''}to {o.upper()}", ("convert", o)))
            return out
        if mode == 1:
            return [Slice(t.label, (f"{t.label} {len(fs)} files" if many else t.label), ("tool", t.id))
                    for t in tools.tools_for(fs)]
        return [Slice(a.label, a.label, ("action", a.id)) for a in actions.actions_for(fs)]

    # ------------------------------------------------------------ applying
    def apply(self, payload):
        if self.job:
            return
        what, val = payload
        if what == "convert":
            self.run_job(lambda p: convert(p, val), list(self.files), f"Converting to {val.upper()}"
                         if val != "extract" else "Extracting")
        elif what == "tool":
            t = tools.BY_ID[val]
            if t.fields:
                self.modal_open = True
                dialogs.ask(self, t.label, t.fields, tools.defaults(t, self.files[0]),
                            lambda vals: self._run_tool(t, vals), self._modal_closed)
                return
            self._run_tool(t, {})
        else:
            self.do_action(val)

    def _modal_closed(self):
        self.modal_open = False
        self.present()

    def _run_tool(self, t, params):
        self.modal_open = False
        fs = list(self.files)
        if t.multi:
            self.run_job(lambda ps: t.fn(ps, **params), [fs], t.label)
        else:
            self.run_job(lambda p: t.fn(p, **params), fs, t.label)

    def run_job(self, fn, items, verb):
        self.job = jobs.submit(fn, items, on_done=lambda j: GLib.idle_add(self.finished, j))
        self.wheel.set_job(self.job)
        self.wheel.set_status(f"{verb}…   Esc cancels")

    def finished(self, job):
        self.job = None
        self.wheel.set_job(None)
        outs = [r[1] for r in job.results if r[1]]
        errs = [r[2] for r in job.results if r[2]]
        if errs and all(e == "Cancelled" for e in errs) and not outs:
            self.wheel.set_status("Cancelled")
            self.show_toast("Cancelled")
        elif errs:
            real = [e for e in errs if e != "Cancelled"]
            msg = real[0] if len(job.results) == 1 else f"{len(real)} of {len(job.results)} failed: {real[0]}"
            self.wheel.set_status(f"✗ {msg}", bad=True)
            self.show_toast(msg, bad=True)
            self.app.notify("Satsuma couldn't finish", msg)
        else:
            name = Path(outs[0]).name if len(outs) == 1 else f"{len(outs)} files"
            self.wheel.set_status(f"✓ {name}")
            self.show_toast(f"✓ {name}", outs[0])
            self.app.notify("Done", name if len(outs) == 1 else f"{name} in {Path(outs[0]).parent.name}", outs[0])
            if self.app.cfg["open_folder"]:
                actions.show_in_folder(outs)
            if not self.pinned:
                self.set_files([])
        if self.popup:
            self.close_soon(2500 if errs else 900)
        return False

    def close_soon(self, ms):
        self.app.hold()  # keep the process for the notification's "Show in folder" button
        GLib.timeout_add_seconds(60, lambda: (self.app.release(), False)[1])
        GLib.timeout_add(ms, lambda: (self.close(), False)[1])

    def do_action(self, aid):
        fs = list(self.files)
        try:
            if aid == "copy":
                gfiles = [Gio.File.new_for_path(p) for p in fs]
                prov = Gdk.ContentProvider.new_union([
                    Gdk.ContentProvider.new_for_value(GObject.Value(Gdk.FileList, Gdk.FileList.new_from_list(gfiles))),
                    Gdk.ContentProvider.new_for_bytes("text/uri-list", GLib.Bytes(actions.uri_list(fs).encode())),
                    Gdk.ContentProvider.new_for_bytes("x-special/gnome-copied-files",
                                                      GLib.Bytes(actions.gnome_copied_files(fs).encode())),
                ])
                self.get_clipboard().set_content(prov)
                self.done_action(f"Copied {len(fs)} file{'s' * (len(fs) > 1)}")
            elif aid == "copy_path":
                self.get_clipboard().set("\n".join(fs))
                self.done_action("Path copied")
            elif aid == "move":
                self.move_to(fs)
            elif aid == "float":
                FloatWindow(self.app, fs[0]).present()
                self.done_action("Floating")
            else:
                actions.RUN[aid](fs)
                if aid == "trash":
                    self.set_files([])
                self.done_action({"trash": "Moved to Trash", "show": "", "terminal": "", "send": "Sent"}[aid])
        except Exception as e:
            jobs.log.exception("action %s failed", aid)
            self.show_toast(str(e), bad=True)

    def done_action(self, msg):
        if msg:
            self.wheel.set_status(msg)
            self.show_toast(msg)
        if self.popup:
            GLib.timeout_add(500, lambda: (self.close(), False)[1])

    def move_to(self, fs):
        d = Gtk.FileDialog(title="Move to…", modal=True)
        last = self.app.cfg["last_move_dir"]
        if last and os.path.isdir(last):
            d.set_initial_folder(Gio.File.new_for_path(last))
        self.modal_open = True

        def picked(dlg, res):
            self.modal_open = False
            try:
                dest = dlg.select_folder_finish(res).get_path()
            except GLib.Error:
                return
            moved = actions.move(fs, dest)
            self.app.cfg["last_move_dir"] = dest
            self.app.save()
            self.set_files([] if not self.pinned else moved, pinned=self.pinned)
            self.done_action(f"Moved to {Path(dest).name}")
        d.select_folder(self, None, picked)

    # ------------------------------------------------------------ input
    def mode_for_key(self, name):
        for i, m in enumerate(MODES):
            if self.app.cfg["keys"].get(m) == name:
                return i
        return None

    def on_drag(self, dt, x, y):
        v = dt.get_value()
        if v is not None:
            paths = [f.get_path() for f in v.get_files() if f.get_path()]
            if paths and paths != self.files:
                self.set_files(paths)
        st = dt.get_current_event().get_modifier_state() if dt.get_current_event() else 0
        held = [name for mask, name in MASK_MOD if st & mask]
        m = self.mode_for_key(held[0]) if held else 0
        self.wheel.set_mode(m if m is not None else 0)
        self.wheel.hover_at(x, y)
        return Gdk.DragAction.COPY

    def on_drop(self, dt, val, x, y):
        paths = [f.get_path() for f in val.get_files() if f.get_path()]
        if not paths:
            return False
        if paths != self.files:
            self.set_files(paths)
        i = self.wheel.hit(x, y)
        if i >= 0:
            self.wheel.apply(i)  # zero-click: dropped on a slice
        else:
            self.wheel.set_status("Pick a slice  ·  Tab switches wheel")
        return True

    def on_click(self, g, n, x, y):
        if not self.files:
            self.choose_files()
            return
        i = self.wheel.hit(x, y)
        if i >= 0:
            self.wheel.hover = i
            self.wheel.apply(i)

    def on_key(self, c, kv, code, st):
        w = self.wheel
        ctrl = st & Gdk.ModifierType.CONTROL_MASK
        if kv == Gdk.KEY_Escape:
            if self.job:
                self.job.cancel()
            elif self.popup:
                self.close()
            elif self.files and not self.pinned:
                self.set_files([])
                w.set_status("")
            else:
                w.set_status("")
        elif ctrl and kv in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste()
        elif ctrl and kv in (Gdk.KEY_o, Gdk.KEY_O):
            self.choose_files()
        elif ctrl and kv == Gdk.KEY_comma:
            self.open_settings()
        elif kv in KEYVAL_MOD:
            m = self.mode_for_key(KEYVAL_MOD[kv])
            if m is not None:
                w.set_mode(m)
            return False
        elif kv in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            back = kv == Gdk.KEY_ISO_Left_Tab or st & Gdk.ModifierType.SHIFT_MASK
            w.set_mode((w.mode + (-1 if back else 1)) % 3)
        elif kv in (Gdk.KEY_Right, Gdk.KEY_Down):
            w.move(1)
        elif kv in (Gdk.KEY_Left, Gdk.KEY_Up):
            w.move(-1)
        elif kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            w.apply()
        else:
            return False
        return True

    def on_active(self, *_):
        active = self.is_active()
        if self.was_active and not active and not self.job and not self.modal_open:
            GLib.timeout_add(150, self._close_if_inactive)
        self.was_active |= active

    def _close_if_inactive(self):
        if not self.is_active() and not self.job and not self.modal_open:
            self.close()
        return False

    def paste(self):
        cb = self.get_clipboard()

        def got_files(cb, res):
            try:
                v = cb.read_value_finish(res)
                paths = [f.get_path() for f in v.get_files() if f.get_path()]
            except GLib.Error:
                paths = []
            if paths:
                self.set_files(paths)
            else:
                cb.read_text_async(None, got_text)

        def got_text(cb, res):
            try:
                text = cb.read_text_finish(res) or ""
            except GLib.Error:
                text = ""
            paths = [ln.strip() for ln in text.splitlines() if ln.strip() and os.path.exists(ln.strip())]
            if paths:
                self.set_files(paths)
            else:
                self.show_toast("Nothing to paste: copy some files first")
        cb.read_value_async(Gdk.FileList, GLib.PRIORITY_DEFAULT, None, got_files)

    def choose_files(self):
        d = Gtk.FileDialog(title="Choose files", modal=True)
        self.modal_open = True

        def picked(dlg, res):
            self.modal_open = False
            try:
                lst = dlg.open_multiple_finish(res)
            except GLib.Error:
                return
            paths = [lst.get_item(i).get_path() for i in range(lst.get_n_items())]
            self.set_files([p for p in paths if p], pinned=True)
        d.open_multiple(self, None, picked)

    def show_toast(self, text, path=None, bad=False):
        self.toast_label.set_text(text)
        self._toast_path = path
        self.toast_btn.set_visible(bool(path))
        box = self.toast.get_child()
        (box.add_css_class if bad else box.remove_css_class)("bad")
        self.choose.set_visible(False)
        self.toast.set_reveal_child(True)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
        self._toast_timer = GLib.timeout_add(3500, self._hide_toast)

    def _hide_toast(self):
        self._toast_timer = 0
        self.toast.set_reveal_child(False)
        self.choose.set_visible(not self.files)
        return False

    def open_settings(self):
        self.modal_open = True
        win = SettingsWindow(self.app, self)
        win.connect("close-request", lambda *_: self._modal_closed() or False)
        win.present()

    # ------------------------------------------------------------ screenshots / smoke tests
    def run_demo(self, demo):
        if "mode" in demo:
            self.wheel.set_mode(int(demo["mode"]))
        if "page" in demo:
            self.wheel.page = int(demo["page"])
            self.wheel.refresh(animate=False)
        if "hover" in demo:
            self.wheel.hover = int(demo["hover"])
            self.wheel._animate()
        if demo.get("settings"):
            self.open_settings()
        if demo.get("run"):
            self.apply(tuple(demo["run"]))
        return False


# ---------------------------------------------------------------- settings
class SettingsWindow(Gtk.Window):
    def __init__(self, app, parent):
        super().__init__(transient_for=parent, modal=True, title="Satsuma Settings", default_width=460,
                         resizable=False)
        self.app = app
        styled(self, app, "satsuma-settings")
        cfg = app.cfg
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                   max_content_height=640)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=18, margin_bottom=18,
                      margin_start=22, margin_end=22)
        outer.set_child(box)
        self.set_child(outer)
        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        box.append(self._section("Wheels"))
        box.append(grid)
        self.row = 0

        def add(label, widget, g=grid):
            lab = Gtk.Label(label=label, xalign=0, hexpand=True)
            widget.update_relation([Gtk.AccessibleRelation.LABELLED_BY], [lab])
            g.attach(lab, 0, self.row, 1, 1)
            g.attach(widget, 1, self.row, 1, 1)
            self.row += 1

        keys = ("shift", "ctrl", "alt", "super")
        self.key_drops = {}
        for m, name in zip(MODES, ("Convert wheel key", "Tools wheel key", "Actions wheel key")):
            dd = Gtk.DropDown.new_from_strings(list(keys))
            dd.set_selected(keys.index(cfg["keys"][m]))
            dd.connect("notify::selected", self.on_key, m, keys)
            self.key_drops[m] = dd
            add(name, dd)

        grid2 = Gtk.Grid(column_spacing=16, row_spacing=10)
        box.append(self._section("Output"))
        box.append(grid2)
        self.row = 0
        where = Gtk.DropDown.new_from_strings(["Next to the original", "In a folder"])
        where.set_selected(1 if cfg["output"] == "folder" else 0)
        add("Save results", where, grid2)
        self.folder_btn = Gtk.Button(label=self._short(cfg["output_folder"]))
        self.folder_btn.set_sensitive(cfg["output"] == "folder")
        self.folder_btn.connect("clicked", self.pick_folder)
        add("Folder", self.folder_btn, grid2)
        where.connect("notify::selected", self.on_where)
        q = Gtk.SpinButton.new_with_range(1, 100, 1)
        q.set_value(cfg["image_quality"])
        q.connect("value-changed", lambda s: self.set("image_quality", int(s.get_value())))
        add("Image quality", q, grid2)
        vq = ("smaller", "balanced", "better")
        vdd = Gtk.DropDown.new_from_strings(["Smaller files", "Balanced", "Better quality"])
        vdd.set_selected(vq.index(cfg["video_quality"]))
        vdd.connect("notify::selected", lambda d, _p: self.set("video_quality", vq[d.get_selected()]))
        add("Video quality", vdd, grid2)
        for key, label in (("keep_metadata", "Keep metadata"), ("open_folder", "Open folder after converting"),
                           ("notifications", "Notifications")):
            sw = Gtk.Switch(active=cfg[key], halign=Gtk.Align.END)
            sw.connect("notify::active", lambda s, _p, key=key: self.set(key, s.get_active()))
            add(label, sw, grid2)
        th = Gtk.DropDown.new_from_strings(["Light", "Dark"])
        th.set_selected(1 if cfg["theme"] == "dark" else 0)
        th.connect("notify::selected", lambda d, _p: self.set("theme", ("light", "dark")[d.get_selected()]))
        add("Theme", th, grid2)

        box.append(self._section("Missing tools"))
        locked = formats.locked()
        if not locked:
            box.append(Gtk.Label(label="Every converter is installed. All options unlocked.", xalign=0,
                                 css_classes=["dim"]))
        for binary, n in sorted(locked.items(), key=lambda kv: -kv[1]):
            hint = formats.install_hint(binary)
            pkg = formats.PACKAGES.get(binary, (binary,))[0]
            box.append(Gtk.Label(label=f"Install {pkg} to unlock {n} option{'s' * (n > 1)}", xalign=0))
            cmds = Gtk.Label(label="\n".join(f"{k:7} {v}" for k, v in hint.items()), xalign=0, selectable=True,
                             css_classes=["cmd", "dim"])
            box.append(cmds)
        log = Gtk.Label(label=f"Log: {config.cache_dir() / 'satsuma.log'}", xalign=0, selectable=True,
                        css_classes=["dim"], margin_top=10, wrap=True)
        box.append(log)
        k = Gtk.EventControllerKey()
        k.connect("key-pressed", lambda _c, kv, *_: (self.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        self.add_controller(k)

    @staticmethod
    def _section(text):
        return Gtk.Label(label=text, xalign=0, css_classes=["section"])

    @staticmethod
    def _short(p):
        home = str(Path.home())
        return "~" + p[len(home):] if p.startswith(home) else p

    def set(self, key, value):
        self.app.cfg[key] = value
        self.app.save()

    def on_key(self, dd, _p, mode, keys):
        new = keys[dd.get_selected()]
        k = self.app.cfg["keys"]
        old = k[mode]
        for other, v in k.items():  # keys stay unique: swap with the wheel that had it
            if other != mode and v == new:
                k[other] = old
                self.key_drops[other].set_selected(keys.index(old))
        k[mode] = new
        self.app.save()

    def on_where(self, dd, _p):
        folder = dd.get_selected() == 1
        self.folder_btn.set_sensitive(folder)
        self.set("output", "folder" if folder else "source")

    def pick_folder(self, *_):
        d = Gtk.FileDialog(title="Save results in", modal=True)

        def picked(dlg, res):
            try:
                p = dlg.select_folder_finish(res).get_path()
            except GLib.Error:
                return
            self.folder_btn.set_label(self._short(p))
            self.set("output_folder", p)
        d.select_folder(self, None, picked)


# ---------------------------------------------------------------- float
def preview_png(path):
    """A still for the float window: images as-is (or via ImageMagick), video frame, pdf page 1."""
    k = formats.kind(path)
    out = os.path.join(tempfile.mkdtemp(prefix="satsuma-float-"), "p.png")
    cmd = {"image": ["convert", path + "[0]", "-auto-orient", "-thumbnail", "640x640>", out],
           "video": ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", path, "-frames:v", "1",
                     "-vf", "scale='min(640,iw)':-2", out],
           "pdf": ["pdftoppm", "-png", "-r", "60", "-singlefile", "-f", "1", "-l", "1", path, out[:-4]]}.get(k)
    if cmd and subprocess.run(cmd, capture_output=True, check=False).returncode == 0 and os.path.exists(out):
        return out
    return None


class FloatWindow(Gtk.Window):
    def __init__(self, app, path):
        super().__init__(application=app, title=Path(path).name, default_width=320, default_height=240)
        styled(self, app, "satsuma")
        self.path = path
        png = preview_png(path)
        if png:
            pic = Gtk.Picture.new_for_filename(png)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.update_property([Gtk.AccessibleProperty.LABEL], [f"Preview of {Path(path).name}"])
            child = pic
        else:
            child = Gtk.Label(label=Path(path).name, wrap=True)
        self.set_child(child)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self, None, None))
        child.add_controller(click)
        k = Gtk.EventControllerKey()
        k.connect("key-pressed", lambda _c, kv, *_: (self.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        self.add_controller(k)
        self.connect("map", lambda *_: GLib.idle_add(lambda: x11_keep_above(self) and False))


def run_gui(files, popup=False, wheel=None):
    argv = ["satsuma"] + (["--popup"] if popup else []) + (["--wheel", wheel] if wheel else []) + files
    return App().run(argv)
