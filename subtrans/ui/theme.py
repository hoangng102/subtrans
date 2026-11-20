"""Design tokens for the SubTrans UI (see design/SUBTRANS_DESIGN.md).

Every colour, size and font used by the interface comes from this module.
Sizes are written for 100% DPI and scaled with px().
"""
import ctypes
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from .. import sysdeps

# ---------------------------------------------------------------- colours
WINDOW = "#F5F5F5"
SURFACE = "#FFFFFF"
SURFACE_MUTED = "#FAFAFA"
SURFACE_SUBTLE = "#F0F0F0"
HOVER = "#F5F5F5"
HOVER_GHOST = "#EDEDED"
BORDER_CARD = "#E6E6E6"
BORDER_CONTROL = "#D9D9D9"
BORDER_HOVER = "#C4C4C4"
BORDER_DISABLED = "#EBEBEB"
DIVIDER = "#EFEFEF"
ROW_BORDER = "#F0F0F0"
BORDER_MENU = "#E0E0E0"

TEXT = "#171717"
TEXT_2 = "#404040"
TEXT_LABEL = "#525252"
TEXT_MUTED = "#6B6B6B"
TEXT_EMPTY = "#8A8A8A"
TEXT_DISABLED = "#A3A3A3"
ICON = "#737373"

ACCENT = "#F97316"
ACCENT_HOVER = "#FB8A3C"
ON_ACCENT = "#1A0A00"
ACCENT_TEXT = "#C2410C"
ACCENT_TINT = "#FFF4EC"
ACCENT_CHIP_BG = "#FFF1E6"
ACCENT_CHIP_TEXT = "#9A3412"
ACCENT_CHIP_BORDER = "#FDBA8C"
ACCENT_CHIP_COUNT = "#FFDDC2"

WARN_ROW = "#FEF6D8"        # table rows that need attention (empty translation, overlap, too short)
DANGER_TEXT = "#B00020"
PREVIEW_BG = "#2B2B2B"
TRACK = "#EAEAEA"

# ---------------------------------------------------------------- sizes (100% DPI)
H_CONTROL = 32
H_SMALL = 28
H_CHIP = 24
H_TABBAR = 45
H_ROW = 34
H_HEADER = 30
H_PROGRESS = 6
R_CARD = 12
R_CONTROL = 8
R_SMALL = 6
PAD_CARD = 16
GAP = 12

# ---------------------------------------------------------------- fonts
FONT_DIR = sysdeps.resource_dir() / "assets" / "fonts"
_FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "JetBrainsMono-Regular.ttf")
_scale = 1.0
_family, CJK_FAMILY = sysdeps.default_font_family()


def enable_dpi():
    """Make the process DPI aware (Windows). Must run before the first Tk window is created."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def register_fonts():
    """Load the bundled Inter / JetBrains Mono for this process only (no install)."""
    if sys.platform != "win32":
        return
    for name in _FONT_FILES:
        p = FONT_DIR / name
        if p.is_file():
            try:
                ctypes.windll.gdi32.AddFontResourceExW(str(p), 0x10, 0)   # FR_PRIVATE
            except (AttributeError, OSError):
                pass


def px(n):
    """Scale a 100%-DPI pixel size to the current screen."""
    return max(1, int(round(n * _scale))) if n else 0


def font(size=13, weight="regular", mono=False):
    """Tk font tuple; negative size = pixels so the design's px sizes carry over."""
    return (_family["mono" if mono else weight], -px(size))


def init(root):
    """Detect scale and fonts, configure named Tk fonts and ttk styles. Call once after Tk() exists."""
    global _scale
    try:
        _scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        _scale = 1.0
    have = set(tkfont.families(root))
    for key, fam in (("regular", "Inter"), ("medium", "Inter Medium"), ("semibold", "Inter SemiBold"),
                     ("mono", "JetBrains Mono")):
        if fam in have:
            _family[key] = fam
    if _family["semibold"] not in have:
        _family["semibold"] = _family["medium"]
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=_family["regular"], size=-px(13))
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(family=_family["mono"], size=-px(12))
    except tk.TclError:
        pass
    root.configure(bg=WINDOW)
    root.option_add("*TCombobox*Listbox.font", font(13))
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_TINT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*Menu.font", font(13))
    _styles(root)


def _styles(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", font=font(13), background=WINDOW, foreground=TEXT)

    # --- table
    s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=px(H_ROW),
                borderwidth=0, relief="flat", font=font(13))
    s.configure("Treeview.Heading", background=SURFACE_MUTED, foreground=TEXT_LABEL, relief="flat",
                borderwidth=0, padding=(px(8), px(5)), font=font(12, "medium"))
    s.map("Treeview.Heading", background=[("active", SURFACE_SUBTLE)])
    s.map("Treeview", background=[("selected", ACCENT_TINT)], foreground=[("selected", TEXT)])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # --- scrollbars
    for orient in ("Vertical", "Horizontal"):
        s.configure(f"{orient}.TScrollbar", background=BORDER_CONTROL, troughcolor=SURFACE, bordercolor=SURFACE,
                    lightcolor=BORDER_CONTROL, darkcolor=BORDER_CONTROL, arrowcolor=SURFACE, relief="flat",
                    gripcount=0, arrowsize=px(10))
        s.map(f"{orient}.TScrollbar", background=[("active", BORDER_HOVER), ("pressed", BORDER_HOVER)])
        s.layout(f"{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {"sticky": "nswe", "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])

    # --- combobox without its own border/arrow (drawn by ui.widgets.Select)
    s.layout("Flat.TCombobox", [("Combobox.padding", {"sticky": "nswe", "children": [
        ("Combobox.textarea", {"sticky": "nswe"})]})])
    s.configure("Flat.TCombobox", padding=0, relief="flat", borderwidth=0, fieldbackground=SURFACE,
                background=SURFACE, foreground=TEXT, selectbackground=SURFACE, selectforeground=TEXT,
                font=font(13))
    s.map("Flat.TCombobox", fieldbackground=[("disabled", WINDOW), ("readonly", SURFACE)],
          background=[("disabled", WINDOW), ("readonly", SURFACE)],
          foreground=[("disabled", TEXT_DISABLED)],
          selectbackground=[("readonly", SURFACE), ("disabled", WINDOW)],
          selectforeground=[("readonly", TEXT), ("disabled", TEXT_DISABLED)])
    s.configure("Flat.TSeparator", background=DIVIDER)
