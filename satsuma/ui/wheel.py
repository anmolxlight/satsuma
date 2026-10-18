"""The radial wheel: 3D keycap row, rounded donut slices, orange active slice, progress ring."""
import math
from dataclasses import dataclass

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, PangoCairo  # noqa: E402

ORANGE = (0.992, 0.329, 0.0)  # #FD5400
PER_PAGE = 10  # more than this -> pages with a "More" slice
THEMES = {
    "light": {"bg": (0.965, 0.965, 0.96), "ring": (0.925, 0.93, 0.925), "ring_edge": (0.88, 0.885, 0.88),
                  "seg_in": (0.92, 0.925, 0.925), "seg_out": (0.985, 0.985, 0.985), "seg_edge": (1, 1, 1, 0.9),
                  "pill": (1, 1, 1), "text": (0.08, 0.08, 0.08), "sub": (0.4, 0.4, 0.4), "key_hi": (1, 1, 1),
                  "key_lo": (0.95, 0.95, 0.93), "key_lip": (0.86, 0.87, 0.83), "key_edge": (0.85, 0.85, 0.83),
                  "key_text": (0.42, 0.42, 0.42), "empty": (0.985, 0.985, 0.98), "dash": (0.8, 0.8, 0.78),
                  "bad": (0.8, 0.2, 0.15), "track": (0.87, 0.875, 0.87)},
    "dark": {"bg": (0.105, 0.105, 0.11), "ring": (0.145, 0.145, 0.155), "ring_edge": (0.2, 0.2, 0.21),
                 "seg_in": (0.19, 0.19, 0.2), "seg_out": (0.235, 0.235, 0.245), "seg_edge": (1, 1, 1, 0.06),
                 "pill": (0.24, 0.24, 0.25), "text": (0.93, 0.93, 0.93), "sub": (0.62, 0.62, 0.64), "key_hi": (0.27, 0.27, 0.28),
                 "key_lo": (0.21, 0.21, 0.22), "key_lip": (0.07, 0.07, 0.075), "key_edge": (0.3, 0.3, 0.31),
                 "key_text": (0.75, 0.75, 0.77), "empty": (0.13, 0.13, 0.14), "dash": (0.3, 0.3, 0.32),
                 "bad": (1.0, 0.45, 0.38), "track": (0.2, 0.2, 0.21)},
}
KEY_GLYPH = {"shift": "⇧", "ctrl": "⌃", "alt": "⌥", "super": "❖"}
MODES = ("convert", "tools", "actions")
MODE_CAPTION = ("Convert formats", "File tools", "File actions")
MORE = object()


@dataclass
class Slice:
    label: str
    caption: str
    payload: object


def _font():
    names = {f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}
    return "Inter" if "Inter" in names else "Noto Sans"


def ease_out(t):
    return 1 - (1 - t) ** 3


def smooth(t):
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class Wheel(Gtk.DrawingArea):
    """Pure view + hit testing. The window feeds slices and reacts to on_apply(payload)."""

    def __init__(self, provider, on_apply, keys, theme="light"):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.provider, self.on_apply, self.keys = provider, on_apply, keys
        self.theme = THEMES[theme]
        self.files, self.mode, self.hover, self.page = [], 0, -1, 0
        self.label = ""          # center pill text
        self.status, self.status_bad = "", False
        self.job = None          # running jobs.Job -> progress ring
        self.hint = "Drop files here"
        self._items, self._glow, self._open, self._spin = [], {}, 1.0, 0.0
        self._tick_id, self._last = 0, None
        self.font = _font()
        self.set_draw_func(self._draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Satsuma wheel"])

    # ------------------------------------------------------------ state
    def refresh(self, animate=True):
        self._items = self.provider(self.mode)
        pages = max(1, math.ceil(len(self._items) / (PER_PAGE - 1))) if len(self._items) > PER_PAGE else 1
        self.page %= pages
        self.hover = min(self.hover, len(self.slices()) - 1)
        if animate:
            self._open = 0.0
        self._animate()

    def slices(self):
        n = len(self._items)
        if n <= PER_PAGE:
            return list(self._items)
        pages = math.ceil(n / (PER_PAGE - 1))
        per = math.ceil(n / pages)
        chunk = self._items[self.page * per:(self.page + 1) * per]
        last = self.page == pages - 1
        return chunk + [Slice("Back" if last else "More", f"Page {(self.page + 1) % pages + 1} of {pages}", MORE)]

    def set_mode(self, m):
        if m != self.mode:
            self.mode, self.page, self.hover = m % 3, 0, -1
            self.refresh()

    def set_theme(self, name):
        self.theme = THEMES[name]
        self.queue_draw()

    def move(self, d):
        n = len(self.slices())
        if n:
            self.hover = (self.hover + d) % n if self.hover >= 0 else (0 if d > 0 else n - 1)
            self._animate()

    def apply(self, i=None):
        i = self.hover if i is None else i
        sl = self.slices()
        if self.job or not (0 <= i < len(sl)):
            return
        if sl[i].payload is MORE:
            self.page += 1
            self.refresh()
            return
        self.on_apply(sl[i].payload)

    def set_status(self, text, bad=False):
        self.status, self.status_bad = text, bad
        self.queue_draw()

    def set_job(self, job):
        self.job = job
        self._animate()

    # ------------------------------------------------------------ geometry
    def geom(self):
        w, h = self.get_width(), self.get_height()
        R = max(60, min(w - 48, h - 236) / 2)
        return w / 2, 146 + R, R, R * 0.40

    def hit(self, x, y):
        n = len(self.slices())
        cx, cy, R, r = self.geom()
        d = math.hypot(x - cx, y - cy)
        if not n or not self.files or d < r or d > R + 6:
            return -1
        a = (math.atan2(y - cy, x - cx) + math.pi / 2 + math.pi / n) % (2 * math.pi)  # slice 0 centered on top
        return int(a / (2 * math.pi / n))

    def hover_at(self, x, y):
        h = self.hit(x, y)
        if h != self.hover:
            self.hover = h
            self._animate()

    # ------------------------------------------------------------ animation
    def _animate(self):
        if not self._tick_id:
            self._last = None
            self._tick_id = self.add_tick_callback(self._tick)
        self.queue_draw()

    def _tick(self, _w, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0 if self._last is None else min(now - self._last, 0.05)
        self._last = now
        busy = False
        for i in set(self._glow) | {self.hover}:
            target = 1.0 if i == self.hover else 0.0
            v = self._glow.get(i, 0.0)
            v = min(target, v + dt / 0.12) if target > v else max(target, v - dt / 0.12)
            self._glow[i] = v
            busy |= v != target
        if self._open < 1:
            self._open = min(1.0, self._open + dt / 0.16)
            busy = True
        if self.job:
            self._spin = (self._spin + dt * 1.6) % 1
            busy = True
        self.queue_draw()
        if not busy:
            self._tick_id = 0
            return False
        return True

    # ------------------------------------------------------------ drawing
    def _text(self, c, s, x, y, rgb, size=12, bold=False, left=False, font=None, alpha=1.0):
        c.select_font_face(font or self.font, cairo.FONT_SLANT_NORMAL,
                           cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)
        e = c.text_extents(s)
        c.set_source_rgba(*rgb[:3], alpha)
        c.move_to(x if left else x - e.width / 2 - e.x_bearing, y - e.height / 2 - e.y_bearing)
        c.show_text(s)
        return e.x_advance

    def _width(self, c, s, size, bold=True):
        c.select_font_face(self.font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else 0)
        c.set_font_size(size)
        return c.text_extents(s).x_advance

    def _fit(self, c, label, maxw, size):
        """One line if it fits, else two lines at the middle space, else shrink (never below 10px)."""
        two = None
        if " " in label:
            cut = min((i for i, ch in enumerate(label) if ch == " "), key=lambda i: abs(i - len(label) / 2))
            two = [label[:cut], label[cut + 1:]]
        while size > 10:
            if self._width(c, label, size) <= maxw:
                return [label], size
            if two and max(self._width(c, ln, size) for ln in two) <= maxw:
                return two, size
            size -= 1
        return two or [label], 10

    @staticmethod
    def _rrect(c, x, y, w, h, rad):
        c.new_sub_path()
        for ax, ay, a in ((x + w - rad, y + rad, -math.pi / 2), (x + w - rad, y + h - rad, 0),
                          (x + rad, y + h - rad, math.pi / 2), (x + rad, y + rad, math.pi)):
            c.arc(ax, ay, rad, a, a + math.pi / 2)
        c.close_path()

    @staticmethod
    def _segment(c, cx, cy, R, r, a0, a1, gap=5, rad=14):
        """Donut slice with a gap and rounded corners (fillets drawn as short curves)."""
        rad = min(rad, (R - r) / 3, R * (a1 - a0) / 4)
        go, gi_ = gap / R, gap / r
        ro, ri = rad / R, rad / (r + rad)

        def p(rr, a):
            return cx + rr * math.cos(a), cy + rr * math.sin(a)
        c.new_path()
        c.arc(cx, cy, R, a0 + go + ro, a1 - go - ro)
        c.curve_to(*p(R, a1 - go), *p(R, a1 - go), *p(R - rad, a1 - go * R / (R - rad)))
        c.line_to(*p(r + rad, a1 - gap / (r + rad)))
        c.curve_to(*p(r, a1 - gi_), *p(r, a1 - gi_), *p(r, a1 - gi_ - ri))
        c.arc_negative(cx, cy, r, a1 - gi_ - ri, a0 + gi_ + ri)
        c.curve_to(*p(r, a0 + gi_), *p(r, a0 + gi_), *p(r + rad, a0 + gap / (r + rad)))
        c.line_to(*p(R - rad, a0 + go * R / (R - rad)))
        c.curve_to(*p(R, a0 + go), *p(R, a0 + go), *p(R, a0 + go + ro))
        c.close_path()

    def _keycaps(self, c, w):
        T = self.theme
        kw, kh, gap = 76, 62, 20
        x0 = w / 2 - (3 * kw + 2 * gap) / 2
        for i, m in enumerate(MODES):
            key = self.keys.get(m, "shift")
            x, y, on = x0 + i * (kw + gap), 20, i == self.mode
            dy = 3 if on else 0
            c.push_group()
            self._rrect(c, x, y + 5, kw, kh, 11)
            c.set_source_rgb(*T["key_lip"])
            c.fill()
            self._rrect(c, x, y + dy, kw, kh, 11)
            g = cairo.LinearGradient(0, y, 0, y + kh)
            g.add_color_stop_rgb(0, *T["key_hi"])
            g.add_color_stop_rgb(1, *T["key_lo"])
            c.set_source(g)
            c.fill_preserve()
            c.set_source_rgb(*T["key_edge"])
            c.set_line_width(1)
            c.stroke()
            self._text(c, KEY_GLYPH.get(key, "?"), x + 13, y + 19 + dy, T["key_text"], 18, left=True,
                       font="DejaVu Sans Mono")
            self._text(c, key, x + 13, y + 44 + dy, T["key_text"], 11, left=True)
            c.pop_group_to_source()
            c.paint_with_alpha(1 if on else 0.45)
        self._text(c, MODE_CAPTION[self.mode], w / 2, 20 + kh + 24, T["sub"], 12)

    def _draw(self, _a, c, w, h):
        T = self.theme
        c.set_source_rgb(*T["bg"])
        c.paint()
        self._keycaps(c, w)
        cx, cy, R, r = self.geom()
        # base ring (also the progress track)
        c.arc(cx, cy, R + 10, 0, 2 * math.pi)
        c.set_source_rgb(*T["ring"])
        c.fill()
        c.arc(cx, cy, R + 10, 0, 2 * math.pi)
        c.set_source_rgb(*T["ring_edge"])
        c.set_line_width(1)
        c.stroke()
        sl = self.slices() if self.files else []
        if not self.files:
            c.arc(cx, cy, R - 4, 0, 2 * math.pi)
            c.set_source_rgb(*T["empty"])
            c.fill()
            c.set_dash([5, 6])
            c.arc(cx, cy, R - 18, 0, 2 * math.pi)
            c.set_source_rgb(*T["dash"])
            c.stroke()
            c.set_dash([])
            self._text(c, self.hint, cx, cy - 12, T["text"], 19, bold=True)
            k = self.keys
            self._text(c, f"{k['convert']} convert  ·  {k['tools']} tools  ·  {k['actions']} actions",
                       cx, cy + 16, T["sub"], 11)
        else:
            # scale-in on open
            s = 0.86 + 0.14 * ease_out(self._open)
            c.save()
            c.translate(cx, cy)
            c.scale(s, s)
            c.translate(-cx, -cy)
            c.push_group()
            n = max(len(sl), 1)
            step = 2 * math.pi / n
            rm = (R + r + 8) / 2
            maxw = min(2 * rm * math.sin(min(step, math.pi) / 2) * 0.8, (R - r) * 1.15)
            for i, item in enumerate(sl):
                a0 = -math.pi / 2 - step / 2 + i * step
                g = smooth(self._glow.get(i, 0.0))
                if n == 1:
                    c.new_path()
                    c.arc(cx, cy, R, 0, 2 * math.pi)
                    c.arc_negative(cx, cy, r + 8, 2 * math.pi, 0)
                else:
                    self._segment(c, cx, cy, R, r + 8, a0, a0 + step)
                grad = cairo.RadialGradient(cx, cy, r, cx, cy, R)  # the subtle shine
                grad.add_color_stop_rgb(0, *mix(T["seg_in"], ORANGE, g))
                grad.add_color_stop_rgb(1, *mix(T["seg_out"], ORANGE, g))
                c.set_source(grad)
                c.fill_preserve()
                c.set_source_rgba(*T["seg_edge"][:3], T["seg_edge"][3] * (1 - g))
                c.set_line_width(1.2)
                c.stroke()
                am = a0 + step / 2 if n > 1 else -math.pi / 2
                tx, ty = cx + rm * math.cos(am), cy + rm * math.sin(am)
                size = 15 if self.mode == 0 and n <= 8 else 13
                lines, size = self._fit(c, item.label, maxw, size)
                col = mix(T["text"], (1, 1, 1), g)
                for j, ln in enumerate(lines):
                    off = (j - (len(lines) - 1) / 2) * (size + 2)
                    self._text(c, ln, tx, ty + off, col, size, bold=True)
            c.pop_group_to_source()
            c.paint_with_alpha(0.55 + 0.45 * ease_out(self._open) if not self.job else 0.5)
            c.restore()
            # center hole + pill
            c.arc(cx, cy, r, 0, 2 * math.pi)
            c.set_source_rgb(*T["bg"])
            c.fill()
            label = self.label
            if self.job:
                p = self.job.progress
                label = f"{int(p * 100)}%" if p is not None else "…"
            pw = max(84, self._width(c, label, 13, False) + 40)
            self._rrect(c, cx - pw / 2, cy - 18, pw, 36, 18)
            c.set_source_rgb(*T["pill"])
            c.fill()
            self._text(c, label, cx, cy, T["text"], 13)
            if not sl:
                self._text(c, "Nothing here for this file", cx, cy - r - (R - r) / 2, T["sub"], 12)
        if self.job:
            self._progress(c, cx, cy, R + 10)
        cap, bad = self.status, self.status_bad
        if not cap and self.files and 0 <= self.hover < len(sl):
            cap = sl[self.hover].caption
        if cap:
            self._text(c, cap, w / 2, cy + R + 36, T["bad"] if bad else T["sub"], 12.5)

    def _progress(self, c, cx, cy, rad):
        p = self.job.progress
        c.set_line_width(5)
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.set_source_rgb(*self.theme["track"])
        c.new_path()
        c.arc(cx, cy, rad - 3, 0, 2 * math.pi)
        c.stroke()
        c.set_source_rgb(*ORANGE)
        c.new_path()
        if p is None:  # indeterminate: a quarter arc spinning
            a = self._spin * 2 * math.pi - math.pi / 2
            c.arc(cx, cy, rad - 3, a, a + math.pi / 2)
        else:
            c.arc(cx, cy, rad - 3, -math.pi / 2, -math.pi / 2 + max(p, 0.005) * 2 * math.pi)
        c.stroke()
