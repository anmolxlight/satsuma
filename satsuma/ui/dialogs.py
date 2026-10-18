"""Small keyboard-first prompts (trim, crop, resize, split, speed, password...).
Prefilled with defaults, Enter confirms, Esc cancels, choices are one click (or just type)."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402


def ask(parent, title, fields, values, on_ok, on_cancel=None):
    """fields: tools.Field list; values: {key: default}. on_ok(dict) when confirmed."""
    win = Gtk.Window(transient_for=parent, modal=True, title=title, resizable=False, decorated=False)
    win.add_css_class("satsuma-prompt")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=18, margin_bottom=18,
                  margin_start=20, margin_end=20)
    win.set_child(box)
    head = Gtk.Label(label=title, xalign=0)
    head.add_css_class("prompt-title")
    box.append(head)
    entries = {}
    for f in fields:
        lab = Gtk.Label(label=f.label, xalign=0)
        lab.add_css_class("prompt-label")
        box.append(lab)
        e = Gtk.Entry(text=str(values.get(f.key, "")), activates_default=True, width_chars=22)
        e.update_relation([Gtk.AccessibleRelation.LABELLED_BY], [lab])
        if f.secret:
            e.set_visibility(False)
            e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        box.append(e)
        entries[f.key] = e
        if f.choices:
            row = Gtk.Box(spacing=6)
            for ch in f.choices:
                b = Gtk.Button(label=ch)
                b.add_css_class("chip")
                b.connect("clicked", lambda _b, e=e, ch=ch: (e.set_text(ch), e.grab_focus()))
                row.append(b)
            box.append(row)
    btns = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=6)
    cancel = Gtk.Button(label="Cancel")
    ok = Gtk.Button(label="Apply")
    ok.add_css_class("suggested-action")
    ok.add_css_class("accent")
    btns.append(cancel)
    btns.append(ok)
    box.append(btns)
    win.set_default_widget(ok)
    done = []

    def confirm(*_):
        done.append(1)
        vals = {k: e.get_text() for k, e in entries.items()}
        win.close()
        on_ok(vals)

    def close(*_):
        win.close()

    def closed(*_):
        if not done and on_cancel:
            on_cancel()
        return False

    ok.connect("clicked", confirm)
    cancel.connect("clicked", close)
    win.connect("close-request", closed)
    keys = Gtk.EventControllerKey()
    keys.connect("key-pressed", lambda _c, kv, _k, _s: (close(), True)[1] if kv == Gdk.KEY_Escape else False)
    win.add_controller(keys)
    win.present()
    if entries:
        first = next(iter(entries.values()))
        first.grab_focus()
    return win
