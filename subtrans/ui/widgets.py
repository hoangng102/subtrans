"""Reusable widgets for the SubTrans UI.

Native Tk has no rounded corners, so boxes are drawn as anti-aliased PNG-like images
(PIL, 4x supersampled) placed on a Canvas.  Widgets keep the small part of the ttk API that
the rest of the app already uses (configure(text/state), state([...]), ["values"], invoke()).
"""
import math
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from . import theme as T
from .theme import px

_SS = 4
_IMAGES = {}
_FONTS = {}


def _rgba(hexcolor, alpha=255):
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def _bg(widget):
    try:
        return widget.cget("bg")
    except tk.TclError:
        return T.WINDOW


def _measure(font_tuple, text):
    f = _FONTS.get(font_tuple)
    if f is None:
        f = _FONTS[font_tuple] = tkfont.Font(font=font_tuple)
    return f.measure(text)


def _linespace(font_tuple):
    _measure(font_tuple, "x")
    return _FONTS[font_tuple].metrics("linespace")


def _perimeter(w, h, r, inset):
    """Points along a rounded rectangle outline (used for dashed borders)."""
    x0, y0, x1, y1 = inset, inset, w - inset, h - inset
    r = max(1, r - inset)
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(0, 91, 6):
            a = math.radians(a0 + i)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def _pil_round(w, h, r, fill, outline=None, bw=1, dash=False):
    """Anti-aliased rounded rectangle as a PIL image (4x supersampled). fill/outline may be None."""
    W, H, R, B = w * _SS, h * _SS, r * _SS, bw * _SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if outline and not dash:
        d.rounded_rectangle([0, 0, W - 1, H - 1], R, fill=_rgba(outline))
        d.rounded_rectangle([B, B, W - 1 - B, H - 1 - B], max(R - B, 0), fill=_rgba(fill) if fill else (0, 0, 0, 0))
    else:
        if fill:
            d.rounded_rectangle([0, 0, W - 1, H - 1], R, fill=_rgba(fill))
        if outline and dash:
            pts = _perimeter(W, H, R, B // 2)
            pattern, k, remain = (6 * _SS, 4 * _SS), 0, 6 * _SS     # k: 0 = dash, 1 = gap
            for a, b in zip(pts, pts[1:]):
                seg = math.hypot(b[0] - a[0], b[1] - a[1])
                if seg == 0:
                    continue
                ux, uy, pos = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg, 0.0
                while pos < seg:           # long straight edges are cut into dashes and gaps
                    take = min(remain, seg - pos)
                    if k == 0:
                        d.line([(a[0] + ux * pos, a[1] + uy * pos), (a[0] + ux * (pos + take), a[1] + uy * (pos + take))],
                               fill=_rgba(outline), width=B)
                    pos += take
                    remain -= take
                    if remain <= 1e-6:
                        k ^= 1
                        remain = pattern[k]
    return im.resize((w, h), Image.LANCZOS)


def round_image(w, h, r, fill, outline=None, bw=1, dash=False):
    """Small fixed-size rounded box as a cached Tk PhotoImage (swatches, badges, checkbox)."""
    key = (w, h, r, fill, outline, bw, dash)
    ph = _IMAGES.get(key)
    if ph is None:
        ph = _IMAGES[key] = ImageTk.PhotoImage(_pil_round(w, h, r, fill, outline, bw, dash))
    return ph


_CORNERS = {}


def _corners(r, fill, outline, bw):
    """Four r x r corner images (TL, TR, BL, BR) of a rounded box, cached."""
    key = (r, fill, outline, bw)
    c = _CORNERS.get(key)
    if c is None:
        full = _pil_round(2 * r, 2 * r, r, fill, outline, bw)
        boxes = ((0, 0), (r, 0), (0, r), (r, r))
        c = _CORNERS[key] = [ImageTk.PhotoImage(full.crop((x, y, x + r, y + r))) for x, y in boxes]
    return c


def draw_round(cv, w, h, r, fill, outline=None, bw=1, dash=False, tag="bg"):
    """Draw a rounded box on a canvas using four small corner images plus plain rectangles.
    Cost does not grow with the box size, so resizing the window stays cheap."""
    r = max(2, min(r, w // 2, h // 2))
    if fill:
        cv.create_rectangle(r, 0, w - r + 1, h + 1, fill=fill, outline="", tags=tag)
        cv.create_rectangle(0, r, w + 1, h - r + 1, fill=fill, outline="", tags=tag)
    if outline:
        if dash:
            kw = dict(fill=outline, width=bw, dash=(6, 4), tags=tag)
            h2 = bw / 2
            cv.create_line(r, h2, w - r, h2, **kw)
            cv.create_line(r, h - h2, w - r, h - h2, **kw)
            cv.create_line(h2, r, h2, h - r, **kw)
            cv.create_line(w - h2, r, w - h2, h - r, **kw)
        else:
            kw = dict(fill=outline, outline="", tags=tag)
            cv.create_rectangle(r, 0, w - r + 1, bw, **kw)
            cv.create_rectangle(r, h - bw, w - r + 1, h + 1, **kw)
            cv.create_rectangle(0, r, bw, h - r + 1, **kw)
            cv.create_rectangle(w - bw, r, w + 1, h - r + 1, **kw)
    tl, tr, bl, br = _corners(r, fill, outline, bw)
    cv.create_image(0, 0, image=tl, anchor="nw", tags=tag)
    cv.create_image(w - r, 0, image=tr, anchor="nw", tags=tag)
    cv.create_image(0, h - r, image=bl, anchor="nw", tags=tag)
    cv.create_image(w - r, h - r, image=br, anchor="nw", tags=tag)


class Label(tk.Label):
    KINDS = {   # size, weight, colour
        "text": (13, "regular", T.TEXT),
        "label": (12, "medium", T.TEXT_LABEL),
        "hint": (12, "regular", T.TEXT_MUTED),
        "h": (13, "semibold", T.TEXT),
        "muted": (13, "regular", T.TEXT_MUTED),
        "mono": (12, "regular", T.TEXT),
    }

    def __init__(self, parent, text="", kind="text", fg=None, wrap=0, anchor="w", justify="left", **kw):
        size, weight, color = self.KINDS[kind]
        super().__init__(parent, text=text, bg=kw.pop("bg", _bg(parent)), fg=fg or color,
                         font=T.font(size, weight, mono=(kind == "mono")), anchor=anchor, justify=justify,
                         wraplength=px(wrap) if wrap else 0, bd=0, highlightthickness=0, **kw)


class Divider(tk.Frame):
    def __init__(self, parent, vertical=False, color=T.DIVIDER):
        super().__init__(parent, bg=color, width=1 if vertical else 1, height=1)
        if vertical:
            self.configure(width=1, height=px(20))


class DashedPanel(tk.Frame):
    """Canvas-drawn rounded box (supports a dashed border). Costly to repaint, so use only for small areas."""

    def __init__(self, parent, fill=T.SURFACE, outline=T.BORDER_CARD, radius=T.R_CARD, pad=T.PAD_CARD, dash=False):
        super().__init__(parent, bg=_bg(parent))
        self._fill, self._outline, self._radius, self._dash = fill, outline, px(radius), dash
        self._cv = tk.Canvas(self, bg=_bg(parent), highlightthickness=0, bd=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        inset = max(px(pad), px(4)) + 1
        self.body.pack(fill="both", expand=True, padx=inset, pady=inset)
        self._size = None
        self._ph = None
        self.bind("<Configure>", self._draw)

    def _draw(self, e):
        if (e.width, e.height) == self._size or e.width < 4 or e.height < 4:
            return
        self._size = (e.width, e.height)
        self._cv.delete("all")
        # One full anti-aliased image (not cached, so resizing does not accumulate images). The dashed border
        # has to be drawn as a whole to keep the dashes continuous around the corners.
        self._ph = ImageTk.PhotoImage(_pil_round(e.width, e.height, self._radius, self._fill, self._outline, 1,
                                                 self._dash))
        self._cv.create_image(0, 0, image=self._ph, anchor="nw")


_PIECES = {}


def _corner_pieces(r, fill, outline, bg, bw):
    """Four opaque r x r corner images already composited over the parent colour."""
    key = (r, fill, outline, bg, bw)
    p = _PIECES.get(key)
    if p is None:
        full = _pil_round(2 * r, 2 * r, r, fill, outline, bw)
        base = Image.new("RGBA", full.size, _rgba(bg))
        img = Image.alpha_composite(base, full).convert("RGB")
        p = _PIECES[key] = [ImageTk.PhotoImage(img.crop((x, y, x + r, y + r))) for x, y in
                            ((0, 0), (r, 0), (0, r), (r, r))]
    return p


class Panel(tk.Frame):
    """Rounded filled box. Put children into .body.

    A plain Frame (square, optional 1px border) plus four tiny corner canvases that fake the radius.
    Unlike a full-size canvas this costs nothing when the window is resized."""

    def __init__(self, parent, fill=T.SURFACE, outline=T.BORDER_CARD, radius=T.R_CARD, pad=T.PAD_CARD):
        bw = 1 if outline else 0
        # The 1px border is the outer frame's own colour showing around .inner. (A highlight border would
        # shift the corner pieces: place() coordinates start inside it.)
        super().__init__(parent, bg=outline or fill, bd=0, highlightthickness=0)
        r = px(radius)
        inner = tk.Frame(self, bg=fill)
        inner.pack(fill="both", expand=True, padx=bw, pady=bw)
        inset = max(px(pad), px(4))
        self.body = tk.Frame(inner, bg=fill)
        self.body.pack(fill="both", expand=True, padx=inset, pady=inset)
        pb = _bg(parent)
        pieces = _corner_pieces(r, fill, outline, pb, bw)
        for img, (rx, ry, ox, oy) in zip(pieces, ((0, 0, 0, 0), (1, 0, -r, 0), (0, 1, 0, -r), (1, 1, -r, -r))):
            cv = tk.Canvas(self, width=r, height=r, bg=pb, highlightthickness=0, bd=0)
            cv.create_image(0, 0, image=img, anchor="nw")
            cv.place(relx=rx, rely=ry, x=ox, y=oy)


class Card(Panel):
    pass


class _Rounded(tk.Canvas):
    """Canvas that redraws a rounded background whenever its size or state changes."""

    def __init__(self, parent, width, height, **kw):
        super().__init__(parent, width=width, height=height, bg=_bg(parent), highlightthickness=0, bd=0, **kw)
        self._ph = self._ph2 = None
        self.bind("<Configure>", lambda e: self.redraw())

    def _wh(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w, h = int(self.cget("width")), int(self.cget("height"))
        return w, h

    def redraw(self):
        raise NotImplementedError


class Button(_Rounded):
    def __init__(self, parent, text="", command=None, variant="default", small=False, icon=False, num=None,
                 state="normal", width=None, **kw):
        self._text, self._cmd, self._variant, self._num = text, command, variant, num
        self._small, self._icon, self._state, self._minw = small, icon, state, width
        self._hover = self._press = self._focus = False
        self._loading, self._spin_job, self._angle = False, None, 90
        self._font = T.font(12 if small else 13, "semibold" if variant == "primary" else "medium")
        h = px(T.H_SMALL if small else T.H_CONTROL)
        super().__init__(parent, self._calc_width(), h, takefocus=1)
        self.configure(cursor="hand2" if state != "disabled" else "arrow")
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, press=False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())

    def _calc_width(self):
        h = px(T.H_SMALL if self._small else T.H_CONTROL)
        if self._icon:
            return h
        padx = px(10 if self._small else 12)
        w = _measure(self._font, self._text) + 2 * padx + (px(26) if self._num else 0)
        if self._loading and self._num is None:
            w += px(22)                      # room for the spinner
        return max(w, px(self._minw) if self._minw else 0)

    def set_loading(self, flag):
        """Show a spinner and ignore clicks while a long action runs (the button keeps its look)."""
        flag = bool(flag)
        if flag == self._loading:
            return
        self._loading = flag
        if not self._icon:
            tk.Canvas.configure(self, width=self._calc_width())
        tk.Canvas.configure(self, cursor="arrow" if flag or self._state == "disabled" else "hand2")
        if flag:
            self._tick()
        elif self._spin_job is not None:
            self.after_cancel(self._spin_job)
            self._spin_job = None
        self.redraw()

    def _tick(self):
        self._angle = (self._angle - 30) % 360
        try:
            self.itemconfigure("spin", start=self._angle)
            self._spin_job = self.after(70, self._tick)
        except tk.TclError:
            self._spin_job = None

    def _spinner(self, cx, cy, d, color):
        self.create_arc(cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2, start=self._angle, extent=260,
                        style="arc", outline=color, width=max(2, px(2)), tags="spin")

    # --- ttk-like API
    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._text = kw.pop("text")
            tk.Canvas.configure(self, width=self._calc_width())
        if "state" in kw:
            self._state = kw.pop("state")
            tk.Canvas.configure(self, cursor="arrow" if self._state == "disabled" else "hand2")
        if "command" in kw:
            self._cmd = kw.pop("command")
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)
        self.redraw()

    config = configure

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def state(self, spec=None):
        if spec is None:
            return ("disabled",) if self._state == "disabled" else ()
        for s in spec:
            if s in ("disabled", "!disabled"):
                self.configure(state="disabled" if s == "disabled" else "normal")

    def invoke(self):
        if self._state != "disabled" and not self._loading and self._cmd:
            self._cmd()

    def _set(self, hover=None, press=None, focus=None):
        if hover is not None:
            self._hover = hover
        if press is not None:
            self._press = press
        if focus is not None:
            self._focus = focus
        self.redraw()

    def _on_press(self, e):
        if self._state != "disabled" and not self._loading:
            self.focus_set()
            self._set(press=True)

    def _on_release(self, e):
        was = self._press
        self._set(press=False)
        if was and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.invoke()

    def _colors(self):
        v = self._variant
        if self._state == "disabled":
            if v in ("ghost", "link"):
                return None, None, T.TEXT_DISABLED
            return T.WINDOW, T.BORDER_DISABLED, T.TEXT_DISABLED
        hot = self._hover or self._press
        if v == "primary":
            c = T.ACCENT_HOVER if hot else T.ACCENT
            return c, c, T.ON_ACCENT
        fg = T.ACCENT_TEXT if v == "link" else (T.TEXT_2 if v == "ghost" else T.TEXT)
        if v in ("ghost", "link"):
            return (T.HOVER_GHOST if hot else None), None, fg
        if self._press:
            return T.HOVER_GHOST, T.BORDER_HOVER, fg
        return (T.HOVER, T.BORDER_HOVER, fg) if hot else (T.SURFACE, T.BORDER_CONTROL, fg)

    def redraw(self):
        w, h = self._wh()
        self.delete("all")
        r = px(T.R_SMALL if self._small else T.R_CONTROL)
        fill, outline, fg = self._colors()
        if fill or outline:
            draw_round(self, w, h, r, fill, outline)
        x = w / 2
        if self._num is not None:
            d = px(18)
            tw = _measure(self._font, self._text)
            x0 = (w - (d + px(8) + tw)) / 2
            bg, nf = (T.ON_ACCENT, T.ACCENT) if self._variant == "primary" and self._state != "disabled" \
                else (T.HOVER_GHOST, T.TEXT_2)
            if self._loading:
                self._spinner(x0 + d / 2, h / 2, d - px(4), fg)
            else:
                self.create_oval(x0, h / 2 - d / 2, x0 + d, h / 2 + d / 2, fill=bg, outline=bg)
                self.create_text(x0 + d / 2, h / 2, text=str(self._num), fill=nf, font=T.font(11, "semibold"))
            self.create_text(x0 + d + px(8), h / 2, text=self._text, fill=fg, font=self._font, anchor="w")
        elif self._loading and self._icon:
            self._spinner(x, h / 2, px(14), fg)
        elif self._loading:
            d = px(14)
            x0 = (w - (d + px(8) + _measure(self._font, self._text))) / 2
            self._spinner(x0 + d / 2, h / 2, d, fg)
            self.create_text(x0 + d + px(8), h / 2, text=self._text, fill=fg, font=self._font, anchor="w")
        else:
            self.create_text(x, h / 2, text=self._text, fill=fg, font=self._font)
        if self._focus and self._state != "disabled":
            draw_round(self, w, h, r, None, T.ACCENT, 2, tag="ring")


class Entry(_Rounded):
    """Single-line text field with a rounded border; the real tk.Entry is .entry."""

    def __init__(self, parent, textvariable=None, width=None, mono=False, justify="left", state="normal",
                 show=None, small=False, placeholder="", **kw):
        h = px(T.H_SMALL if small else T.H_CONTROL)
        fsize = 12 if small else 13
        super().__init__(parent, px(width) if width else px(140), h)
        self._state, self._focus = state, False
        self.entry = tk.Entry(self, textvariable=textvariable, bd=0, relief="flat", highlightthickness=0,
                              font=T.font(fsize, mono=mono), fg=T.TEXT, insertbackground=T.TEXT, justify=justify,
                              disabledforeground=T.TEXT_DISABLED, selectbackground=T.ACCENT_CHIP_COUNT,
                              selectforeground=T.TEXT, show=show or "")
        self._hint = None
        if placeholder and textvariable is not None:
            self._hint = tk.Label(self.entry, text=placeholder, bg=T.SURFACE, fg=T.TEXT_DISABLED,
                                  font=T.font(fsize), bd=0)
            self._hint.bind("<Button-1>", lambda e: self.entry.focus_set())
            self._var = textvariable
            textvariable.trace_add("write", lambda *a: self._sync_hint())
            self._sync_hint()
        self._win = self.create_window(px(10), h // 2, window=self.entry, anchor="w")
        self.entry.bind("<FocusIn>", lambda e: self._setfocus(True))
        self.entry.bind("<FocusOut>", lambda e: self._setfocus(False))
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self._apply_state()

    def _setfocus(self, v):
        self._focus = v
        self.redraw()

    def _sync_hint(self):
        try:
            if self._var.get():
                self._hint.place_forget()
            else:
                self._hint.place(x=0, rely=0.5, anchor="w")
        except tk.TclError:
            pass

    def _apply_state(self):
        bg = T.WINDOW if self._state == "disabled" else (T.SURFACE_MUTED if self._state == "readonly" else T.SURFACE)
        self.entry.configure(state=self._state, bg=bg, disabledbackground=bg, readonlybackground=bg)
        self.redraw()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            self._apply_state()
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)

    config = configure

    def focus_set(self):
        self.entry.focus_set()

    def get(self):
        return self.entry.get()

    def redraw(self):
        w, h = self._wh()
        self.delete("bg")
        bg = T.WINDOW if self._state == "disabled" else (T.SURFACE_MUTED if self._state == "readonly" else T.SURFACE)
        draw_round(self, w, h, px(T.R_CONTROL), bg, T.ACCENT if self._focus else T.BORDER_CONTROL,
                   2 if self._focus else 1)
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(10, w - px(20)))
        self.coords(self._win, px(10), h // 2)


class Spinner(Entry):
    """Numeric field: Up/Down keys and the mouse wheel step the value inside [from_, to]."""

    def __init__(self, parent, from_=0, to=100, increment=1, textvariable=None, width=84, **kw):
        super().__init__(parent, textvariable=textvariable, width=width, mono=True, **kw)
        self._lo, self._hi, self._inc, self._var = from_, to, increment, textvariable
        self.entry.bind("<Up>", lambda e: self._step(1))
        self.entry.bind("<Down>", lambda e: self._step(-1))
        self.entry.bind("<MouseWheel>", lambda e: self._step(1 if e.delta > 0 else -1))

    def _step(self, sign):
        if self._state == "disabled" or self._var is None:
            return "break"
        try:
            cur = float(self._var.get())
        except (ValueError, tk.TclError):
            cur = self._lo
        val = min(self._hi, max(self._lo, cur + sign * self._inc))
        self._var.set(str(int(val)) if float(self._inc).is_integer() else f"{val:g}")
        return "break"


class Select(_Rounded):
    """Dropdown with a rounded border and a drawn chevron; the ttk.Combobox is .cb."""

    def __init__(self, parent, textvariable=None, values=(), width=None, state="readonly", postcommand=None,
                 mono=False, **kw):
        h = px(T.H_CONTROL)
        super().__init__(parent, px(width) if width else px(160), h)
        self._state, self._focus = state, False
        self.cb = ttk.Combobox(self, textvariable=textvariable, values=list(values), state=state,
                               style="Flat.TCombobox", font=T.font(13, mono=mono), postcommand=postcommand or "")
        self._win = self.create_window(px(10), h // 2, window=self.cb, anchor="w")
        self.cb.bind("<FocusIn>", lambda e: self._setfocus(True), add="+")
        self.cb.bind("<FocusOut>", lambda e: self._setfocus(False), add="+")
        self.bind("<Button-1>", self._open)

    def _open(self, e):
        if self._state != "disabled":
            self.cb.focus_set()
            self.tk.call("ttk::combobox::Post", str(self.cb))

    def _setfocus(self, v):
        self._focus = v
        self.redraw()

    # --- delegate the combobox API the app uses
    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw["state"]
        for k in ("state", "values", "textvariable"):
            if k in kw:
                self.cb.configure(**{k: kw.pop(k)})
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)
        self.redraw()

    config = configure

    def __setitem__(self, key, value):
        self.cb[key] = value

    def __getitem__(self, key):
        return self.cb[key]

    def get(self):
        return self.cb.get()

    def current(self, *a):
        return self.cb.current(*a)

    def bind_combo(self, seq, func):
        self.cb.bind(seq, func)

    def redraw(self):
        w, h = self._wh()
        self.delete("bg")
        dis = self._state == "disabled"
        draw_round(self, w, h, px(T.R_CONTROL), T.WINDOW if dis else T.SURFACE,
                   T.ACCENT if self._focus else T.BORDER_CONTROL, 2 if self._focus else 1)
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(10, w - px(38)))
        self.coords(self._win, px(10), h // 2)
        cx, cy, a = w - px(16), h / 2, px(4)
        self.create_line(cx - a, cy - a / 2, cx, cy + a / 2, cx + a, cy - a / 2,
                         fill=T.TEXT_DISABLED if dis else T.ICON, width=max(1, px(1.5)), capstyle="round",
                         joinstyle="round", tags="bg")


class Checkbox(tk.Canvas):
    def __init__(self, parent, text="", variable=None, command=None, state="normal", wrap=0, **kw):
        super().__init__(parent, bg=_bg(parent), highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
        self._text, self._var, self._cmd, self._state, self._wrap = text, variable, command, state, px(wrap)
        self._focus = False
        self._font = T.font(13)
        self._own_var = variable is None
        if self._own_var:
            self._var = tk.BooleanVar(value=False)
        self._trace = self._var.trace_add("write", lambda *a: self._safe_redraw())
        self.bind("<ButtonRelease-1>", lambda e: self.toggle())
        self.bind("<space>", lambda e: self.toggle())
        self.bind("<FocusIn>", lambda e: self._f(True))
        self.bind("<FocusOut>", lambda e: self._f(False))
        self.bind("<Destroy>", self._on_destroy)
        self.redraw()

    def _on_destroy(self, e):
        if e.widget is self:
            try:
                self._var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def _f(self, v):
        self._focus = v
        self.redraw()

    def _safe_redraw(self):
        try:
            self.redraw()
        except tk.TclError:
            pass

    def toggle(self):
        if self._state == "disabled":
            return
        self.focus_set()
        self._var.set(not self._var.get())
        if self._cmd:
            self._cmd()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            tk.Canvas.configure(self, cursor="arrow" if self._state == "disabled" else "hand2")
        if "text" in kw:
            self._text = kw.pop("text")
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)
        self.redraw()

    config = configure

    def state(self, spec=None):
        for s in spec or ():
            if s in ("disabled", "!disabled"):
                self.configure(state="disabled" if s == "disabled" else "normal")

    def redraw(self):
        self.delete("all")
        box, gap = px(16), px(8)
        dis = self._state == "disabled"
        line = _linespace(self._font)
        t = self.create_text(box + gap, 0, text=self._text, anchor="nw", font=self._font,
                             fill=T.TEXT_DISABLED if dis else T.TEXT, width=self._wrap or 0)
        bb = self.bbox(t)
        th = (bb[3] - bb[1]) if bb else line
        tw = (bb[2] - bb[0]) if bb else 0
        h = max(box + px(2), th)
        tk.Canvas.configure(self, width=box + gap + tw + 2, height=h)
        y = (min(line, h) - box) / 2 + (h - min(line, h)) * 0 + px(1)
        on = bool(self._var.get())
        fill = (T.BORDER_CONTROL if dis else T.ACCENT) if on else (T.WINDOW if dis else T.SURFACE)
        outline = fill if on else (T.BORDER_DISABLED if dis else T.BORDER_HOVER)
        self._ph = round_image(box, box, px(4), fill, outline)
        self.create_image(0, y, image=self._ph, anchor="nw")
        if on:
            self.create_line(px(4), y + px(8.5), px(7), y + px(11.5), px(12), y + px(5), fill=T.ON_ACCENT,
                             width=max(2, px(2)), capstyle="round", joinstyle="round")
        if self._focus and not dis:
            self._ph2 = round_image(box + px(4), box + px(4), px(6), None, T.ACCENT, 2)
            self.create_image(-px(2), y - px(2), image=self._ph2, anchor="nw")


class Chip(_Rounded):
    def __init__(self, parent, text="", orange=False, **kw):
        self._text, self._orange = text, orange
        self._font = T.font(12, "medium")
        super().__init__(parent, _measure(self._font, text) + px(20), px(T.H_CHIP))

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._text = kw.pop("text")
            tk.Canvas.configure(self, width=_measure(self._font, self._text) + px(20))
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)
        self.redraw()

    config = configure

    def redraw(self):
        w, h = self._wh()
        self.delete("all")
        bg, fg = (T.ACCENT_CHIP_BG, T.ACCENT_CHIP_TEXT) if self._orange else (T.SURFACE_SUBTLE, T.TEXT_2)
        draw_round(self, w, h, h // 2, bg)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)


class FilterChip(_Rounded):
    """'Chọn nhanh' chip: label + live count; active chips use the orange variant."""

    def __init__(self, parent, text="", count=0, command=None, **kw):
        self._text, self._count, self._cmd = text, count, command
        self._active = self._hover = self._focus = False
        self._font = T.font(12, "medium")
        super().__init__(parent, self._calc(), px(T.H_SMALL), takefocus=1, cursor="hand2")
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<ButtonRelease-1>", lambda e: self.invoke())
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._ff(True))
        self.bind("<FocusOut>", lambda e: self._ff(False))

    def _calc(self):
        return px(12) + _measure(self._font, self._text) + px(8) + max(px(18), _measure(self._font, str(self._count)) + px(10)) + px(5)

    def _h(self, v):
        self._hover = v
        self.redraw()

    def _ff(self, v):
        self._focus = v
        self.redraw()

    def invoke(self):
        self.focus_set()
        if self._cmd:
            self._cmd()

    def set(self, count=None, active=None):
        if count is not None:
            self._count = count
        if active is not None:
            self._active = active
        tk.Canvas.configure(self, width=self._calc())
        self.redraw()

    def redraw(self):
        w, h = self._wh()
        self.delete("all")
        if self._active:
            fill, outline, fg, badge = T.ACCENT_CHIP_BG, T.ACCENT_CHIP_BORDER, T.ACCENT_CHIP_TEXT, T.ACCENT_CHIP_COUNT
        else:
            fill, outline, fg, badge = (T.HOVER if self._hover else T.SURFACE), T.BORDER_CONTROL, T.TEXT_2, T.SURFACE_SUBTLE
        draw_round(self, w, h, h // 2, fill, outline)
        self.create_text(px(12), h / 2, text=self._text, fill=fg, font=self._font, anchor="w")
        bw = max(px(18), _measure(self._font, str(self._count)) + px(10))
        bh = px(18)
        x1 = w - px(5)
        self._ph2 = round_image(bw, bh, bh // 2, badge)
        self.create_image(x1 - bw, (h - bh) / 2, image=self._ph2, anchor="nw")
        self.create_text(x1 - bw / 2, h / 2, text=str(self._count), fill=fg, font=T.font(11, "medium"))
        if self._focus:
            draw_round(self, w, h, h // 2, None, T.ACCENT, 2, tag="ring")


class SwatchField(_Rounded):
    """Colour picker field: rounded swatch + hex code. configure(bg=...) sets the colour."""

    def __init__(self, parent, color="#FFFFFF", command=None, **kw):
        super().__init__(parent, px(120), px(T.H_CONTROL), takefocus=1, cursor="hand2")
        self._color, self._cmd, self._focus = color, command, False
        self.bind("<ButtonRelease-1>", lambda e: self._click())
        self.bind("<Return>", lambda e: self._click())
        self.bind("<space>", lambda e: self._click())
        self.bind("<FocusIn>", lambda e: self._ff(True))
        self.bind("<FocusOut>", lambda e: self._ff(False))

    def _ff(self, v):
        self._focus = v
        self.redraw()

    def _click(self):
        self.focus_set()
        if self._cmd:
            self._cmd()

    def configure(self, cnf=None, **kw):
        c = kw.pop("bg", None)
        kw.pop("activebackground", None)
        if c:
            self._color = c
        if cnf or kw:
            tk.Canvas.configure(self, cnf, **kw)
        self.redraw()

    config = configure

    def redraw(self):
        w, h = self._wh()
        self.delete("all")
        draw_round(self, w, h, px(T.R_CONTROL), T.SURFACE, T.ACCENT if self._focus else T.BORDER_CONTROL,
                   2 if self._focus else 1)
        s = px(18)
        self._ph2 = round_image(s, s, px(5), self._color, "#B8B8B8")
        self.create_image(px(10), (h - s) / 2, image=self._ph2, anchor="nw")
        self.create_text(px(10) + s + px(8), h / 2, text=self._color.upper(), fill=T.TEXT, font=T.font(12, mono=True),
                         anchor="w")


class ProgressBar(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, height=px(T.H_PROGRESS), bg=_bg(parent), highlightthickness=0, bd=0)
        self._frac, self._pos, self._job, self._step = 0.0, 0.0, None, 16
        self.bind("<Configure>", lambda e: self.redraw())

    def _pill(self, x0, x1, color):
        h = px(T.H_PROGRESS)
        if x1 - x0 < h:
            x1 = x0 + h
        self.create_oval(x0, 0, x0 + h, h, fill=color, outline=color)
        self.create_oval(x1 - h, 0, x1, h, fill=color, outline=color)
        self.create_rectangle(x0 + h / 2, 0, x1 - h / 2, h, fill=color, outline=color)

    def redraw(self):
        self.delete("all")
        w = max(self.winfo_width(), 10)
        self._pill(0, w, T.TRACK)
        if self._job is not None:
            seg = w * 0.28
            x0 = self._pos * (w + seg) - seg
            lo, hi = max(0, x0), min(w, x0 + seg)
            if hi - lo > 1:
                self._pill(lo, hi, T.ACCENT)
        elif self._frac > 0:
            self._pill(0, w * self._frac, T.ACCENT)

    def set(self, frac):
        """Determinate mode: stops the moving segment and shows frac (0..1)."""
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._frac = max(0.0, min(1.0, frac))
        self.redraw()

    def start(self, interval=12):
        self.stop()
        self._pos = 0.0
        self._tick()

    def _tick(self):
        self._pos = (self._pos + 0.012) % 1.0
        self.redraw()
        self._job = self.after(16, self._tick)

    def stop(self):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._frac = 0.0
        self.redraw()


class TextBox(Panel):
    """Rounded multi-line text field; the real tk.Text is .text.

    autogrow=(min_lines, max_lines): the field starts at min_lines and grows with its content
    (wrapped lines and newlines) up to max_lines, then scrolls. Call fit() after programmatic edits."""

    def __init__(self, parent, height=3, fill=T.SURFACE, font=None, autogrow=None, **text_kw):
        super().__init__(parent, fill=fill, outline=T.BORDER_CONTROL, radius=T.R_CONTROL, pad=4)
        self._grow = autogrow
        self.text = tk.Text(self.body, height=autogrow[0] if autogrow else height, wrap="word", bd=0,
                            relief="flat", highlightthickness=0, bg=fill, fg=T.TEXT, font=font or T.font(14),
                            insertbackground=T.TEXT, selectbackground=T.ACCENT_CHIP_COUNT, selectforeground=T.TEXT,
                            padx=0, pady=0, spacing1=0, **text_kw)
        self.text.pack(fill="both", expand=True)
        self._job = None
        if autogrow:
            self.text.bind("<KeyRelease>", lambda e: self.fit(), add="+")
            for seq in ("<<Paste>>", "<<Cut>>", "<<Undo>>", "<<Redo>>"):
                self.text.bind(seq, lambda e: self.after_idle(self.fit), add="+")
            self.text.bind("<Configure>", lambda e: self._later(), add="+")

    def _later(self):
        if self._job is None:
            self._job = self.after_idle(self.fit)

    def fit(self):
        self._job = None
        if not self._grow or self.text.winfo_width() < 30:
            return
        lo, hi = self._grow
        n = self.text.count("1.0", "end-1c", "displaylines")
        n = (n[0] if isinstance(n, tuple) else n) or 0
        lines = max(lo, min(hi, n + 1))
        if int(self.text.cget("height")) != lines:
            self.text.configure(height=lines)


class TabPanel(Card):
    """Card with a tab bar on top. All pages stay alive in the same grid cell; switching only shows/hides
    them, so field values and variables persist. .right is a slot on the right of the tab bar."""

    def __init__(self, parent, min_height=257, on_select=None):
        super().__init__(parent, pad=0)
        b = self.body
        self.bar = tk.Frame(b, bg=T.SURFACE, height=px(44))
        self.bar.pack(fill="x")
        self.bar.pack_propagate(False)
        self.tabs_frame = tk.Frame(self.bar, bg=T.SURFACE)
        self.tabs_frame.pack(side="left", fill="y", padx=px(11))
        self.right = tk.Frame(self.bar, bg=T.SURFACE)
        self.right.pack(side="right", padx=px(11))
        tk.Frame(b, bg=T.DIVIDER, height=1).pack(fill="x")
        self.stack = tk.Frame(b, bg=T.SURFACE)
        self.stack.pack(fill="both", expand=True)
        self.stack.grid_columnconfigure(0, weight=1)
        self.stack.grid_rowconfigure(0, weight=1, minsize=px(min_height))
        self.pages, self.cells, self.current = [], [], None
        self._on_select = on_select

    def add_tab(self, title):
        """Add a tab; returns the padded frame to build the page content in."""
        idx = len(self.pages)
        page = tk.Frame(self.stack, bg=T.SURFACE)
        page.grid(row=0, column=0, sticky="nsew")
        inner = tk.Frame(page, bg=T.SURFACE)
        inner.pack(fill="both", expand=True, padx=px(11), pady=px(11))
        cell = tk.Frame(self.tabs_frame, bg=T.SURFACE, cursor="hand2", takefocus=1)
        cell.pack(side="left", fill="y", padx=(0 if idx == 0 else px(24), 0))
        lbl = tk.Label(cell, text=title, bg=T.SURFACE, font=T.font(13, "medium"), bd=0, cursor="hand2")
        lbl.pack(fill="both", expand=True)
        line = tk.Frame(cell, bg=T.SURFACE, height=px(2))
        line.pack(fill="x", side="bottom")
        for w in (cell, lbl):
            w.bind("<ButtonRelease-1>", lambda e, i=idx: self.select(i))
        cell.bind("<Left>", lambda e, i=idx: self._step(i, -1))
        cell.bind("<Right>", lambda e, i=idx: self._step(i, 1))
        cell.bind("<Return>", lambda e, i=idx: self.select(i))
        cell.bind("<space>", lambda e, i=idx: self.select(i))
        cell.bind("<FocusIn>", lambda e, l=lbl: l.configure(fg=T.ACCENT_TEXT))
        cell.bind("<FocusOut>", lambda e: self._paint())
        self.pages.append(page)
        self.cells.append((cell, lbl, line))
        if self.current is None:
            self.select(0)
        return inner

    def _step(self, i, d):
        j = (i + d) % len(self.pages)
        self.select(j)
        self.cells[j][0].focus_set()

    def select(self, i):
        self.pages[i].tkraise()            # xếp chồng + nâng lên (không ẩn/hiện: xem ghi chú ở TabView.add)
        self.current = i
        self._paint()
        if self._on_select:
            self._on_select(i)

    def _paint(self):
        for j, (cell, lbl, line) in enumerate(self.cells):
            on = j == self.current
            lbl.configure(fg=T.TEXT if on else T.TEXT_MUTED)
            line.configure(bg=T.ACCENT if on else T.SURFACE)

class LogView(Panel):
    """Monospace log on a muted rounded surface; the real tk.Text is .text."""

    def __init__(self, parent, height=8):
        super().__init__(parent, fill=T.SURFACE_MUTED, outline=T.DIVIDER, radius=T.R_CONTROL, pad=10)
        sb = ttk.Scrollbar(self.body, orient="vertical")
        self.text = tk.Text(self.body, wrap="word", height=height, state="disabled", bd=0, relief="flat",
                            highlightthickness=0, bg=T.SURFACE_MUTED, fg=T.TEXT, font=T.font(12, mono=True),
                            spacing1=3, spacing3=3, padx=0, pady=0, yscrollcommand=sb.set,
                            selectbackground=T.ACCENT_CHIP_COUNT, selectforeground=T.TEXT)
        sb.configure(command=self.text.yview)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")


class PopupMenu:
    """Small white menu that opens above/below an anchor widget; closes on outside click or Esc."""

    def __init__(self, anchor):
        self.anchor, self.items, self.top = anchor, [], None
        self._closed_at = 0.0

    def add(self, label, command, icon=""):
        self.items.append((label, command, icon))

    def add_separator(self):
        self.items.append(None)

    def toggle(self, up=True):
        if self.top is not None:
            self.close()
        elif time.monotonic() - self._closed_at > 0.25:
            self.show(up)

    def show(self, up=True):
        a = self.anchor
        top = self.top = tk.Toplevel(a)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=T.BORDER_MENU)
        body = tk.Frame(top, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        pad = tk.Frame(body, bg=T.SURFACE)
        pad.pack(fill="both", expand=True, padx=px(6), pady=px(6))
        font = T.font(13)
        width = max([_measure(font, i[0]) for i in self.items if i] + [px(160)]) + px(56)
        for it in self.items:
            if it is None:
                tk.Frame(pad, bg=T.DIVIDER, height=1).pack(fill="x", pady=px(4))
                continue
            label, cmd, icon = it
            row = tk.Frame(pad, bg=T.SURFACE, height=px(T.H_ROW), cursor="hand2")
            row.pack(fill="x")
            row.pack_propagate(False)
            ic = tk.Label(row, text=icon, bg=T.SURFACE, fg=T.ICON, font=font, width=2)
            ic.pack(side="left", padx=(px(6), 0))
            tx = tk.Label(row, text=label, bg=T.SURFACE, fg=T.TEXT, font=font, anchor="w")
            tx.pack(side="left", fill="x", expand=True, padx=(px(6), px(10)))
            for wdg in (row, ic, tx):
                wdg.bind("<Enter>", lambda e, r=row, i=ic, t=tx: [x.configure(bg=T.HOVER) for x in (r, i, t)])
                wdg.bind("<Leave>", lambda e, r=row, i=ic, t=tx: [x.configure(bg=T.SURFACE) for x in (r, i, t)])
                wdg.bind("<ButtonRelease-1>", lambda e, c=cmd: self._pick(c))
        top.update_idletasks()
        w, h = max(width, top.winfo_reqwidth()), top.winfo_reqheight()
        x = a.winfo_rootx()
        y = a.winfo_rooty() - h - px(6) if up else a.winfo_rooty() + a.winfo_height() + px(6)
        sw = a.winfo_screenwidth()
        top.geometry(f"{w}x{h}+{max(0, min(x, sw - w))}+{max(0, y)}")
        top.deiconify()
        top.lift()
        top.focus_force()
        top.bind("<Escape>", lambda e: self.close())
        top.bind("<FocusOut>", lambda e: self.top and self.top.after(60, self._maybe_close))

    def _maybe_close(self):
        if self.top is not None and self.top.focus_displayof() is None:
            self.close()

    def _pick(self, cmd):
        self.close()
        cmd()

    def close(self):
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None
            self._closed_at = time.monotonic()


class ScrollPage(tk.Frame):
    """Vertical scroll container built from plain frames and place().

    .inner keeps its natural height but stretches to fill the window. Unlike a canvas with an embedded
    window, resizing the viewport does not touch .inner, and its width/height are only updated once a
    burst of <Configure> events (window drag) pauses, so dragging the window stays cheap."""

    DELAY_MS = 100
    POLL_MS = 400
    STEP = 48

    def __init__(self, parent, bg=T.WINDOW):
        super().__init__(parent, bg=bg)
        self.vp = tk.Frame(self, bg=bg)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.vp.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.vp, bg=bg)
        self.inner.place(x=0, y=0, width=1, height=1)
        self._sb_on = False
        self._job = None
        self._last = None
        self._off = 0
        self._h = 1
        self._view = 1
        self.vp.bind("<Configure>", self._fit)
        self.bind("<<TabShown>>", self._shown)
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.after(self.POLL_MS, self._poll)

    def _poll(self):
        """Content height changes (widgets shown/hidden) do not emit events on a placed frame: check cheaply."""
        try:
            if self.winfo_ismapped() and self.inner.winfo_reqheight() != (self._last or (0, 0, 0))[2]:
                self._fit()
            self.after(self.POLL_MS, self._poll)
        except tk.TclError:
            pass

    def _shown(self, e=None):
        """Trang vừa được chuyển tới: bố trí lại ngay, không bỏ qua dù kích thước không đổi (macOS có thể không vẽ lại
        trang vừa hiện lại nếu không được đặt lại vị trí)."""
        self._last = None
        self._fit()

    def _fit(self, e=None):
        if self._last is None:          # first display: lay out at once, no blank flash
            self.after_idle(self._apply)
            return
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(self.DELAY_MS, self._apply)

    def _apply(self):
        self._job = None
        w, h = self.vp.winfo_width(), self.vp.winfo_height()
        req = self.inner.winfo_reqheight()
        if h <= 1:
            return
        need = req > h
        if need != self._sb_on:
            self._sb_on = need
            if need:
                self.sb.pack(side="right", fill="y")
            else:
                self.sb.pack_forget()
                self._off = 0
        if (w, h, req) != self._last:
            self._last = (w, h, req)
            self._h, self._view = max(h, req), h
            self._off = max(0, min(self._off, self._h - h))
            self.inner.place_configure(x=0, y=-self._off, width=w, height=self._h)
            self._sync()

    def _sync(self):
        total = max(1, self._h)
        self.sb.set(self._off / total, min(1.0, (self._off + self._view) / total))

    def _yview(self, *args):
        if args[0] == "moveto":
            off = float(args[1]) * self._h
        else:
            n = int(args[1])
            off = self._off + n * (self.STEP if args[2] == "units" else self._view * 0.9)
        self._off = max(0, min(int(off), self._h - self._view))
        self.inner.place_configure(y=-self._off)
        self._sync()

    def _wheel(self, e):
        if not self._sb_on or not str(e.widget).startswith(str(self)):
            return
        if e.widget.winfo_class() in ("Text", "Listbox", "Treeview"):
            return
        self._yview("scroll", -1 if e.delta > 0 else 1, "units")

    def yview_moveto(self, frac):
        self._yview("moveto", frac)


class TabView(tk.Frame):
    """Custom tab bar (labels with a 2px orange underline) above a stack of pages."""

    def __init__(self, parent, brand=("SubTrans", "Dịch hardsub sang tiếng Việt")):
        super().__init__(parent, bg=T.WINDOW)
        self.bar = tk.Frame(self, bg=T.SURFACE, height=px(T.H_TABBAR))
        self.bar.pack(fill="x")
        self.bar.pack_propagate(False)
        tk.Frame(self, bg=T.BORDER_CARD, height=1).pack(fill="x")
        self.content = tk.Frame(self, bg=T.WINDOW)
        self.content.pack(fill="both", expand=True)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages, self.tabs_, self.current = [], [], None
        self._mark(brand)

    def _mark(self, brand):
        box = tk.Frame(self.bar, bg=T.SURFACE)
        box.pack(side="left", padx=(px(24), px(28)))
        cv = tk.Canvas(box, width=px(20), height=px(20), bg=T.SURFACE, highlightthickness=0, bd=0)
        cv.pack(side="left")
        self._mark_ph = round_image(px(20), px(20), px(6), T.ACCENT)
        cv.create_image(0, 0, image=self._mark_ph, anchor="nw")
        for x0, x1, y in ((4, 16, 6), (6.5, 13.5, 11.5)):
            cv.create_rectangle(px(x0), px(y), px(x1), px(y + 2), fill=T.ON_ACCENT, outline=T.ON_ACCENT)
        Label(box, brand[0], kind="h").pack(side="left", padx=(px(10), 0))

    def add(self, page, text):
        # Mọi trang xếp chồng trong cùng một ô lưới; chuyển tab bằng tkraise() thay vì ẩn/hiện (grid_remove/grid).
        # Cách ẩn/hiện làm trang bị trắng khi quay lại trên macOS (Tk Aqua không vẽ lại các widget con đặt bằng place()).
        page.grid(row=0, column=0, sticky="nsew", in_=self.content)
        cell = tk.Frame(self.bar, bg=T.SURFACE, cursor="hand2", takefocus=1)
        cell.pack(side="left", fill="y", padx=(0, px(28)))
        lbl = tk.Label(cell, text=text, bg=T.SURFACE, font=T.font(13, "medium"), bd=0)
        lbl.pack(fill="both", expand=True)
        line = tk.Frame(cell, bg=T.SURFACE, height=px(2))
        line.pack(fill="x", side="bottom")
        for w in (cell, lbl):
            w.bind("<ButtonRelease-1>", lambda e, p=page: self.select(p))
        cell.bind("<Return>", lambda e, p=page: self.select(p))
        cell.bind("<space>", lambda e, p=page: self.select(p))
        cell.bind("<FocusIn>", lambda e, l=lbl: l.configure(fg=T.ACCENT_TEXT))
        cell.bind("<FocusOut>", lambda e, p=page: self._paint())
        self.pages.append(page)
        self.tabs_.append((cell, lbl, line))
        if self.current is None:
            self.select(page)

    def tabs(self):
        return list(self.pages)

    def select(self, page):
        if isinstance(page, int):
            page = self.pages[page]
        page.tkraise()
        self.current = page
        self._paint()
        page.event_generate("<<TabShown>>")
        page.update_idletasks()

    def _paint(self):
        for p, (cell, lbl, line) in zip(self.pages, self.tabs_):
            on = p is self.current
            lbl.configure(fg=T.TEXT if on else T.TEXT_MUTED)
            line.configure(bg=T.ACCENT if on else T.SURFACE)










