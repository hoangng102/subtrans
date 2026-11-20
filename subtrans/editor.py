"""Tab chỉnh sửa phụ đề: sửa từng dòng, thời gian, và kiểu hiển thị (font, màu, viền, nền, vị trí)."""
import copy
import io
import json
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

from . import export, importer, providers, sysdeps
from .declined import mark_declined
from .export import DEFAULT_STYLE
from .ui import theme as T
from .ui import widgets as W

# quick-select filters: key, label
QS_FILTERS = (("all", "Tất cả"), ("todo", "Chưa dịch"), ("nosrc", "Chưa có chữ gốc"), ("done", "Đã dịch"))

BG_MODES = {
    "Che cả dải sub gốc (khuyên dùng)": "strip",
    "Nền chỉ sau chữ": "text",
    "Không nền": "none",
}
BG_LABEL = {v: k for k, v in BG_MODES.items()}
FONTS = ["Arial", "Tahoma", "Segoe UI", "Times New Roman", "Verdana", "Calibri"]
FONT_FILES = {   # thường, đậm, nghiêng, đậm+nghiêng (đều hỗ trợ đủ dấu tiếng Việt)
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "times new roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
}
FONT_DIR = Path(r"C:\Windows\Fonts")
NO_WINDOW = sysdeps.NO_WINDOW
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv", ".m4v"}


# ---------- tiện ích thời gian ----------
def fmt_time(t):
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h}:{m:02}:{s:02}.{ms:03}"


def parse_time(text):
    """Nhận 'h:mm:ss.mmm', 'mm:ss.mmm' hoặc số giây."""
    parts = text.strip().replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(text)
    t = 0.0
    for p in parts:
        t = t * 60 + float(p)
    if t < 0:
        raise ValueError(text)
    return t


# ---------- vẽ xem trước (gần đúng với file .ass) ----------
def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def load_font(name, bold, italic, size):
    files = FONT_FILES.get(name.lower(), FONT_FILES["arial"])
    for fname in (files[(1 if bold else 0) + (2 if italic else 0)], files[0], "arial.ttf"):
        try:
            return ImageFont.truetype(str(FONT_DIR / fname), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_preview(frame, text, meta, st):
    w, h = frame.size
    y0, y1 = round(h * meta["crop"][0]), round(h * meta["crop"][1])
    cy = (y0 + y1) / 2 if st["pos_auto"] else h * float(st["pos_y"]) / 100
    fs = max(16, int((y1 - y0) * 0.38 * float(st["font_scale"]) / 100))
    font = load_font(st["font"], st["bold"], st["italic"], max(8, int(fs * 0.9)))
    ow, sh = int(st["outline_width"]), int(st["shadow"])
    mode = st["bg_mode"]
    bg = _rgb(st["bg_color"]) + (int(255 * int(st["bg_opacity"]) / 100),)
    text_rgb, out_rgb = _rgb(st["text_color"]), _rgb(st["outline_color"])

    base = frame.convert("RGBA")
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    if mode == "strip":
        d.rectangle([0, y0, w, y1], fill=bg)
    lines = text.split("\n") if text else []
    top = cy - len(lines) * fs / 2
    if lines and mode == "text":
        bw = max(d.textlength(line, font=font) for line in lines)
        pad = max(4, ow + 3)
        d.rectangle([w / 2 - bw / 2 - pad, top - pad / 2, w / 2 + bw / 2 + pad,
                     top + len(lines) * fs + pad / 2], fill=bg)
    for i, line in enumerate(lines):
        y = top + fs * (i + 0.5)
        if sh:
            d.text((w / 2 + sh, y + sh), line, font=font, fill=(0, 0, 0, 200), anchor="mm",
                   stroke_width=ow if mode != "text" else 0, stroke_fill=(0, 0, 0, 200))
        d.text((w / 2, y), line, font=font, fill=text_rgb + (255,), anchor="mm",
               stroke_width=ow if mode != "text" else 0, stroke_fill=out_rgb + (255,))
    return Image.alpha_composite(base, ov).convert("RGB")


def copy_image_to_clipboard(owner, img):
    """Đặt ảnh lên clipboard hệ thống (dán được vào Paint/Word/trình duyệt, Preview...)."""
    sysdeps.copy_image(owner, img)


def grab_frame(video, t):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", video, "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, creationflags=NO_WINDOW)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB") if p.stdout else None


def find_vlc():
    return sysdeps.find_vlc()


def find_cues(video):
    """Trả về (đường dẫn cues.json, tag) của bản dịch cả video, nếu không có thì bản thử."""
    for suffix, tag in ((".subtrans", ""), (".subtrans_test", "_test")):
        p = Path(video).with_suffix(suffix) / "cues.json"
        if p.is_file():
            return p, tag
    return None, ""


class ImportDialog(tk.Toplevel):
    """Hộp thoại nhập phụ đề: chọn cách ghép, xem trước kết quả rồi mới áp dụng."""

    def __init__(self, parent, name, entries, cues):
        super().__init__(parent)
        self.title("Nhập phụ đề đã dịch")
        self.configure(bg=T.WINDOW)
        self.transient(parent.winfo_toplevel())
        self.entries, self.cues, self.result = entries, cues, None
        timed = all(e["start"] is not None for e in entries)
        self.v_mode = tk.StringVar(value="time" if timed else "order")
        self.v_over = tk.BooleanVar(value=False)
        self.v_new = tk.BooleanVar(value=False)

        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"File: {name}  ({len(entries)} dòng)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        box = ttk.LabelFrame(f, text="Cách ghép vào các dòng phụ đề của video", padding=6)
        box.pack(fill="x", pady=(6, 4))
        r1 = ttk.Radiobutton(box, text="Theo thời gian (khuyên dùng): dòng nào trùng khoảng thời gian thì ghép vào",
                             variable=self.v_mode, value="time")
        r1.pack(anchor="w")
        if not timed:
            r1.state(["disabled"])
        ttk.Radiobutton(box, text="Theo thứ tự dòng: file có đúng bằng số dòng đang trống (hoặc bằng tổng số dòng)",
                        variable=self.v_mode, value="order").pack(anchor="w")
        opt = ttk.LabelFrame(f, text="Tuỳ chọn", padding=6)
        opt.pack(fill="x", pady=4)
        ttk.Checkbutton(opt, text="Ghi đè cả những dòng đã có bản dịch (mặc định: chỉ điền dòng đang trống)",
                        variable=self.v_over).pack(anchor="w")
        self.c_new = ttk.Checkbutton(opt, text="Dòng trong file không khớp dòng nào: thêm thành dòng phụ đề mới",
                                     variable=self.v_new)
        self.c_new.pack(anchor="w")
        self.summary = ttk.Label(f, justify="left", wraplength=760)
        self.summary.pack(anchor="w", pady=(6, 2))
        self.sample = tk.Text(f, width=100, height=9, font=("Segoe UI", 9), state="disabled", bg="#f6f6f6")
        self.sample.pack(fill="x")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 0))
        self.b_apply = ttk.Button(bar, text="Áp dụng", command=self._ok)
        self.b_apply.pack(side="right")
        ttk.Button(bar, text="Hủy", command=self.destroy).pack(side="right", padx=6)
        for v in (self.v_mode, self.v_over, self.v_new):
            v.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def plan(self):
        return importer.make_plan(self.cues, self.entries, self.v_mode.get(), self.v_over.get(), self.v_new.get())

    def refresh(self):
        p = self.plan()
        self.c_new.state(["!disabled" if self.v_mode.get() == "time" else "disabled"])
        self.sample.configure(state="normal")
        self.sample.delete("1.0", "end")
        if p["error"]:
            self.summary.configure(text=p["error"], foreground="#b00020")
            self.b_apply.state(["disabled"])
        else:
            s = p["stats"]
            todo = s["fill"] + s["overwrite"] + (s["unmatched"] if self.v_new.get() and p["mode"] == "time" else 0)
            self.summary.configure(
                foreground="#000",
                text=f"Ghép được {len(p['actions'])}/{s['entries']} dòng của file. Sẽ điền {s['fill']} dòng đang trống"
                     f", ghi đè {s['overwrite']} dòng, giữ nguyên {s['keep']} dòng đã có bản dịch"
                     f" ({s['same']} dòng giống hệt). Không ghép được: {s['unmatched']} dòng của file.")
            self.b_apply.state(["!disabled" if todo else "disabled"])
            shown = 0
            for a in p["actions"]:
                if a["kind"] in ("fill", "overwrite") and shown < 8:
                    c = self.cues[a["cue"]]
                    old = " ".join((c.get("src") or "").split())[:28]
                    self.sample.insert("end", f"{fmt_time(c['start'])}  {old}  →  {' / '.join(a['text'].splitlines())}\n")
                    shown += 1
        self.sample.configure(state="disabled")

    def _ok(self):
        self.result = self.plan()
        self.destroy()

    def run(self):
        self.grab_set()
        self.wait_window()
        return self.result


class EditorTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.WINDOW)
        self.app = app
        self.qs_active = None      # active quick-select filter key
        self._qs_expect = None     # selection set made by a filter click (to tell it from manual selection)
        self.data = None
        self.cues = []
        self.path = None
        self.tag = ""
        self.video = None
        self.cur = None
        self.undo = []
        self.dirty = False
        self.frames = {}
        self._photo = self._photo_src = None
        self._orig_path = None     # ảnh sub gốc của dòng đang chọn (file trong thư mục frames)
        self._prev_full = None     # khung hình đã vẽ phụ đề, kích thước đầy đủ
        self._after = None
        self._loading = False
        self._build()
        self._register_dnd(self)

    # ------------------------------------------------------------ giao diện
    def _build(self):
        app = self.app
        v = app.vars
        px, gap = T.px, T.px(T.GAP)

        # --- sticky export card: packed first so it stays at the bottom while the page above scrolls
        xc = W.Card(self, pad=14)
        xc.pack(side="bottom", fill="x", padx=px(24), pady=(px(8), px(16)))
        xb = xc.body
        r1 = tk.Frame(xb, bg=T.SURFACE)
        r1.pack(fill="x")
        W.Label(r1, "Xuất kèm", kind="h").pack(side="left")
        W.Label(r1, "Mặc định chỉ có file .ass, đã gồm màu chữ/viền/nền", kind="hint").pack(side="left", padx=(px(10), px(20)))
        W.Checkbox(r1, ".srt (không có màu/viền/nền)", v["also_srt"]).pack(side="left", padx=(0, px(16)))
        W.Checkbox(r1, "Chữ gốc (.src.srt)", v["also_src"]).pack(side="left")
        self.l_saved = W.Label(r1, "", kind="hint", fg=T.TEXT_2, wrap=380, anchor="e", justify="right")
        self.l_saved.pack(side="right")
        r2 = tk.Frame(xb, bg=T.SURFACE)
        r2.pack(fill="x", pady=(px(12), 0))
        self.b_save = W.Button(r2, "Lưu và xuất .ass", command=lambda: self._with_spinner(self.b_save, self.save),
                               variant="primary")
        self.b_save.pack(side="left")
        self.b_vlc = W.Button(r2, "Xem trong VLC", command=lambda: self._with_spinner(self.b_vlc, self.open_vlc, 1500))
        self.b_vlc.pack(side="left", padx=px(8))
        more = W.Button(r2, "⋯", icon=True)
        more.pack(side="left")
        menu = W.PopupMenu(more)
        menu.add("Xuất chữ gốc (.srt)", self.export_src, "⤓")
        menu.add("Nhập phụ đề đã dịch…", lambda: self.import_file(), "⤒")
        menu.add("Bật bảng phụ đề tự động cho VLC…", lambda: self.winfo_toplevel().vlc_setup(), "☰")
        menu.add_separator()
        menu.add("Đọc/dịch lại dòng trống", self.fix_empty, "↻")
        more.configure(command=lambda: menu.toggle(up=True))
        W.Divider(r2, vertical=True, color=T.BORDER_CARD).pack(side="left", padx=px(12))
        self.b_ocr_local = W.Button(r2, "OCR cục bộ dòng chưa đọc được", command=lambda: self.ocr_local(),
                                    variant="ghost")
        self.b_ocr_local.pack(side="left")

        self.page = W.ScrollPage(self)
        self.page.pack(fill="both", expand=True)
        wrap = tk.Frame(self.page.inner, bg=T.WINDOW)
        wrap.pack(fill="both", expand=True, padx=px(24), pady=(px(20), px(8)))

        # --- card: video, toolbar, quick select, table
        lc = W.Card(wrap, pad=0)
        lc.pack(fill="both", expand=True, pady=(0, gap))
        lb = lc.body
        side = px(11)       # card body is inset 5px; together 16px like the other cards
        top = tk.Frame(lb, bg=T.SURFACE)
        top.pack(fill="x", padx=side, pady=(side, px(8)))
        W.Label(top, "Video", kind="label").pack(side="left")
        self.video_var = tk.StringVar()
        self.cb_video = W.Select(top, self.video_var, [], postcommand=self._fill_videos, mono=True)
        self.cb_video.pack(side="left", fill="x", expand=True, padx=px(10))
        self.cb_video.bind_combo("<<ComboboxSelected>>", lambda e: self.load_video(self.video_var.get()))
        W.Button(top, "Tải phụ đề", command=lambda: self.load_video(self.video_var.get())).pack(side="left")
        self.status = W.Label(top, "", kind="hint", fg=T.ACCENT_TEXT)
        self.status.pack(side="left", padx=px(8))

        tb = tk.Frame(lb, bg=T.SURFACE)
        tb.pack(fill="x", padx=side, pady=(0, px(8)))
        for text, cmd, var in (("+ Thêm dòng", self.add_cue, "default"), ("Xóa dòng", self.delete_cues, "default"),
                               ("Gộp với dòng sau", self.merge_next, "default"), ("Hoàn tác", self.do_undo, "ghost")):
            W.Button(tb, text, command=cmd, variant=var, small=True).pack(side="left", padx=(0, px(6)))
        W.Divider(tb, vertical=True, color=T.BORDER_CARD).pack(side="left", padx=px(4))
        W.Label(tb, "Lệch giờ (giây)", kind="label").pack(side="left", padx=(px(6), px(6)))
        self.shift_var = tk.StringVar(value="0.5")
        W.Entry(tb, self.shift_var, width=56, mono=True, small=True).pack(side="left")
        W.Button(tb, "Tất cả", command=lambda: self.shift(False), small=True).pack(side="left", padx=(px(6), 0))
        W.Button(tb, "Từ dòng chọn", command=lambda: self.shift(True), small=True).pack(side="left", padx=(px(6), 0))
        self.find_var, self.repl_var = tk.StringVar(), tk.StringVar()
        W.Button(tb, "Thay hết", command=self.replace_all, small=True).pack(side="right")
        W.Entry(tb, self.repl_var, width=84, small=True, placeholder="Thay bằng").pack(side="right", padx=px(6))
        W.Entry(tb, self.find_var, width=84, small=True, placeholder="Tìm").pack(side="right")

        # quick select (Chọn nhanh)
        qr = tk.Frame(lb, bg=T.SURFACE)
        qr.pack(fill="x", padx=side, pady=(0, px(10)))
        W.Label(qr, "Chọn nhanh", kind="label").pack(side="left", padx=(0, px(10)))
        self.qs_chips = {}
        for key, label in QS_FILTERS:
            chip = W.FilterChip(qr, label, 0, command=lambda k=key: self.qs_pick(k))
            chip.pack(side="left", padx=(0, px(8)))
            self.qs_chips[key] = chip
        self.only_var = tk.BooleanVar(value=False)
        W.Checkbox(qr, "Chỉ hiện dòng khớp", self.only_var, command=self.refresh_tree).pack(side="right")
        self.qs_div = W.Divider(qr, vertical=True, color=T.BORDER_CARD)
        self.qs_div.pack(side="right", padx=px(10))
        self.b_clear = W.Button(qr, "Bỏ chọn", command=self.qs_clear, variant="ghost", small=True)
        self.l_selcount = W.Label(qr, "Đã chọn 0 dòng", kind="label", fg=T.TEXT)
        self.l_selcount.pack(side="right", padx=(0, px(8)))

        W.Divider(lb, color=T.ROW_BORDER).pack(fill="x")
        tf = tk.Frame(lb, bg=T.SURFACE)
        tf.pack(fill="both", expand=True)
        # the edit toolbar sits below the table, right above the "Dòng đang chọn" card
        tb.pack_forget()
        tb.pack(fill="x", padx=side, pady=(px(8), side), after=tf)
        cols = ("n", "start", "end", "src", "vi")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=5, selectmode="extended")
        for c, text, wd, anchor in (("n", "#", 44, "e"), ("start", "Bắt đầu", 112, "w"), ("end", "Kết thúc", 112, "w"),
                                    ("src", "Chữ gốc", 240, "w"), ("vi", "Tiếng Việt", 420, "w")):
            self.tree.heading(c, text=text, anchor="w" if c != "n" else "e")
            self.tree.column(c, width=px(wd), anchor=anchor, stretch=(c in ("src", "vi")))
        self.tree.tag_configure("warn", background=T.WARN_ROW)
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self._build_menus()

        # --- selected line (full width, compact): fields start one line tall and grow with their content
        ec = W.Card(wrap)
        ec.pack(fill="x", pady=(0, gap))
        eb = ec.body
        hd = tk.Frame(eb, bg=T.SURFACE)
        hd.pack(fill="x")
        W.Label(hd, "Dòng đang chọn", kind="h").pack(side="left")
        self.chip_row = W.Chip(hd, "Dòng —", orange=True)
        self.chip_row.pack(side="left", padx=(px(10), 0))
        self.l_cps = W.Label(hd, "", kind="hint")
        self.l_cps.configure(font=T.font(11, mono=True))
        self.l_cps.pack(side="right")
        times = tk.Frame(eb, bg=T.SURFACE)
        times.pack(fill="x", pady=(px(12), 0))
        self.e_start, self.e_end = tk.StringVar(), tk.StringVar()
        for text, var in (("Bắt đầu", self.e_start), ("Kết thúc", self.e_end)):
            g = tk.Frame(times, bg=T.SURFACE)
            g.pack(side="left", padx=(0, px(16)))
            W.Label(g, text, kind="label").pack(side="left", padx=(0, px(8)))
            W.Entry(g, var, width=108, mono=True).pack(side="left")
            for d in ("−0.1", "+0.1"):
                W.Button(g, d, small=True, command=lambda x=var, s=d: self.nudge(x, -0.1 if s[0] == "−" else 0.1)
                         ).pack(side="left", padx=(px(6), 0))
        two = tk.Frame(eb, bg=T.SURFACE)
        two.pack(fill="x", pady=(px(12), 0))
        two.grid_columnconfigure((0, 1), weight=1, uniform="sv")
        h0 = tk.Frame(two, bg=T.SURFACE, height=px(T.H_CHIP))
        h0.grid(row=0, column=0, sticky="ew", padx=(0, px(6)))
        W.Label(h0, "Chữ gốc", kind="label").pack(side="left")
        self.b_copy_src = W.Button(h0, "⧉ Chép", variant="ghost", small=True, command=self.copy_src_button)
        self.b_copy_src.pack(side="right")
        h1 = tk.Frame(two, bg=T.SURFACE, height=px(T.H_CHIP))
        h1.grid(row=0, column=1, sticky="ew", padx=(px(6), 0))
        W.Label(h1, "Tiếng Việt", kind="label").pack(side="left")
        self.src_box = W.TextBox(two, fill=T.SURFACE_MUTED, font=(T.CJK_FAMILY, -px(15)), autogrow=(1, 4))
        self.src_box.grid(row=1, column=0, sticky="new", padx=(0, px(6)), pady=(px(4), 0))
        self.t_src = self.src_box.text
        self.t_src.configure(state="disabled", cursor="xterm")
        self.vi_box = W.TextBox(two, font=T.font(13), autogrow=(1, 4), undo=True)
        self.vi_box.grid(row=1, column=1, sticky="new", padx=(px(6), 0), pady=(px(4), 0))
        self.t_vi = self.vi_box.text
        # chữ gốc: chọn được bằng chuột, Ctrl+C và chuột phải để sao chép
        self.t_src.bind("<Button-1>", lambda e: self.t_src.focus_set())
        self.t_src.bind("<Button-3>", lambda e: self.popup(self.m_src, e))
        self.t_src.bind("<Control-a>", lambda e: (self.t_src.tag_add("sel", "1.0", "end-1c"), "break")[1])
        self.t_vi.bind("<FocusOut>", lambda e: self.commit())
        self.t_vi.bind("<Button-3>", lambda e: self.popup(self.m_vi, e))
        self.l_note = W.Label(eb, "", kind="hint", fg=T.DANGER_TEXT, wrap=900)   # shown only when it has text

        # --- row: tabbed panel (style | AI tools) + preview, same height
        mid = tk.Frame(wrap, bg=T.WINDOW)
        mid.pack(fill="x")
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_columnconfigure(1, minsize=px(400))
        mid.grid_rowconfigure(0, weight=1)

        self.chip_sel = None

        def on_tab(i):
            if self.chip_sel is not None:
                if i == 1:
                    self.chip_sel.pack(side="right")
                else:
                    self.chip_sel.pack_forget()

        panel = W.TabPanel(mid, min_height=257, on_select=on_tab)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        self.tabs = panel
        sbody = panel.add_tab("Kiểu phụ đề")
        abody = panel.add_tab("Công cụ AI cho dòng chọn")
        self.chip_sel = W.Chip(panel.right, "Đã chọn 0 dòng", orange=True)

        # style tab
        g = tk.Frame(sbody, bg=T.SURFACE)
        g.pack(fill="x")
        g.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="st")
        self.swatches = {}

        def cell(row, col, label=None, span=1):
            ph = (px(6) if col else 0, px(6) if col + span < 4 else 0)
            if label:
                W.Label(g, label, kind="label").grid(row=row, column=col, columnspan=span, sticky="w", padx=ph,
                                                     pady=(px(10) if row else 0, px(6)))
            return dict(row=row + 1, column=col, columnspan=span, sticky="ew", padx=ph)

        W.Select(g, v["font"], FONTS, state="normal").grid(**cell(0, 0, "Font"))
        W.Spinner(g, 40, 250, 10, v["font_scale"]).grid(**cell(0, 1, "Cỡ chữ (%)"))
        W.Checkbox(g, "In đậm", v["bold"]).grid(**cell(0, 2))
        W.Checkbox(g, "In nghiêng", v["italic"]).grid(**cell(0, 3))
        for col, (key, label) in enumerate((("text_color", "Màu chữ"), ("outline_color", "Màu viền"),
                                            ("bg_color", "Màu nền"))):
            sw = W.SwatchField(g, app._hex(key), command=lambda k=key: app.pick_color(k))
            sw.grid(**cell(2, col, label))
            self.swatches[key] = sw
        W.Spinner(g, 0, 100, 10, v["bg_opacity"]).grid(**cell(2, 3, "Độ đục nền (%)"))
        W.Spinner(g, 0, 10, 1, v["outline_width"]).grid(**cell(4, 0, "Độ dày viền"))
        W.Spinner(g, 0, 10, 1, v["shadow"]).grid(**cell(4, 1, "Đổ bóng"))
        W.Select(g, v["bg_mode"], list(BG_MODES)).grid(**cell(4, 2, "Kiểu nền", span=2))
        W.Divider(sbody).pack(fill="x", pady=px(12))
        pr = tk.Frame(sbody, bg=T.SURFACE)
        pr.pack(fill="x")
        W.Checkbox(pr, "Vị trí theo sub gốc", v["pos_auto"]).pack(side="left")
        W.Label(pr, "Cách đỉnh (%)", kind="label").pack(side="left", padx=(px(16), px(8)))
        self.sp_pos = W.Spinner(pr, 0, 100, 2, v["pos_y"], width=72)
        self.sp_pos.pack(side="left")
        W.Button(pr, "Đặt lại mặc định", command=self.reset_style, variant="ghost", small=True).pack(side="right")

        # AI tools tab: two columns
        cols2 = tk.Frame(abody, bg=T.SURFACE)
        cols2.pack(fill="x")
        cols2.grid_columnconfigure((0, 1), weight=1, uniform="aic")

        def ai_block(col, which, title, labels, btn_text, cmd):
            blk = tk.Frame(cols2, bg=T.SURFACE)
            blk.grid(row=0, column=col, sticky="new", padx=(0, px(12)) if col == 0 else (px(12), 0))
            W.Label(blk, title, kind="label").pack(anchor="w", pady=(0, px(6)))
            pair = tk.Frame(blk, bg=T.SURFACE)
            pair.pack(fill="x")
            pair.grid_columnconfigure(0, weight=6)
            pair.grid_columnconfigure(1, weight=4)
            W.Select(pair, v[f"{which}_provider"], labels).grid(row=0, column=0, sticky="ew", padx=(0, px(4)))
            cb = W.Select(pair, v[f"{which}_model"], [], state="normal")
            cb.grid(row=0, column=1, sticky="ew", padx=(px(4), 0))
            app.model_cb[which] = cb
            act = tk.Frame(blk, bg=T.SURFACE)
            act.pack(fill="x", pady=(px(8), 0))
            W.Button(act, "Tải danh sách model", variant="link", small=True,
                     command=lambda: app.fetch_models(which)).pack(side="left")
            b = W.Button(act, btn_text, small=True, command=cmd)
            b.pack(side="right")
            return b, blk

        self.b_retr, _ = ai_block(0, "rt", "Dịch lại bằng", list(providers.PROVIDER_OF_LABEL), "Dịch lại dòng chọn",
                                  self.retranslate_selected)
        self.b_reocr, ocr_blk = ai_block(1, "ro", "Đọc lại chữ (OCR) bằng", list(providers.OCR_PROVIDER_OF_LABEL),
                                         "Đọc lại dòng chọn", self.reocr_selected)
        self.chain_var = tk.BooleanVar(value=False)
        W.Checkbox(ocr_blk, "Dịch luôn sau khi đọc (dùng model ở khung bên trái)", self.chain_var, wrap=270
                   ).pack(anchor="w", pady=(px(10), 0))
        hint = W.Panel(abody, fill=T.WINDOW, outline=None, radius=T.R_CONTROL, pad=6)
        hint.pack(fill="x", side="bottom", pady=(px(14), 0))
        W.Label(hint.body, "Dùng “Chọn nhanh” ở bảng phụ đề để chọn hàng loạt dòng chưa dịch hoặc chưa có chữ gốc, "
                           "rồi dịch lại / đọc lại tại đây.", kind="hint", wrap=540, bg=T.WINDOW).pack(anchor="w")

        # preview: the dark box fills the height left by the tabbed panel
        pc = W.Card(mid)
        pc.grid(row=0, column=1, sticky="nsew")
        ph = tk.Frame(pc.body, bg=T.SURFACE)
        ph.pack(fill="x")
        W.Label(ph, "Xem trước", kind="h").pack(side="left")
        W.Label(ph, "Gần đúng", kind="hint").pack(side="right")
        self.l_orig = tk.Label(pc.body, text="", anchor="w", takefocus=True, highlightthickness=1, bg=T.SURFACE,
                               highlightbackground=T.BORDER_CONTROL, highlightcolor=T.ACCENT)
        self.l_orig.pack(fill="x", pady=(px(10), 0))
        pv = W.Panel(pc.body, fill=T.PREVIEW_BG, outline=None, radius=T.R_CONTROL, pad=0)
        pv.pack(fill="both", expand=True, pady=(px(8), 0))
        tk.Frame(pv.body, bg=T.PREVIEW_BG, width=1, height=px(207)).pack(side="left")      # minimum height
        self.l_prev = tk.Label(pv.body, text="Chọn một dòng để xem trước trên khung hình thật.", bg=T.PREVIEW_BG,
                               fg=T.TEXT_DISABLED, takefocus=True, highlightthickness=1,
                               highlightbackground=T.PREVIEW_BG, highlightcolor=T.ACCENT, font=T.font(12),
                               wraplength=px(320))
        self.l_prev.pack(side="left", fill="both", expand=True)
        self.m_img = tk.Menu(self, tearoff=0)
        self.m_img.add_command(label="Sao chép ảnh\tCtrl+C", command=lambda: self.copy_image(self._img_target))
        self.m_img.add_command(label="Lưu ảnh ra file...", command=lambda: self.save_image(self._img_target))
        self._img_target = "orig"
        for widget, which in ((self.l_orig, "orig"), (self.l_prev, "prev")):
            widget.bind("<Button-1>", lambda e, w=widget: w.focus_set())
            widget.bind("<Button-3>", lambda e, w=widget, k=which: self.image_menu(e, w, k))
            widget.bind("<Control-c>", lambda e, k=which: (self.copy_image(k), "break")[1])
            widget.bind("<Control-C>", lambda e, k=which: (self.copy_image(k), "break")[1])

    def _with_spinner(self, btn, fn, min_ms=600):
        """Run a short synchronous action with a spinner on its button (visible for at least min_ms)."""
        btn.set_loading(True)
        btn.update_idletasks()
        try:
            fn()
        finally:
            self.after(min_ms, lambda: btn.set_loading(False))

    # ------------------------------------------------------------ kéo thả video vào tab này
    def _register_dnd(self, widget):
        if not DND_FILES:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)
        except (AttributeError, tk.TclError):
            pass
        for child in widget.winfo_children():
            self._register_dnd(child)

    def on_drop(self, event):
        vids, subs = [], []
        for p in map(Path, self.tk.splitlist(event.data)):
            if p.is_dir():
                vids += sorted(x for x in p.iterdir() if x.suffix.lower() in VIDEO_EXT)
            elif p.suffix.lower() in VIDEO_EXT:
                vids.append(p)
            elif p.suffix.lower() in importer.SUB_EXT:
                subs.append(p)
        if subs and not vids:                     # thả file phụ đề: nhập vào video đang mở
            if self.data is None:
                self.status.configure(text="Hãy nạp một video trước khi nhập phụ đề.")
            else:
                self.import_file(str(subs[0]))
            return event.action
        if not vids:
            self.status.configure(text="Không có video trong mục vừa thả.")
            return event.action
        self.app.add_paths([str(v) for v in vids])      # cũng đưa vào hàng đợi ở tab Dịch
        self.load_video(str(vids[0]))
        if len(vids) > 1:
            self.status.configure(text=f"Đã nạp {vids[0].name}; {len(vids) - 1} video còn lại nằm trong hàng đợi.")
        return event.action

    # ------------------------------------------------------------ chuột phải, sao chép / dán
    def _build_menus(self):
        t = self.tree
        m = self.m_tree = tk.Menu(self, tearoff=0)
        m.add_command(label="Sao chép chữ gốc\tCtrl+C", command=self.copy_src)
        m.add_command(label="Sao chép bản dịch\tCtrl+Shift+C", command=self.copy_vi)
        m.add_command(label="Sao chép cả hai (gốc | Việt)", command=self.copy_both)
        m.add_command(label="Sao chép ảnh sub gốc", command=self.copy_orig_image)
        m.add_separator()
        m.add_command(label="OCR cục bộ dòng chọn (đọc chữ trực tiếp từ ảnh)", command=self.ocr_local_selected)
        m.add_command(label="Đọc lại chữ (OCR) dòng chọn bằng model đã chọn", command=self.reocr_selected)
        m.add_command(label="Dịch lại dòng chọn bằng model đã chọn", command=self.retranslate_selected)
        m.add_command(label="Dán vào bản dịch\tCtrl+V", command=self.paste_to_vi)
        m.add_separator()
        m.add_command(label="Chọn tất cả\tCtrl+A", command=self.select_all)
        s = self.m_src = tk.Menu(self, tearoff=0)
        s.add_command(label="Sao chép", command=self.copy_src_widget)
        s.add_command(label="Sao chép toàn bộ chữ gốc", command=lambda: self.copy_src_widget(everything=True))
        v = self.m_vi = tk.Menu(self, tearoff=0)
        v.add_command(label="Cắt", command=lambda: self.t_vi.event_generate("<<Cut>>"))
        v.add_command(label="Sao chép", command=lambda: self.t_vi.event_generate("<<Copy>>"))
        v.add_command(label="Dán", command=lambda: self.t_vi.event_generate("<<Paste>>"))
        v.add_separator()
        v.add_command(label="Chèn chữ gốc vào đây", command=self.insert_src_into_vi)

        t.bind("<Button-3>", self.on_tree_right_click)
        for seq in ("<Control-c>",):
            t.bind(seq, lambda e: (self.copy_src(), "break")[1])
        t.bind("<Control-C>", lambda e: (self.copy_vi(), "break")[1])
        for seq in ("<Control-v>", "<Control-V>"):
            t.bind(seq, lambda e: (self.paste_to_vi(), "break")[1])
        for seq in ("<Control-a>", "<Control-A>"):
            t.bind(seq, lambda e: (self.select_all(), "break")[1])

    def popup(self, menu, event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        self.popup(self.m_tree, event)

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _clip(self, text, what):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        rows = len(self.selected())
        self.l_saved.configure(text=f"Đã sao chép {what} ({rows} dòng).")

    def _rows_text(self, key):
        sel = self.selected()
        if len(sel) == 1:
            return self.cues[sel[0]][key]
        # nhiều dòng: mỗi dòng phụ đề thành đúng một dòng văn bản để dán ngược lại cho khớp
        return "\n".join(" ".join(self.cues[i][key].split()) for i in sel)

    def copy_src(self):
        if self.data is not None:
            self._clip(self._rows_text("src"), "chữ gốc")

    def copy_vi(self):
        if self.data is not None and self.commit():
            self._clip(self._rows_text("vi"), "bản dịch")

    def copy_both(self):
        if self.data is None or not self.commit():
            return
        rows = [f"{' '.join(self.cues[i]['src'].split())} | {' '.join(self.cues[i]['vi'].split())}"
                for i in self.selected()]
        self._clip("\n".join(rows), "gốc + bản dịch")

    # ---- đọc lại chữ (OCR) các dòng đã chọn bằng nhà cung cấp/model đã chọn (hoặc OCR cục bộ)
    # ---- Chọn nhanh: chọn hàng loạt theo tiêu chí
    @staticmethod
    def qs_match(key, c):
        src, vi = c["src"].strip(), c["vi"].strip()
        return {"all": True, "todo": bool(src) and not vi, "nosrc": not src, "done": bool(vi)}[key]

    def update_quick(self):
        """Refresh the chip counts and the selection counter (call after any change to the cues)."""
        for key, chip in self.qs_chips.items():
            chip.set(count=sum(1 for c in self.cues if self.qs_match(key, c)), active=(key == self.qs_active))
        n = len(self.tree.selection())
        self.l_selcount.configure(text=f"Đã chọn {n} dòng")
        self.chip_sel.configure(text=f"Đã chọn {n} dòng")
        if self.qs_active:
            if not self.b_clear.winfo_ismapped():
                self.b_clear.pack(side="right", padx=(T.px(8), 0), after=self.qs_div)
        else:
            self.b_clear.pack_forget()

    def qs_pick(self, key):
        """Click a chip: select every matching row; click it again to clear."""
        if self.data is None:
            return
        if self.qs_active == key:
            self.qs_clear()
            return
        rows = [str(i) for i, c in enumerate(self.cues) if self.qs_match(key, c)]
        self.qs_active = key
        self.refresh_tree()
        shown = [r for r in rows if self.tree.exists(r)]
        self._qs_expect = set(shown)
        self.tree.selection_set(shown)
        if shown:
            self.tree.see(shown[0])
        self.update_quick()
        if not rows:
            self.l_saved.configure(text="Không có dòng nào khớp.")

    def qs_clear(self):
        self.qs_active = None
        self._qs_expect = None
        self.tree.selection_set(())
        self.refresh_tree()
        self.update_quick()

    def reocr_selected(self):
        if self.data is None or not self.commit() or getattr(self, "_ro_busy", False):
            return
        sel = self.selected()
        if not sel:
            messagebox.showinfo("SubTrans", "Hãy chọn ít nhất một dòng (Ctrl/Shift + bấm, Ctrl+A chọn tất cả, "
                                            "hoặc bấm một ô trong 'Chọn nhanh').")
            return
        from . import config, localocr
        prov = self.app.provider_of("ro")
        model = self.app.vars["ro_model"].get().strip()
        frames = self.path.parent / "frames"
        targets = [i for i in sel if self.cues[i].get("image") and (frames / self.cues[i]["image"]).is_file()]
        no_img = len(sel) - len(targets)
        if not targets:
            messagebox.showinfo("SubTrans", "Các dòng đã chọn không có ảnh sub gốc để đọc lại "
                                            "(dòng thêm tay hoặc ảnh đã bị xóa).")
            return
        if prov == "local":
            name, model = providers.LOCAL_LABEL, ""
            if not localocr.available():
                messagebox.showwarning("SubTrans", "Chưa cài OCR cục bộ. Chạy: pip install rapidocr-onnxruntime")
                return
        else:
            name = providers.PROVIDERS[prov]
            if not model:
                messagebox.showwarning("SubTrans", "Hãy chọn hoặc gõ tên model.")
                return
            if not config.has_key(prov):
                if messagebox.askyesno("SubTrans", f"Chưa có khóa API cho {name}. Mở cửa sổ nhập khóa ngay?"):
                    self.app.manage_keys()
                return
        had = [i for i in targets if self.cues[i]["src"].strip()]
        msg = f"Đọc lại chữ {len(targets)} dòng bằng {name}" + (f" / {model}" if model else "") + "?"
        if had:
            msg += f"\n- {len(had)} dòng đã có chữ gốc sẽ bị thay bằng kết quả mới. Có thể Hoàn tác."
        if no_img:
            msg += f"\n- {no_img} dòng không có ảnh sẽ bị bỏ qua."
        msg += "\n- Dòng nào không đọc được hoặc bị model từ chối thì giữ nguyên như cũ."
        msg += "\n- Bản dịch hiện có không bị đổi; hãy dịch lại nếu chữ gốc thay đổi."
        if prov != "local":
            msg += "\n- Ảnh sub gốc của các dòng này được gửi tới dịch vụ đó và tính phí theo tài khoản của bạn."
        if not messagebox.askyesno("SubTrans", msg):
            return

        jobs = [{"id": self.cues[i]["id"], "image": self.cues[i]["image"]} for i in targets]
        src_lang, start_path = self.app.vars["src"].get(), self.path
        tag = "local" if prov == "local" else f"{prov}:{model}"
        self._ro_busy = True
        self.b_reocr.set_loading(True)
        self.push_undo()
        q = queue.Queue()

        def work():
            from . import llm
            usage = llm.Usage()
            try:
                if prov == "local":
                    def on_done(i, text, score):
                        q.put(("batch", {jobs[i]["id"]: text.strip()}, [jobs[i]["id"]]))

                    localocr.read_many([frames / j["image"] for j in jobs], on_done=on_done)
                else:
                    provider = providers.make(prov)
                    for k in range(0, len(jobs), 15):
                        group = jobs[k:k + 15]
                        q.put(("batch", llm.ocr_batch(provider, usage, model, src_lang, group, frames),
                               [g["id"] for g in group]))
            except SystemExit as e:
                q.put(("error", str(e)))
            except Exception as e:                      # lỗi mạng, khóa sai, model không tồn tại, ảnh hỏng...
                q.put(("error", f"Lỗi khi đọc chữ bằng {name}: {e}"))
            q.put(("done", str(usage)))

        threading.Thread(target=work, daemon=True).start()
        self.l_saved.configure(text=f"Đang đọc lại 0/{len(jobs)} dòng...")
        self._ro_poll(q, len(jobs), tag, start_path,
                      {"changed": [], "refused": 0, "empty": 0, "done": 0, "error": ""})

    def _ro_poll(self, q, total, tag, start_path, stat):
        from .declined import is_refusal_src
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "batch":
                    _, res, ids = item
                    if self.path != start_path:           # đã chuyển sang video khác: bỏ kết quả
                        continue
                    by_id = {c["id"]: c for c in self.cues}
                    for cid in ids:
                        c = by_id.get(cid)
                        text = (res.get(cid) or "").strip()
                        if c is None:
                            continue
                        if is_refusal_src(text):
                            stat["refused"] += 1
                        elif not text:
                            stat["empty"] += 1
                        else:
                            if text != c["src"].strip():
                                stat["changed"].append(cid)
                            c["src"], c["ocr"] = text, tag
                            c.pop("declined", None)
                            self.dirty = True
                    stat["done"] += len(ids)
                    self.refresh_tree()
                    if self.cur is not None and self.cur < len(self.cues):
                        self.load_fields()
                    self.l_saved.configure(text=f"Đang đọc lại {stat['done']}/{total} dòng...")
                elif item[0] == "error":
                    stat["error"] = item[1]
                else:
                    self._ro_busy = False
                    self.b_reocr.set_loading(False)
                    n = len(stat["changed"])
                    parts = [f"{n} dòng có chữ gốc mới"]
                    if stat["empty"]:
                        parts.append(f"{stat['empty']} dòng không đọc được chữ (giữ nguyên)")
                    if stat["refused"]:
                        parts.append(f"{stat['refused']} dòng bị model từ chối (giữ nguyên)")
                    text = "Đọc lại xong: " + ", ".join(parts) + f". {item[1]}"
                    if stat["error"]:
                        text = stat["error"] + " | " + text
                    elif n:
                        text += " Bấm 'Dịch lại dòng chọn' để dịch chữ mới."
                    self.l_saved.configure(text=text)
                    if n and self.chain_var.get() and not stat["error"]:
                        by_id = {c["id"]: i for i, c in enumerate(self.cues)}
                        rows = [str(by_id[c]) for c in stat["changed"] if c in by_id]
                        if rows:
                            self.tree.selection_set(rows)
                            self.retranslate_selected()      # có hộp xác nhận riêng vì tốn phí
                    return
        except queue.Empty:
            pass
        self.after(200, self._ro_poll, q, total, tag, start_path, stat)

    # ---- dịch lại các dòng đã chọn bằng nhà cung cấp/model đã chọn ở khung "Dịch lại dòng đã chọn bằng"
    def retranslate_selected(self):
        if self.data is None or not self.commit() or getattr(self, "_rt_busy", False):
            return
        sel = self.selected()
        if not sel:
            messagebox.showinfo("SubTrans", "Hãy chọn ít nhất một dòng (Ctrl/Shift + bấm, hoặc Ctrl+A chọn tất cả).")
            return
        from . import config
        prov = self.app.provider_of("rt")
        model = self.app.vars["rt_model"].get().strip()
        name = providers.PROVIDERS[prov]
        if not model:
            messagebox.showwarning("SubTrans", "Hãy chọn hoặc gõ tên model.")
            return
        if not config.has_key(prov):
            if messagebox.askyesno("SubTrans", f"Chưa có khóa API cho {name}. Mở cửa sổ nhập khóa ngay?"):
                self.app.manage_keys()
            return
        targets = [i for i in sel if self.cues[i]["src"].strip()]
        no_src = len(sel) - len(targets)
        if not targets:
            messagebox.showinfo("SubTrans", "Các dòng đã chọn chưa có chữ gốc để dịch. "
                                            "Hãy dùng 'OCR cục bộ dòng chưa đọc được' trước.")
            return
        had = [i for i in targets if self.cues[i]["vi"].strip()]
        manual = [i for i in had if self.cues[i].get("manual")]
        msg = f"Dịch lại {len(targets)} dòng bằng {name} / {model}?"
        if had:
            msg += (f"\n- {len(had)} dòng đã có bản dịch sẽ bị thay"
                    + (f" (gồm {len(manual)} dòng bạn nhập tay)" if manual else "") + ". Có thể Hoàn tác.")
        if no_src:
            msg += f"\n- {no_src} dòng không có chữ gốc sẽ bị bỏ qua."
        msg += ("\n- Dòng nào model này từ chối hoặc không trả kết quả thì giữ nguyên như cũ."
                "\n- Chữ gốc của các dòng này được gửi tới dịch vụ đó và tính phí theo tài khoản của bạn.")
        if not messagebox.askyesno("SubTrans", msg):
            return

        snapshot = [{"id": c["id"], "src": c["src"], "vi": c["vi"]} for c in self.cues]
        tset = set(targets)
        jobs = []
        for k in range(0, len(targets), 50):
            b = targets[k:k + 50]
            ctx = [snapshot[j] for j in range(max(0, b[0] - 5), b[0]) if j not in tset and snapshot[j]["vi"].strip()]
            jobs.append(([snapshot[i] for i in b], ctx))
        src_lang, video, start_path = self.app.vars["src"].get(), self.video, self.path
        self._rt_busy = True
        self.b_retr.set_loading(True)
        self.push_undo()
        q = queue.Queue()

        def work():
            from . import llm
            from .cli import load_glossary
            usage = llm.Usage()
            try:
                provider = providers.make(prov)
                glossary = load_glossary(video)
                for group, ctx in jobs:
                    got, declined = llm.translate_robust(provider, usage, model, src_lang, group, ctx, glossary)
                    q.put(("batch", got, declined, [g["id"] for g in group]))
            except SystemExit as e:
                q.put(("error", str(e)))
            except Exception as e:                      # lỗi mạng, khóa sai, model không tồn tại...
                q.put(("error", f"Lỗi khi gọi {name}: {e}"))
            q.put(("done", str(usage)))

        threading.Thread(target=work, daemon=True).start()
        self.l_saved.configure(text=f"Đang dịch lại 0/{len(targets)} dòng bằng {name} / {model}...")
        self._rt_poll(q, len(targets), f"{prov}:{model}", start_path,
                      {"changed": 0, "refused": 0, "failed": 0, "done": 0, "error": ""})

    def _rt_poll(self, q, total, tag, start_path, stat):
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "batch":
                    _, got, declined, ids = item
                    if self.path != start_path:           # đã chuyển sang video khác: bỏ kết quả
                        continue
                    by_id = {c["id"]: c for c in self.cues}
                    for cid in ids:
                        c = by_id.get(cid)
                        if c is None:
                            continue
                        if cid in got:
                            c["vi"], c["tr_model"] = got[cid], tag
                            c.pop("declined", None)
                            c.pop("manual", None)
                            stat["changed"] += 1
                            self.dirty = True
                        elif cid in declined:
                            stat["refused"] += 1
                        else:
                            stat["failed"] += 1
                    stat["done"] += len(ids)
                    self.refresh_tree()
                    if self.cur is not None and self.cur < len(self.cues):
                        self.load_fields()               # tránh việc ô bản dịch cũ ghi đè kết quả mới
                    self.l_saved.configure(text=f"Đang dịch lại {stat['done']}/{total} dòng...")
                elif item[0] == "error":
                    stat["error"] = item[1]
                else:
                    self._rt_busy = False
                    self.b_retr.set_loading(False)
                    parts = [f"{stat['changed']} dòng đã đổi"]
                    if stat["refused"]:
                        parts.append(f"{stat['refused']} dòng model từ chối (giữ nguyên)")
                    if stat["failed"]:
                        parts.append(f"{stat['failed']} dòng không có kết quả (giữ nguyên)")
                    text = "Dịch lại xong: " + ", ".join(parts) + f". {item[1]}"
                    if stat["changed"]:
                        text += " Bấm 'Lưu và xuất .ass' để ghi ra file."
                    if stat["error"]:
                        text = stat["error"] + " | " + text
                    self.l_saved.configure(text=text)
                    return
        except queue.Empty:
            pass
        self.after(200, self._rt_poll, q, total, tag, start_path, stat)

    # ---- nhập phụ đề đã dịch tay
    def import_file(self, path=None):
        if self.data is None:
            messagebox.showinfo("SubTrans", "Hãy nạp một video (đã có phụ đề) trước khi nhập.")
            return
        if not self.commit():
            return
        if path is None:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                parent=self, title="Chọn file phụ đề đã dịch",
                filetypes=[("Phụ đề", "*.srt *.ass *.ssa *.vtt *.txt"), ("Tất cả", "*.*")])
            if not path:
                return
        try:
            entries = importer.parse_file(path)
        except OSError as e:
            messagebox.showwarning("SubTrans", f"Không đọc được file: {e}")
            return
        if not entries:
            messagebox.showwarning("SubTrans", "Không tìm thấy dòng phụ đề nào trong file này.")
            return
        self._dlg = ImportDialog(self, Path(path).name, entries, self.cues)
        plan = self._dlg.run()
        if plan:
            self.apply_import(entries, plan)

    def apply_import(self, entries, plan):
        self.push_undo()
        changed, added = importer.apply_plan(self.cues, entries, plan)
        if not (changed or added):
            self.undo.pop()
            self.l_saved.configure(text="Không có dòng nào được thay đổi.")
            return
        self.dirty = True
        self.cur = None
        self.refresh_tree()
        first = next((i for i, c in enumerate(self.cues) if c.get("manual")), None)
        if first is not None:
            self.tree.selection_set(str(first))
            self.tree.see(str(first))
        self.l_saved.configure(text=f"Đã nhập: điền/ghi đè {changed} dòng, thêm mới {added} dòng. "
                                    f"Bấm 'Lưu và xuất' để tạo file phụ đề.")

    # ---- OCR cục bộ ngay trong tab: đọc chữ trực tiếp từ ảnh sub gốc
    def unread_rows(self):
        """Dòng có ảnh nhưng chưa có chữ gốc (ví dụ Claude trả về [withheld] hoặc từ chối đọc)."""
        return [i for i, c in enumerate(self.cues) if c.get("image") and not c["src"].strip()]

    def ocr_local_selected(self):
        self.ocr_local(self.selected())

    def ocr_local(self, rows=None):
        if self.data is None or not self.commit():
            return
        from . import localocr
        if not localocr.available():
            messagebox.showwarning("SubTrans", "Chưa cài OCR cục bộ. Chạy: pip install rapidocr-onnxruntime")
            return
        if getattr(self, "_ocr_busy", False):
            return
        rows = self.unread_rows() if rows is None else rows
        frames = self.path.parent / "frames"
        jobs = [(self.cues[i], frames / self.cues[i]["image"]) for i in rows
                if self.cues[i].get("image") and (frames / self.cues[i]["image"]).is_file()]
        if not jobs:
            messagebox.showinfo("SubTrans", "Không có dòng nào cần OCR cục bộ "
                                            "(không có dòng chưa đọc được, hoặc dòng chọn không có ảnh sub gốc).")
            return
        self.push_undo()
        self._ocr_busy = True
        self.b_ocr_local.set_loading(True)
        q = queue.Queue()

        def work():
            cnt = [0]

            def on_done(i, text, score):               # chạy song song; ảnh hỏng cho chữ trống
                cnt[0] += 1
                q.put((cnt[0], jobs[i][0], text.strip()))

            localocr.read_many([p for _, p in jobs], on_done=on_done)
            q.put(None)

        threading.Thread(target=work, daemon=True).start()
        self._ocr_poll(q, len(jobs), 0)

    def _ocr_poll(self, q, total, got):
        try:
            while True:
                item = q.get_nowait()
                if item is None:
                    self._ocr_busy = False
                    self.b_ocr_local.set_loading(False)
                    self.l_saved.configure(
                        text=f"OCR cục bộ xong: đọc được {got}/{total} dòng. "
                             f"Bấm 'Đọc/dịch lại dòng trống' để dịch các dòng này.")
                    if self.cur is not None and self.cur < len(self.cues):
                        self.load_fields()
                    return
                n, cue, text = item
                if text:
                    cue["src"], cue["ocr"] = text, "local"
                    cue.pop("declined", None)
                    got += 1
                    self.dirty = True
                    self.refresh_row(self.cues.index(cue))
                self.l_saved.configure(text=f"OCR cục bộ {n}/{total}...")
        except queue.Empty:
            pass
        self.after(150, self._ocr_poll, q, total, got)

    def copy_src_button(self):
        """Nút bên cạnh ô chữ gốc: chép toàn bộ chữ gốc của dòng đang chọn."""
        text = self.t_src.get("1.0", "end-1c")
        if not text.strip():
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self.b_copy_src.configure(text="✓ Đã chép")
        self.after(1200, lambda: self.b_copy_src.configure(text="⧉ Chép"))

    def copy_src_widget(self, everything=False):
        try:
            text = "" if everything else self.t_src.get("sel.first", "sel.last")
        except tk.TclError:
            text = ""
        self._clip(text or self.t_src.get("1.0", "end-1c"), "chữ gốc")

    def insert_src_into_vi(self):
        if self.cur is not None:
            self.t_vi.insert("insert", self.cues[self.cur]["src"])
            self.vi_box.fit()

    def paste_to_vi(self):
        """Dán vào bản dịch: 1 dòng chọn -> dán nguyên văn; nhiều dòng chọn -> mỗi dòng văn bản cho một dòng."""
        if self.data is None or not self.selected() or not self.commit():
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        sel = self.selected()
        if len(sel) == 1:
            new = {sel[0]: text.strip("\n")}
        else:
            lines = text.split("\n")
            while lines and not lines[-1].strip():
                lines.pop()
            if len(lines) != len(sel):
                messagebox.showwarning(
                    "SubTrans", f"Số dòng trong clipboard ({len(lines)}) khác số dòng phụ đề đang chọn ({len(sel)}).")
                return
            new = {i: line.strip() for i, line in zip(sel, lines)}
        self.push_undo()
        for i, v in new.items():
            self.cues[i]["vi"] = v
            if v.strip():
                self.cues[i].pop("declined", None)
            self.refresh_row(i)
        self.dirty = True
        if self.cur in new:
            self.load_fields()
        self.l_saved.configure(text=f"Đã dán vào {len(new)} dòng.")

    # ---- sao chép / lưu ảnh
    def _image(self, which):
        """which: 'orig' = ảnh sub gốc của dòng đang chọn (nguyên kích thước); 'prev' = khung hình có phụ đề tiếng Việt."""
        if which == "orig":
            if self._orig_path and self._orig_path.is_file():
                return Image.open(self._orig_path).convert("RGB")
            return None
        return self._prev_full

    def image_menu(self, event, widget, which):
        widget.focus_set()
        self._img_target = which
        self.popup(self.m_img, event)

    def copy_image(self, which="orig"):
        im = self._image(which)
        if im is None:
            messagebox.showinfo("SubTrans", "Dòng này không có ảnh để sao chép (dòng thêm tay hoặc chưa chọn dòng).")
            return
        try:
            copy_image_to_clipboard(self, im)
        except OSError as e:
            messagebox.showwarning("SubTrans", f"Không sao chép được ảnh: {e}")
            return
        self.l_saved.configure(text=f"Đã sao chép ảnh {im.width}×{im.height} vào clipboard.")

    def copy_orig_image(self):
        self.copy_image("orig")

    def save_image(self, which="orig"):
        from tkinter import filedialog
        im = self._image(which)
        if im is None:
            messagebox.showinfo("SubTrans", "Không có ảnh để lưu.")
            return
        n = (self.cur or 0) + 1
        name = f"{Path(self.video).stem}_{'subgoc' if which == 'orig' else 'xemtruoc'}_{n:04d}.png"
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".png", initialfile=name,
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if path:
            im.save(path)
            self.l_saved.configure(text=f"Đã lưu ảnh: {path}")

    def set_src_text(self, text):
        self.t_src.configure(state="normal")
        self.t_src.delete("1.0", "end")
        self.t_src.insert("1.0", text)
        self.t_src.configure(state="disabled")
        self.src_box.fit()

    def export_src(self):
        """Xuất phụ đề gốc (.srt) gồm mọi dòng có chữ nhận diện được, kể cả dòng mô hình không dịch."""
        if self.data is None or not self.commit():
            return
        out = sorted((c for c in self.cues if c["src"].strip()), key=lambda c: c["start"])
        if not out:
            messagebox.showinfo("SubTrans", "Chưa có chữ gốc nào để xuất.")
            return
        path = Path(self.video).with_suffix(f"{'.test' if self.tag else ''}.src.srt")
        export.write_srt(out, path, key="src")
        no_text = sum(1 for c in self.cues if not c["src"].strip())
        self.l_saved.configure(text=f"Đã xuất {len(out)} dòng chữ gốc: {path.name}"
                                    + (f" ({no_text} dòng không có chữ nhận diện)" if no_text else ""))
        self.app.write(f"\nĐã xuất chữ gốc: {path}\n")

    # ------------------------------------------------------------ nạp / lưu
    def _fill_videos(self):
        self.cb_video["values"] = self.app.videos

    def load_video(self, video):
        video = video.strip().strip('"')
        if not self.confirm_discard():
            return
        if not video or not Path(video).is_file():
            messagebox.showwarning("SubTrans", "Hãy chọn một file video hợp lệ.")
            return
        path, tag = find_cues(video)
        if not path:
            messagebox.showinfo("SubTrans", "Video này chưa có phụ đề đã tạo. Hãy chạy 'Dịch' ở tab đầu trước.")
            return
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.cues = self.data["cues"]
        for c in self.cues:
            c.setdefault("src", "")
            c.setdefault("vi", "")
        mark_declined(self.cues)
        self.path, self.tag, self.video = path, tag, video
        self.video_var.set(video)
        self.undo.clear()
        self.dirty = False
        self.cur = None
        self.frames.clear()
        self.status.configure(text="(bản thử đoạn ngắn)" if tag else "")
        self.l_saved.configure(text="")
        self.qs_active = None
        self.refresh_tree()
        self.on_style_change()
        if self.cues:
            self.tree.selection_set("0")

    def confirm_discard(self):
        if self.dirty:
            return messagebox.askyesno("SubTrans", "Có thay đổi chưa lưu. Bỏ qua và tiếp tục?")
        return True

    def save(self):
        if not self.data or not self.commit():
            return False
        self.cues.sort(key=lambda c: c["start"])
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        out = [c for c in self.cues if c["vi"].strip()]
        mid = ".test" if self.tag else ""
        v = Path(self.video)
        # Chỉ một file .ass (có màu chữ/viền/nền). .srt và chữ gốc chỉ xuất khi bạn bật ô tương ứng.
        ass = v.with_suffix(f"{mid}.vi.ass")
        export.write_ass(out, ass, self.data["meta"], self.app.style_dict())
        written = [ass.name]
        if self.app.vars["also_srt"].get():
            srt = v.with_suffix(f"{mid}.vi.srt")
            export.write_srt(out, srt)
            written.append(srt.name)
        if self.app.vars["also_src"].get():
            src_out = [c for c in self.cues if c["src"].strip()]
            if src_out:
                export.write_srt(src_out, v.with_suffix(f"{mid}.src.srt"), key="src")
                written.append(f"{v.stem}{mid}.src.srt")
        self.dirty = False
        self.refresh_tree()
        self.l_saved.configure(text="Đã lưu: " + ", ".join(written))
        self.app.write(f"\nĐã lưu chỉnh sửa: {ass}\n")
        return True

    def fix_empty(self):
        """Gửi các dòng có chữ gốc nhưng chưa có tiếng Việt đi dịch lại (cần API)."""
        if not self.data:
            return
        todo = sum(1 for c in self.cues
                   if (c["src"].strip() and not c["vi"].strip() and not c.get("declined"))
                   or (c.get("declined") and not c["src"].strip() and c.get("image")))
        if not todo:
            messagebox.showinfo("SubTrans", "Không có dòng nào đang trống bản dịch.")
            return
        if not self.save():
            return
        self.l_saved.configure(text=f"Đang dịch lại {todo} dòng... xem tiến trình ở tab Dịch.")
        self.app.fix_video(self.video)

    def reload_after_job(self):
        """Nạp lại dữ liệu sau khi dịch/dịch lại xong, nếu bạn không có thay đổi chưa lưu."""
        if self.data is not None and self.video and not self.dirty and Path(self.video).is_file():
            keep = self.cur
            self.load_video(self.video)
            if keep is not None and keep < len(self.cues):
                self.tree.selection_set(str(keep))
            self.l_saved.configure(text="Đã nạp lại sau khi dịch.")

    def open_vlc(self):
        if not self.data:
            return
        if not self.save():
            return
        vlc = find_vlc()
        if not vlc:
            messagebox.showinfo("SubTrans", "Không tìm thấy VLC. Bạn mở video trong VLC rồi nạp file .ass vừa lưu.")
            return
        from . import vlcpanel
        port, pw = vlcpanel.config()
        t = self.cues[self.cur]["start"] - 2 if self.cur is not None else 0
        ass = Path(self.video).with_suffix(f"{'.test' if self.tag else ''}.vi.ass")
        subprocess.Popen([vlc, self.video, f"--sub-file={ass}", f"--start-time={max(0, t):.1f}",
                          *vlcpanel.vlc_args(port, pw)])
        # Bảng "Danh sách phụ đề" tự mở khi VLC phát video (xem vlcpanel.Watcher); mở lại ngay cả khi từng đóng.
        top = self.winfo_toplevel()
        if getattr(top, "vlc_watch", None) is None:
            top.vlc_watch = vlcpanel.Watcher(top)
        top.vlc_watch.open_now()

    # ------------------------------------------------------------ bảng
    def row_values(self, i, c):
        vi = c["vi"].replace("\n", " ⏎ ")
        src = c["src"].replace("\n", " ⏎ ")
        if c.get("declined") and not vi:
            vi = "⛔ mô hình từ chối đọc/dịch dòng này (bạn có thể tự gõ)"
        elif not vi and src.strip():
            vi = "Chưa dịch"
        if not src.strip():
            src = "(trống)"
        return (i + 1, fmt_time(c["start"]), fmt_time(c["end"]), src, vi)

    def row_tags(self, i):
        c = self.cues[i]
        bad = (not c["vi"].strip() or c["end"] - c["start"] < 0.3
               or (i + 1 < len(self.cues) and c["end"] > self.cues[i + 1]["start"] + 0.01))
        return ("warn",) if bad else ()

    def refresh_tree(self):
        keep = [int(s) for s in self.tree.selection()]
        self._loading = True
        self.tree.delete(*self.tree.get_children())
        only = self.qs_active and self.only_var.get()
        for i, c in enumerate(self.cues):
            if only and not self.qs_match(self.qs_active, c):
                continue
            self.tree.insert("", "end", iid=str(i), values=self.row_values(i, c), tags=self.row_tags(i))
        for i in keep:
            if i < len(self.cues) and self.tree.exists(str(i)):
                self.tree.selection_add(str(i))
        self._loading = False
        self.update_quick()

    def refresh_row(self, i):
        if self.tree.exists(str(i)):
            self.tree.item(str(i), values=self.row_values(i, self.cues[i]), tags=self.row_tags(i))
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.cues) and self.tree.exists(str(j)):
                self.tree.item(str(j), tags=self.row_tags(j))
        self.update_quick()

    def on_select(self, _=None):
        if self._loading:
            return
        sel = self.tree.selection()
        if self.qs_active and set(sel) != self._qs_expect:     # manual selection replaces the quick filter
            self.qs_active = None
        self.update_quick()
        new = int(sel[0]) if sel else None
        if self.cur is not None and new != self.cur and self.cur < len(self.cues):
            if not self.commit():
                self._loading = True
                self.tree.selection_set(str(self.cur))
                self._loading = False
                return
        self.cur = new
        self.chip_row.configure(text=f"Dòng {new + 1}" if new is not None else "Dòng —")
        self.load_fields()
        self.schedule_preview(immediate=True)

    def load_fields(self):
        if self.cur is None or self.cur >= len(self.cues):
            return
        c = self.cues[self.cur]
        self.e_start.set(fmt_time(c["start"]))
        self.e_end.set(fmt_time(c["end"]))
        self.t_vi.delete("1.0", "end")
        self.t_vi.insert("1.0", c["vi"])
        self.t_vi.edit_reset()
        self.vi_box.fit()
        self.set_src_text(c["src"])
        if c.get("declined") and not c["src"].strip():
            note = ("Mô hình đã từ chối đọc dòng này (chữ gốc trống). Bấm 'OCR cục bộ dòng chưa đọc được' "
                    "để đọc trực tiếp từ ảnh, hoặc tự gõ.")
        elif c.get("declined"):
            note = "Mô hình đã từ chối dịch dòng này (chữ gốc vẫn được giữ). Bạn có thể tự gõ bản dịch."
        elif c.get("ocr") == "local":
            note = "Chữ gốc dòng này được đọc bằng OCR cục bộ; nên đối chiếu với ảnh sub gốc."
        else:
            note = ""
        self.l_note.configure(text=note)
        if note and not self.l_note.winfo_ismapped():
            self.l_note.pack(anchor="w", pady=(T.px(6), 0))
        elif not note:
            self.l_note.pack_forget()
        self.update_cps()

    def update_cps(self):
        try:
            d = parse_time(self.e_end.get()) - parse_time(self.e_start.get())
        except ValueError:
            return
        n = len(self.t_vi.get("1.0", "end").replace("\n", "").strip())
        cps = n / d if d > 0 else 0
        self.l_cps.configure(text=f"{d:.2f}s • {n} ký tự • {cps:.0f} ký tự/giây" + ("  (quá nhanh)" if cps > 20 else ""))

    def nudge(self, var, delta):
        try:
            var.set(fmt_time(max(0, parse_time(var.get()) + delta)))
        except ValueError:
            return
        self.commit()
        self.update_cps()

    # ------------------------------------------------------------ chỉnh sửa dữ liệu
    def push_undo(self):
        self.undo.append(copy.deepcopy(self.cues))
        del self.undo[:-50]

    def commit(self):
        i = self.cur
        if self.data is None or i is None or i >= len(self.cues):
            return True
        c = self.cues[i]
        try:
            s, e = parse_time(self.e_start.get()), parse_time(self.e_end.get())
        except ValueError:
            messagebox.showwarning("SubTrans", "Thời gian không hợp lệ. Dùng dạng 0:01:23.500 hoặc số giây.")
            return False
        if e <= s:
            messagebox.showwarning("SubTrans", "Thời gian kết thúc phải sau thời gian bắt đầu.")
            return False
        text = self.t_vi.get("1.0", "end").strip("\n")
        if (round(s, 3), round(e, 3), text) != (c["start"], c["end"], c["vi"]):
            self.push_undo()
            c.update(start=round(s, 3), end=round(e, 3), vi=text)
            if text.strip():
                c.pop("declined", None)
            self.dirty = True
            self.refresh_row(i)
        self.update_cps()
        return True

    def selected(self):
        return sorted(int(s) for s in self.tree.selection())

    def _reselect(self, idx):
        self.refresh_tree()
        self.cur = None
        if self.cues:
            idx = max(0, min(idx, len(self.cues) - 1))
            self.tree.selection_set(str(idx))
            self.tree.see(str(idx))

    def add_cue(self):
        if self.data is None or not self.commit():
            return
        self.push_undo()
        i = (self.cur if self.cur is not None else len(self.cues) - 1)
        start = self.cues[i]["end"] if self.cues else 0.0
        nid = max([c.get("id", 0) for c in self.cues] + [-1]) + 1
        self.cues.insert(i + 1, {"id": nid, "start": round(start, 3), "end": round(start + 2, 3),
                                 "image": None, "src": "", "vi": ""})
        self.dirty = True
        self._reselect(i + 1)

    def delete_cues(self):
        sel = self.selected()
        if not sel or not self.commit():
            return
        self.push_undo()
        for i in reversed(sel):
            del self.cues[i]
        self.dirty = True
        self._reselect(sel[0])

    def merge_next(self):
        i = self.cur
        if i is None or i + 1 >= len(self.cues) or not self.commit():
            return
        self.push_undo()
        a, b = self.cues[i], self.cues[i + 1]
        a["end"] = b["end"]
        a["vi"] = (a["vi"].rstrip() + "\n" + b["vi"].lstrip()).strip("\n")
        a["src"] = (a["src"] + "\n" + b["src"]).strip("\n")
        del self.cues[i + 1]
        self.dirty = True
        self._reselect(i)

    def shift(self, from_selected):
        if self.data is None or not self.commit():
            return
        try:
            d = float(self.shift_var.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("SubTrans", "Số giây lệch không hợp lệ (vd 0.5 hoặc -1.2).")
            return
        start = (self.cur or 0) if from_selected else 0
        self.push_undo()
        for c in self.cues[start:]:
            c["start"] = round(max(0, c["start"] + d), 3)
            c["end"] = round(max(c["start"] + 0.1, c["end"] + d), 3)
        self.dirty = True
        keep = self.cur
        self._reselect(keep or 0)

    def replace_all(self):
        f = self.find_var.get()
        if self.data is None or not f or not self.commit():
            return
        self.push_undo()
        n = 0
        for c in self.cues:
            if f in c["vi"]:
                n += c["vi"].count(f)
                c["vi"] = c["vi"].replace(f, self.repl_var.get())
        if not n:
            self.undo.pop()
        else:
            self.dirty = True
            self._reselect(self.cur or 0)
        self.l_saved.configure(text=f"Đã thay {n} chỗ." if n else "Không tìm thấy.")

    def do_undo(self):
        if not self.undo:
            return
        self.cues[:] = self.undo.pop()
        self.dirty = True
        self._reselect(self.cur or 0)

    # ------------------------------------------------------------ kiểu + xem trước
    def reset_style(self):
        v = self.app.vars
        d = DEFAULT_STYLE
        for k in ("text_color", "outline_color", "bg_color", "font", "bold", "italic", "pos_auto"):
            v[k].set(d[k])
        for k in ("outline_width", "bg_opacity", "font_scale", "shadow", "pos_y"):
            v[k].set(str(d[k]))
        v["bg_mode"].set(BG_LABEL[d["bg_mode"]])

    def on_style_change(self):
        for key, sw in self.swatches.items():
            sw.configure(bg=self.app._hex(key), activebackground=self.app._hex(key))
        self.sp_pos.configure(state="disabled" if self.app.vars["pos_auto"].get() else "normal")
        self.schedule_preview()

    def schedule_preview(self, immediate=False):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(0 if immediate else 150, self.draw_preview)

    def draw_preview(self):
        self._after = None
        if self.data is None or self.cur is None or self.cur >= len(self.cues):
            return
        c = self.cues[self.cur]
        # ảnh sub gốc để đối chiếu khi sửa lỗi đọc chữ
        img = c.get("image")
        if img and (self.path.parent / "frames" / img).is_file():
            self._orig_path = self.path.parent / "frames" / img
            if self._photo_src is None or self._photo_src[0] != img:
                im = Image.open(self._orig_path)
                pw = T.px(350)
                im = im.resize((pw, max(1, im.height * pw // im.width)))
                self._photo_src = (img, ImageTk.PhotoImage(im))
            self.l_orig.configure(image=self._photo_src[1])
        else:
            self._orig_path = None
            self._photo_src = None
            self.l_orig.configure(image="")
        # khung hình thật + phụ đề tiếng Việt theo kiểu hiện tại
        t = round((c["start"] + c["end"]) / 2)
        key = (self.video, t)
        if key not in self.frames:
            if len(self.frames) > 8:
                self.frames.clear()
            self.frames[key] = grab_frame(self.video, t)
        frame = self.frames[key]
        if frame is None:
            self.l_prev.configure(text="Không lấy được khung hình (kiểm tra ffmpeg).", image="")
            return
        out = self._prev_full = render_preview(frame, c["vi"], self.data["meta"],
                                               export.effective_style(self.app.style_dict(), self.data["meta"]))
        pw = min(T.px(350), int(T.px(210) * out.width / out.height))     # keep the preview box short
        out = out.resize((pw, max(1, out.height * pw // out.width)))
        self._photo = ImageTk.PhotoImage(out)
        self.l_prev.configure(image=self._photo, text="", height=out.height)






