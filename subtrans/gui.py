import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import config, providers, sysdeps, vlcpanel
from .editor import BG_LABEL, BG_MODES, VIDEO_EXT, EditorTab
from .export import DEFAULT_STYLE
from .progress import Tracker, fmt_duration, parse_line
from .ui import theme as T
from .ui import widgets as W
from .ui.widgets import TabView

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
except ImportError:   # chạy được mà không có kéo thả
    DND_FILES = None
    BaseTk = tk.Tk

ROOT = config.ROOT
ROOT.mkdir(parents=True, exist_ok=True)
SETTINGS = ROOT / "settings.json"

DETECT_MODES = {
    "Theo nét chữ, mọi màu/nền (khuyên dùng)": "edge",
    "Chỉ chữ trắng": "white",
    "Chữ sáng (trắng, vàng...)": "bright",
}
DETECT_LABEL = {v: k for k, v in DETECT_MODES.items()}
OCR_ENGINES = {
    "Lai: OCR cục bộ trước, mô hình AI cho dòng khó (nhanh nhất)": "hybrid",
    "Mô hình AI ở trên (chính xác, nhanh)": "cloud",
    "OCR cục bộ (offline, không gọi mô hình nào)": "local",
}
OCR_ENGINE_LABEL = {v: k for k, v in OCR_ENGINES.items()}
SOURCES = {
    "Chữ cứng trên hình (hardsub)": "hardsub",
    "Giọng nói (video không có hardsub)": "speech",
}
SOURCE_LABEL = {v: k for k, v in SOURCES.items()}
ASR_ENGINES = {
    "Whisper trên máy (miễn phí, offline)": "local",
    "Groq (nhanh, qua mạng, cần khóa Groq)": "groq",
}
ASR_ENGINE_LABEL = {v: k for k, v in ASR_ENGINES.items()}
ASR_MODELS = {
    "small – cân bằng (~470 MB, khuyên dùng)": "small",
    "base – nhanh, kém chính xác hơn (~150 MB)": "base",
    "medium – chính xác hơn, chậm hơn (~1,5 GB)": "medium",
    "large-v3-turbo – chính xác nhất, chậm (~1,6 GB)": "large-v3-turbo",
}
ASR_MODEL_LABEL = {v: k for k, v in ASR_MODELS.items()}
TOKENS_RE = re.compile(r"Tổng tokens in=(\d+) out=(\d+)")
STYLE_KEYS = ("text_color", "outline_color", "bg_color", "outline_width", "bg_opacity", "font_scale",
              "bg_mode", "font", "bold", "italic", "shadow", "pos_auto", "pos_y")


def refresh_path():
    """Nạp lại PATH (vd ffmpeg mới cài) nếu phiên đăng nhập hiện tại chưa có."""
    sysdeps.fix_path()


def serve(srv, out):
    """Nhận đường dẫn video từ các lần mở khác (menu chuột phải, shortcut) và chuyển vào cửa sổ này."""
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(3)
            data = b""
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                out.put(json.loads(data.decode("utf-8")))
            except (OSError, ValueError):
                pass


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.ipc = queue.Queue()
        self.title("SubTrans – Dịch hardsub sang tiếng Việt")
        T.init(self)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(T.px(1120), sw - 40)}x{min(T.px(1000), sh - 90)}+{max(0, (sw - T.px(1120)) // 2)}+10")
        self.minsize(min(T.px(960), sw - 40), min(T.px(700), sh - 90))
        self.proc = None
        self.q = queue.Queue()
        self.videos = []          # đường dẫn các video trong hàng đợi
        self.status = {}          # idx -> ký hiệu trạng thái
        self.jobs = []
        self.cancelled = False
        self.cur = None
        self.kind = None
        self.tokens = [0, 0]
        self.tracker = Tracker()      # phần trăm / thời gian còn lại của bước đang chạy
        self._job_total = 0
        self._job_no = 0
        self.editor = None
        d = DEFAULT_STYLE
        self.vars = {
            "full": tk.BooleanVar(value=True),
            "src": tk.StringVar(value="zh"),
            "crop": tk.StringVar(value="0.75-1.0"),
            "detect": tk.StringVar(value=DETECT_LABEL["edge"]),
            "ocr_model": tk.StringVar(value=config.OCR_MODEL),
            "ocr_engine": tk.StringVar(value=OCR_ENGINE_LABEL["hybrid"]),
            "ocr_provider": tk.StringVar(value=providers.PROVIDERS["claude"]),
            "tr_provider": tk.StringVar(value=providers.PROVIDERS["claude"]),
            "rt_provider": tk.StringVar(value=providers.PROVIDERS["claude"]),   # tab Chỉnh sửa: dịch lại dòng chọn
            "rt_model": tk.StringVar(value=config.TRANSLATE_MODEL),
            "ro_provider": tk.StringVar(value=providers.PROVIDERS["claude"]),   # tab Chỉnh sửa: đọc lại chữ (OCR)
            "ro_model": tk.StringVar(value=config.OCR_MODEL),
            "source": tk.StringVar(value=SOURCE_LABEL["hardsub"]),
            "asr_engine": tk.StringVar(value=ASR_ENGINE_LABEL["local"]),
            "asr_model": tk.StringVar(value=ASR_MODEL_LABEL["small"]),
            "hint": tk.StringVar(),
            "vlc_auto": tk.BooleanVar(value=True),
            "vlc_asked": tk.BooleanVar(value=False),
            "ocr_fallback": tk.BooleanVar(value=True),
            "also_srt": tk.BooleanVar(value=False),
            "also_src": tk.BooleanVar(value=False),
            "start": tk.StringVar(),
            "duration": tk.StringVar(),
            "tr_model": tk.StringVar(value=config.TRANSLATE_MODEL),
            "text_color": tk.StringVar(value=d["text_color"]),
            "outline_color": tk.StringVar(value=d["outline_color"]),
            "bg_color": tk.StringVar(value=d["bg_color"]),
            "outline_width": tk.StringVar(value=str(d["outline_width"])),
            "bg_opacity": tk.StringVar(value=str(d["bg_opacity"])),
            "font_scale": tk.StringVar(value=str(d["font_scale"])),
            "bg_mode": tk.StringVar(value=BG_LABEL[d["bg_mode"]]),
            "font": tk.StringVar(value=d["font"]),
            "bold": tk.BooleanVar(value=d["bold"]),
            "italic": tk.BooleanVar(value=d["italic"]),
            "shadow": tk.StringVar(value=str(d["shadow"])),
            "pos_auto": tk.BooleanVar(value=d["pos_auto"]),
            "pos_y": tk.StringVar(value=str(d["pos_y"])),
        }
        self._load_settings()
        # Cài đặt cũ có thể chứa nhãn không còn tồn tại (đổi tên lựa chọn): đưa về mặc định.
        for key, table, default in (("source", SOURCES, SOURCE_LABEL["hardsub"]),
                                    ("asr_engine", ASR_ENGINES, ASR_ENGINE_LABEL["local"]),
                                    ("asr_model", ASR_MODELS, ASR_MODEL_LABEL["small"])):
            if self.vars[key].get() not in table:
                self.vars[key].set(default)
        if self.vars["ocr_engine"].get() not in OCR_ENGINES:
            self.vars["ocr_engine"].set(OCR_ENGINE_LABEL["hybrid"])
        for which in ("ocr", "tr", "rt", "ro"):
            valid = {"ro": providers.OCR_PROVIDER_OF_LABEL, "ocr": providers.VISION_LABEL_OF.values()}.get(
                which, providers.PROVIDER_OF_LABEL)
            if self.vars[f"{which}_provider"].get() not in valid:
                self.vars[f"{which}_provider"].set(providers.PROVIDERS["claude"])
        self.ui_q = queue.Queue()
        self.model_lists = {}
        self.model_cb = {}          # which -> combobox model ("ocr", "tr" ở tab Dịch; "rt" ở tab Chỉnh sửa)
        self._build()
        for which in ("ocr", "tr", "rt", "ro"):
            self._refresh_models(which)
            self._sync_model_state(which)
            self.vars[f"{which}_provider"].trace_add("write", lambda *_, w=which: self._on_provider_change(w))
        self.update_key_status()
        self.bind("<FocusIn>", lambda e: self.update_key_status() if e.widget is self else None)
        for k in STYLE_KEYS:
            self.vars[k].trace_add("write", lambda *_: self.editor.on_style_change())
        self.vars["full"].trace_add("write", lambda *_: self.update_full())
        self.vars["source"].trace_add("write", lambda *_: self.update_source())
        self.vars["asr_engine"].trace_add("write", lambda *_: self.update_source())
        self.update_source()
        self.update_full()
        self.editor.on_style_change()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        if not any(config.has_key(p) for p in providers.PROVIDERS):      # lần đầu: chưa có khóa nào
            self.after(600, self.manage_keys)
        self.vlc_watch = vlcpanel.Watcher(self)
        self.after(1500, self._start_vlc_watch)

    # ---- bảng danh sách phụ đề tự hiện khi VLC phát video
    def _start_vlc_watch(self):
        if not self.vars["vlc_asked"].get() and not vlcpanel.vlc_configured():
            self.vars["vlc_asked"].set(True)
            self._save_settings()
            if messagebox.askyesno(
                    "SubTrans", "Bật bảng 'Danh sách phụ đề' tự hiện khi bạn xem video bằng VLC (không cần bấm gì trong "
                    "SubTrans)?\n\nSubTrans sẽ bật giao diện web của VLC, chỉ nghe trên máy này và có mật khẩu ngẫu nhiên, "
                    "bằng cách sửa file cấu hình VLC (có sao lưu). Bạn cần đóng VLC trước khi làm.\n\n"
                    "(Có thể bật lại sau trong menu ⋯ ở tab Chỉnh sửa.)"):
                self.vlc_setup(ask_first=False)
        if self.vars["vlc_auto"].get():
            self.vlc_watch.start()

    def vlc_setup(self, ask_first=True):
        if vlcpanel.vlc_running():
            messagebox.showinfo("SubTrans", "Hãy đóng VLC trước (VLC ghi đè cấu hình khi thoát), rồi làm lại.")
            return
        ok, msg = vlcpanel.configure_vlc()
        messagebox.showinfo("SubTrans", msg) if ok or ask_first else messagebox.showwarning("SubTrans", msg)
        if ok:
            self.vars["vlc_auto"].set(True)
            self.vlc_watch.start()

    # ---- lưu / nạp cài đặt
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in self.vars and k not in ("start", "duration"):
                    try:
                        self.vars[k].set(v)
                    except tk.TclError:
                        pass
        except (OSError, ValueError):
            pass

    def _save_settings(self):
        try:
            data = {k: v.get() for k, v in self.vars.items() if k not in ("start", "duration")}
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def on_close(self):
        if self.proc and not messagebox.askyesno("SubTrans", "Đang xử lý. Thoát và dừng hẳn?"):
            return
        if not self.editor.confirm_discard():
            return
        self.cancelled = True
        self._kill()
        self._save_settings()
        self.destroy()

    # ---- giao diện
    # ---- giao diện
    def _build(self):
        self.nb = TabView(self)
        self.nb.pack(fill="both", expand=True)
        run = W.ScrollPage(self.nb.content)
        self.nb.add(run, "Dịch")
        self.editor = EditorTab(self.nb.content, self)
        self.nb.add(self.editor, "Chỉnh sửa & kiểu phụ đề")
        self._build_run(run.inner)

    def _build_run(self, f):
        px, gap = T.px, T.px(T.GAP)
        wrap = tk.Frame(f, bg=T.WINDOW)
        wrap.pack(fill="both", expand=True, padx=px(24), pady=px(20))

        # --- hàng đợi video
        qc = W.Card(wrap)
        qc.pack(fill="x", pady=(0, gap))
        head = tk.Frame(qc.body, bg=T.SURFACE)
        head.pack(fill="x")
        tl = tk.Frame(head, bg=T.SURFACE)
        tl.pack(side="left")
        W.Label(tl, "Hàng đợi video", kind="h").pack(anchor="w")
        W.Label(tl, "Kéo thả video hoặc thư mục vào đây (xử lý lần lượt)" if DND_FILES
                else "Xử lý lần lượt từng video", kind="hint").pack(anchor="w")
        qb = tk.Frame(head, bg=T.SURFACE)
        qb.pack(side="right")
        for text, cmd, var in (("Thêm video…", self.add_files, "default"), ("Thêm thư mục…", self.add_folder, "default"),
                               ("Xóa mục chọn", self.remove_selected, "ghost"), ("Xóa tất cả", self.clear_all, "ghost")):
            W.Button(qb, text, command=cmd, variant=var).pack(side="left", padx=(px(6), 0))
        dz = W.DashedPanel(qc.body, fill=T.SURFACE_MUTED, outline=T.BORDER_CONTROL, radius=10, pad=6, dash=True)
        dz.pack(fill="x", pady=(px(12), 0))
        lsb = ttk.Scrollbar(dz.body, orient="vertical")
        self.listbox = tk.Listbox(dz.body, height=3, selectmode="extended", activestyle="none", bd=0,
                                  highlightthickness=0, bg=T.SURFACE_MUTED, fg=T.TEXT, font=T.font(13),
                                  selectbackground=T.ACCENT_TINT, selectforeground=T.TEXT,
                                  yscrollcommand=lsb.set)
        lsb.configure(command=self.listbox.yview)
        self.listbox.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

        # --- hai cột: nhận dạng + mô hình AI
        cols = tk.Frame(wrap, bg=T.WINDOW)
        cols.pack(fill="x", pady=(0, gap))
        cols.grid_columnconfigure((0, 1), weight=1, uniform="cols")
        left = W.Card(cols)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, gap // 2))
        right = W.Card(cols)
        right.grid(row=0, column=1, sticky="nsew", padx=(gap // 2, 0))

        o = left.body
        o.grid_columnconfigure((0, 1), weight=1, uniform="o")
        W.Label(o, "Nhận dạng và dịch", kind="h").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(10)))
        half = ((0, px(6)), (px(6), 0))

        def lab(text, r, c=0, span=1, pady=(px(10), px(6))):
            return W.Label(o, text, kind="label").grid(row=r, column=c, columnspan=span, sticky="w",
                                                       padx=half[c] if span == 1 else 0, pady=pady)

        # Mỗi hàng của hai chế độ dùng chung vị trí 5-8; update_source() hiện/ẩn nhóm tương ứng.
        self._hs, self._sp = [], []        # widget chỉ dùng cho hardsub / chỉ dùng cho giọng nói

        def put(widget, group, **grid):
            widget.grid(**grid)
            group.append(widget)
            return widget

        lab("Nguồn phụ đề", 1, span=2, pady=(0, px(6)))
        W.Select(o, self.vars["source"], list(SOURCES)).grid(row=2, column=0, columnspan=2, sticky="ew")
        lab("Ngôn ngữ gốc", 3, 0)
        self.l_crop = W.Label(o, "Vùng sub (theo chiều cao)", kind="label")
        put(self.l_crop, self._hs, row=3, column=1, sticky="w", padx=half[1], pady=(px(10), px(6)))
        W.Select(o, self.vars["src"], ["zh", "ja", "auto"]).grid(row=4, column=0, sticky="ew", padx=half[0])
        crop_row = tk.Frame(o, bg=T.SURFACE)
        put(crop_row, self._hs, row=4, column=1, sticky="ew", padx=half[1])
        W.Button(crop_row, "Chọn trên video", command=self.pick_crop).pack(side="right", padx=(px(6), 0))
        W.Entry(crop_row, self.vars["crop"], mono=True, width=80).pack(side="left", fill="x", expand=True)

        def lab2(text, r, group):
            return put(W.Label(o, text, kind="label"), group, row=r, column=0, columnspan=2, sticky="w",
                       pady=(px(10), px(6)))

        lab2("Nhận diện sub", 5, self._hs)
        put(W.Select(o, self.vars["detect"], list(DETECT_MODES)), self._hs, row=6, column=0, columnspan=2,
            sticky="ew")
        lab2("Đọc chữ bằng", 7, self._hs)
        put(W.Select(o, self.vars["ocr_engine"], list(OCR_ENGINES)), self._hs, row=8, column=0, columnspan=2,
            sticky="ew")
        lab2("Nhận dạng giọng nói bằng", 5, self._sp)
        put(W.Select(o, self.vars["asr_engine"], list(ASR_ENGINES)), self._sp, row=6, column=0, columnspan=2,
            sticky="ew")
        self.l_asr_model = lab2("Cỡ model Whisper (chạy trên máy)", 7, self._sp)
        self.s_asr_model = put(W.Select(o, self.vars["asr_model"], list(ASR_MODELS)), self._sp, row=8, column=0,
                               columnspan=2, sticky="ew")
        W.Divider(o).grid(row=9, column=0, columnspan=2, sticky="ew", pady=px(12))
        W.Checkbox(o, "Dịch toàn bộ video", self.vars["full"]).grid(row=10, column=0, columnspan=2, sticky="w")
        self.l_start = W.Label(o, "Chỉ thử đoạn – từ giây", kind="label")
        self.l_start.grid(row=11, column=0, sticky="w", padx=half[0], pady=(px(10), px(6)))
        self.l_dur = W.Label(o, "Dài (giây)", kind="label")
        self.l_dur.grid(row=11, column=1, sticky="w", padx=half[1], pady=(px(10), px(6)))
        self.e_start = W.Entry(o, self.vars["start"], mono=True)
        self.e_start.grid(row=12, column=0, sticky="ew", padx=half[0])
        self.e_dur = W.Entry(o, self.vars["duration"], mono=True)
        self.e_dur.grid(row=12, column=1, sticky="ew", padx=half[1])
        put(W.Checkbox(o, "Ảnh mô hình không đọc được: đọc bằng OCR cục bộ (nhận diện đủ chữ)",
                       self.vars["ocr_fallback"], wrap=380), self._hs, row=13, column=0, columnspan=2, sticky="w",
            pady=(px(12), 0))
        self.l_mode = W.Label(o, "", kind="hint", fg=T.ACCENT_TEXT, wrap=400)
        self.l_mode.grid(row=14, column=0, columnspan=2, sticky="w", pady=(px(6), 0))
        put(W.Label(o, "Giọng nói được nhận dạng thành chữ rồi mới dịch. Whisper trên máy miễn phí nhưng chậm hơn "
                       "và lần đầu phải tải model (có báo trong nhật ký). Groq nhanh hơn, dùng khóa Groq của bạn "
                       "và gửi âm thanh lên dịch vụ của họ.", kind="hint", wrap=400),
            self._sp, row=15, column=0, columnspan=2, sticky="w", pady=(px(8), 0))

        W.Label(o, "Gợi ý ngữ cảnh cho bản dịch (không bắt buộc)", kind="label").grid(
            row=16, column=0, columnspan=2, sticky="w", pady=(px(12), px(6)))
        W.Entry(o, self.vars["hint"]).grid(row=17, column=0, columnspan=2, sticky="ew")
        W.Label(o, "Ví dụ: phim cổ trang; Lý Minh là sư phụ của Tiểu Vũ, xưng thầy – con; tên: 李明 = Lý Minh. "
                   "Càng cụ thể thì xưng hô và tên riêng càng đúng.", kind="hint", wrap=400).grid(
            row=18, column=0, columnspan=2, sticky="w", pady=(px(6), 0))

        W.Label(right.body, "Mô hình AI", kind="h").pack(anchor="w")
        W.Label(right.body, "Chọn nhà cung cấp và model cho từng bước", kind="hint").pack(anchor="w", pady=(0, px(6)))
        self._build_ai(right.body)

        # --- gợi ý sang tab chỉnh sửa
        W.Label(wrap, "ⓘ  Kiểu phụ đề (màu, viền, cỡ chữ, vị trí...) và việc xuất kèm .srt/chữ gốc chỉnh ở tab "
                      "'Chỉnh sửa & kiểu phụ đề'. Mặc định chỉ xuất một file .ass.", kind="hint", wrap=1000
                ).pack(fill="x", pady=(0, gap))

        # --- chạy
        rc = W.Card(wrap)
        rc.pack(fill="x", pady=(0, gap))
        btns = tk.Frame(rc.body, bg=T.SURFACE)
        btns.pack(fill="x")
        self.b_preview = W.Button(btns, "Xem trước (miễn phí)", command=lambda: self.start("preview"), num=1)
        self.b_dry = W.Button(btns, "Ước lượng", command=lambda: self.start("dry"), num=2)
        self.b_run = W.Button(btns, "Dịch", command=lambda: self.start("run"), variant="primary", num=3)
        self.b_stop = W.Button(btns, "Dừng", command=self.stop, variant="ghost", state="disabled")
        self.b_export = W.Button(btns, "Xuất lại theo kiểu hiện tại", command=lambda: self.start("export"))
        self.action_btns = (self.b_preview, self.b_dry, self.b_run, self.b_export)
        for b in (self.b_preview, self.b_dry, self.b_run, self.b_stop):
            b.pack(side="left", padx=(0, px(8)))
        self.b_export.pack(side="right")
        self.bar = W.ProgressBar(rc.body)
        self.bar.pack(fill="x", pady=(px(14), 0))
        self.l_progress = W.Label(rc.body, "", kind="hint")
        self.l_progress.pack(anchor="w", pady=(px(6), 0))

        # --- nhật ký
        lc = W.Card(wrap)
        lc.pack(fill="both", expand=True)
        lh = tk.Frame(lc.body, bg=T.SURFACE)
        lh.pack(fill="x", pady=(0, px(10)))
        W.Label(lh, "Nhật ký", kind="h").pack(side="left")
        for text, cmd in (("Mở thư mục video", self.open_folder), ("Mở ảnh xem trước", self.open_preview),
                          ("Chỉnh sửa phụ đề của video chọn", self.edit_selected)):
            W.Button(lh, text, command=cmd, variant="ghost", small=True).pack(side="right", padx=(px(4), 0))
        lv = W.LogView(lc.body, height=5)
        lv.pack(fill="both", expand=True)
        self.log = lv.text

        if DND_FILES:
            self._dnd_all(self)      # cửa sổ chính (cả thanh tab) và toàn bộ tab Dịch
            self._dnd_all(f)

        self.write(self.key_status_text() + "\nThêm một hoặc nhiều video, bấm 'Xem trước' để kiểm tra vùng sub, "
                                            "rồi bấm 'Dịch'.\n")

    # ---- chọn nhà cung cấp và model
    def _build_ai(self, box):
        px = T.px
        for which, title in (("ocr", "Đọc chữ trong ảnh"), ("tr", "Dịch sang tiếng Việt")):
            labels = list(providers.VISION_LABEL_OF.values()) if which == "ocr" else list(providers.PROVIDER_OF_LABEL)
            head = tk.Frame(box, bg=T.SURFACE)
            head.pack(fill="x", pady=(px(8), px(6)))
            if which == "ocr":
                self._ocr_block = [head]
            else:
                self._tr_head = head
            W.Label(head, title, kind="label").pack(side="left")
            W.Button(head, "Tải danh sách model", variant="link", small=True,
                     command=lambda w=which: self.fetch_models(w)).pack(side="right")
            pair = tk.Frame(box, bg=T.SURFACE)
            pair.pack(fill="x")
            pair.grid_columnconfigure((0, 1), weight=1, uniform="ai")
            W.Select(pair, self.vars[f"{which}_provider"], labels).grid(row=0, column=0, sticky="ew",
                                                                          padx=(0, px(6)))
            cb = W.Select(pair, self.vars[f"{which}_model"], [], state="normal")
            cb.grid(row=0, column=1, sticky="ew", padx=(px(6), 0))
            self.model_cb[which] = cb
            if which == "ocr":
                self._ocr_block.append(pair)
        W.Divider(box).pack(fill="x", pady=px(12))
        keys = tk.Frame(box, bg=T.SURFACE)
        keys.pack(fill="x")
        W.Button(keys, "Quản lý khóa API", command=self.manage_keys, small=True, variant="primary").pack(side="right")
        self.l_keysum = W.Label(keys, "", kind="hint", wrap=330)
        self.l_keysum.pack(side="left", fill="x", expand=True)
        self.l_keys = W.Label(box, "", kind="hint", wrap=420)
        self.l_keys.pack(anchor="w", pady=(px(6), 0))
        W.Label(box, "Mỗi nhà cung cấp tính phí riêng và có chính sách nội dung riêng. Tool không tự chuyển sang nhà "
                     "khác khi một mô hình từ chối một dòng. Bạn có thể gõ tay tên model nếu danh sách chưa có.",
                kind="hint", wrap=420).pack(anchor="w", pady=(px(6), 0))

    def provider_of(self, which):
        """'claude' | 'openai' | 'gemini', hoặc 'local' (chỉ cho mục đọc lại chữ 'ro')."""
        return {**providers.PROVIDER_OF_LABEL, providers.LOCAL_LABEL: "local"}.get(self.vars[f"{which}_provider"].get(), "claude")

    def _sync_model_state(self, which):
        """OCR cục bộ không có model để chọn nên khóa ô model."""
        if which in self.model_cb:
            self.model_cb[which].configure(state="disabled" if self.provider_of(which) == "local" else "normal")

    @staticmethod
    def _model_belongs(prov, model):
        return providers.model_belongs(prov, model)

    def _on_provider_change(self, which):
        prov = self.provider_of(which)
        self._sync_model_state(which)
        if prov == "local":
            return
        model = self.vars[f"{which}_model"]
        if not self._model_belongs(prov, model.get()):
            model.set(providers.default_model(prov, vision=which in ("ocr", "ro")))
        self._refresh_models(which)

    def _refresh_models(self, which):
        prov = self.provider_of(which)
        if prov == "local":
            self.model_cb[which]["values"] = []
            return
        values = list(self.model_lists.get(prov) or providers.SUGGESTED[prov])
        cur = self.vars[f"{which}_model"].get()
        if cur and cur not in values:
            values.insert(0, cur)
        self.model_cb[which]["values"] = values

    def fetch_models(self, which):
        prov = self.provider_of(which)
        if prov == "local":
            self._set_status(which, "OCR cục bộ không dùng model nên không có danh sách để tải.")
            return
        name = providers.PROVIDERS[prov]
        self._set_status(which, f"Đang tải danh sách model của {name}...")

        def work():
            try:
                ids, msg = providers.make(prov).list_models(), None
            except SystemExit as e:
                ids, msg = None, str(e)
            except Exception as e:                      # lỗi mạng, khóa sai...
                ids, msg = None, f"Không tải được danh sách model của {name}: {e}"
            self.ui_q.put(lambda: self._models_loaded(which, prov, name, ids, msg))

        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, which, text):
        """Dòng trạng thái nằm cạnh nơi bạn bấm: tab Chỉnh sửa cho 'rt', khung Mô hình AI cho các mục còn lại."""
        (self.editor.l_saved if which in ("rt", "ro") else self.l_keys).configure(text=text)

    def _models_loaded(self, which, prov, name, ids, msg):
        if ids:
            self.model_lists[prov] = ids
            for w in self.model_cb:
                self._refresh_models(w)
            self._set_status(which, f"Đã tải {len(ids)} model của {name}. {self.key_status_text()}")
        else:
            self._set_status(which, msg or f"{name} không trả về model nào.")

    def key_status_text(self):
        ready = [providers.PROVIDERS[p].split(" (")[0] for p in providers.PROVIDERS
                 if p not in config.NO_KEY and config.has_key(p)]
        return "Khóa API: " + (", ".join(ready) + " ✔" if ready else "chưa có khóa nào ✖")

    def update_key_status(self):
        self.l_keysum.configure(text=self.key_status_text())
        self.l_keys.configure(text="")

    def manage_keys(self):
        """Cửa sổ nhập, kiểm tra khóa API và xem hướng dẫn tự lấy khóa."""
        from .keydialog import KeyDialog
        KeyDialog(self).run()
        self.update_key_status()

    def missing_keys(self, kind):
        """Tên các nhà cung cấp cần khóa cho lệnh này mà chưa có khóa."""
        need = []
        speech = self.source_kind() == "speech"
        if kind in ("run", "fix"):
            need.append(self.provider_of("tr"))
        if kind == "run" and not speech and OCR_ENGINES.get(self.vars["ocr_engine"].get()) in ("cloud", "hybrid"):
            need.append(self.provider_of("ocr"))
        if kind in ("run", "preview") and speech and ASR_ENGINES.get(self.vars["asr_engine"].get()) == "groq":
            need.append("groq")
        out = []
        for p in need:
            if p in providers.PROVIDERS and not config.has_key(p) and providers.PROVIDERS[p] not in out:
                out.append(providers.PROVIDERS[p])
        return out

    def open_key_file(self):
        p = config.key_file()
        if not p.exists():
            p.write_text("# Mỗi dòng một khóa, dạng TÊN=giá_trị (không dấu cách, không ngoặc kép).\n"
                         "# ANTHROPIC_API_KEY=\n# OPENAI_API_KEY=\n# GEMINI_API_KEY=\n", encoding="utf-8")
        sysdeps.open_path(p)
        self.l_keys.configure(text="Thêm dòng OPENAI_API_KEY=... hoặc GEMINI_API_KEY=... rồi lưu file; "
                                   "quay lại cửa sổ này để cập nhật trạng thái.")

    def source_kind(self):
        return SOURCES.get(self.vars["source"].get(), "hardsub")

    def update_source(self):
        """Hiện các ô của nguồn phụ đề đang chọn (chữ cứng hoặc giọng nói) và ẩn các ô còn lại."""
        speech = self.source_kind() == "speech"
        for w in self._hs:
            (w.grid_remove if speech else w.grid)()
        for w in self._sp:
            (w.grid if speech else w.grid_remove)()
        local = ASR_ENGINES.get(self.vars["asr_engine"].get()) == "local"
        for w in (self.l_asr_model, self.s_asr_model):           # cỡ model chỉ có nghĩa khi chạy trên máy
            if speech and not local:
                w.grid_remove()
        head, pair = self._ocr_block                             # không đọc chữ trong ảnh khi dùng giọng nói
        head.pack_forget()
        pair.pack_forget()
        if not speech:
            head.pack(fill="x", pady=(T.px(8), T.px(6)), before=self._tr_head)
            pair.pack(fill="x", before=self._tr_head)
        self.b_preview.configure(text="Nghe thử 60 giây" if speech else "Xem trước (miễn phí)")

    def update_full(self):
        full = self.vars["full"].get()
        state = "disabled" if full else "normal"
        for w in (self.e_start, self.e_dur):
            w.configure(state=state)
        self.l_mode.configure(
            text="" if full else "Chế độ thử: chỉ xử lý đoạn đã nhập; kết quả lưu riêng thành *.test.vi.srt, "
                                 "không ảnh hưởng bản dịch cả video.")

    # ---- hàng đợi video
    def refresh_list(self):
        sel = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for i, p in enumerate(self.videos):
            self.listbox.insert("end", f"{self.status.get(i, '  ')}  {Path(p).name}")
        for i in sel:
            if i < len(self.videos):
                self.listbox.selection_set(i)

    def _add(self, paths):
        known = {str(Path(p)) for p in self.videos}
        added = 0
        for p in paths:
            p = str(Path(p))
            if p not in known and Path(p).suffix.lower() in VIDEO_EXT and Path(p).is_file():
                self.videos.append(p)
                known.add(p)
                added += 1
        self.refresh_list()
        return added

    def add_paths(self, paths):
        """Thêm file hoặc thư mục (kéo thả, menu chuột phải); thư mục thì lấy các video bên trong."""
        flat = []
        for p in paths:
            p = Path(p)
            flat += sorted(p.iterdir()) if p.is_dir() else [p]
        added = self._add(str(x) for x in flat)
        if added:
            self.write(f"\nĐã thêm {added} video vào hàng đợi.\n")
            if self.proc:
                self.write("(Video mới sẽ được xử lý ở lượt chạy sau.)\n")
        elif flat:
            self.write("\nKhông có video mới hợp lệ trong những mục vừa thêm.\n")

    def _dnd_all(self, widget):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)
        except (AttributeError, tk.TclError):
            pass
        if widget is not self:
            for child in widget.winfo_children():
                self._dnd_all(child)

    def on_drop(self, event):
        self.add_paths(self.tk.splitlist(event.data))
        return event.action

    def bring_to_front(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def add_files(self):
        ps = filedialog.askopenfilenames(
            title="Chọn một hoặc nhiều video",
            filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.webm *.ts *.flv *.m4v"), ("Tất cả", "*.*")])
        self._add(ps)

    def add_folder(self):
        d = filedialog.askdirectory(title="Chọn thư mục chứa video")
        if d:
            self._add(sorted(str(p) for p in Path(d).iterdir() if p.is_file()))

    def remove_selected(self):
        if self.proc:
            return
        for i in reversed(self.listbox.curselection()):
            del self.videos[i]
        self.status = {}
        self.refresh_list()

    def clear_all(self):
        if self.proc:
            return
        self.videos.clear()
        self.status = {}
        self.refresh_list()

    def focus_video(self):
        sel = self.listbox.curselection()
        if sel:
            return self.videos[sel[0]]
        if self.videos:
            return self.videos[0]
        messagebox.showwarning("SubTrans", "Hãy thêm ít nhất một video.")
        return None

    def pick_crop(self):
        """Mở hộp thoại chọn vùng phụ đề trực quan trên khung hình của video đang chọn."""
        video = self.focus_video()
        if not video:
            return
        if not Path(video).is_file():
            messagebox.showwarning("SubTrans", f"Không tìm thấy file: {video}")
            return
        from .cropdialog import CropDialog
        res = CropDialog(self, video, self.vars["crop"].get()).run()
        if res:
            self.vars["crop"].set(res)
            self.write(f"\n[Vùng sub đặt thành {res} bằng công cụ chọn trên video.]\n")

    def edit_selected(self):
        p = self.focus_video()
        if p:
            self.nb.select(self.editor)
            self.editor.load_video(p)

    def open_folder(self):
        p = self.focus_video()
        if p:
            sysdeps.open_path(Path(p).parent)

    def open_preview(self):
        p = self.focus_video()
        if p:
            d = Path(p).with_suffix(".subtrans") / "preview" / "frames"
            if d.is_dir():
                sysdeps.open_path(d)
            else:
                messagebox.showinfo("SubTrans", "Chưa có ảnh xem trước cho video này. Bấm 'Xem trước' trước.")

    # ---- kiểu phụ đề (dùng chung cho tab chỉnh sửa và các lần xuất)
    def _hex(self, key):
        v = self.vars[key].get().strip()
        return v if len(v) == 7 and v.startswith("#") else DEFAULT_STYLE[key]

    def pick_color(self, key):
        rgb, hexv = colorchooser.askcolor(color=self._hex(key), title="Chọn màu", parent=self)
        if hexv:
            self.vars[key].set(hexv.upper())

    def _int(self, key, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(self.vars[key].get()))))
        except (ValueError, tk.TclError):
            return default

    def _float(self, key, default, lo, hi):
        try:
            return max(lo, min(hi, float(self.vars[key].get())))
        except (ValueError, tk.TclError):
            return default

    def style_dict(self):
        v = self.vars
        return {
            "font": v["font"].get().strip() or DEFAULT_STYLE["font"],
            "font_scale": self._int("font_scale", 100, 40, 250),
            "text_color": self._hex("text_color"),
            "outline_color": self._hex("outline_color"),
            "outline_width": self._int("outline_width", 2, 0, 10),
            "bg_color": self._hex("bg_color"),
            "bg_mode": BG_MODES.get(v["bg_mode"].get(), "strip"),
            "bg_opacity": self._int("bg_opacity", 100, 0, 100),
            "bold": bool(v["bold"].get()),
            "italic": bool(v["italic"].get()),
            "shadow": self._int("shadow", 0, 0, 10),
            "pos_auto": bool(v["pos_auto"].get()),
            "pos_y": self._float("pos_y", DEFAULT_STYLE["pos_y"], 0, 100),
        }

    # ---- lệnh
    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def build_cmd(self, kind, video):
        v = self.vars
        sub = {"preview": "preview", "fix": "fix"}.get(kind, "run")
        cmd = sysdeps.cli_command() + [sub, video]
        if kind != "fix":
            cmd += ["--crop", v["crop"].get().strip(),
                    "--mode", DETECT_MODES.get(v["detect"].get(), "edge")]
            if not v["full"].get():
                if v["start"].get().strip():
                    cmd += ["--start", v["start"].get().strip()]
                if v["duration"].get().strip():
                    cmd += ["--duration", v["duration"].get().strip()]
        if self.source_kind() == "speech":
            cmd += ["--source", "speech", "--asr-engine", ASR_ENGINES.get(v["asr_engine"].get(), "local"),
                    "--asr-model", ASR_MODELS.get(v["asr_model"].get(), "small"), "--asr-lang", v["src"].get()]
        if kind != "preview":
            s = self.style_dict()
            cmd += ["--src", v["src"].get(), "--tr-model", v["tr_model"].get().strip(),
                    "--tr-provider", self.provider_of("tr")]
            if v["hint"].get().strip():
                cmd += ["--hint", v["hint"].get().strip()]
            if kind != "fix":
                cmd += ["--ocr-model", v["ocr_model"].get().strip(),
                        "--ocr-provider", self.provider_of("ocr"),
                        "--ocr-engine", OCR_ENGINES.get(v["ocr_engine"].get(), "cloud")]
            if not v["ocr_fallback"].get():
                cmd.append("--no-ocr-fallback")
            if v["also_srt"].get():
                cmd.append("--also-srt")
            if v["also_src"].get():
                cmd.append("--also-src")
            cmd += ["--font", s["font"], "--font-scale", str(s["font_scale"]),
                    "--text-color", s["text_color"], "--outline-color", s["outline_color"],
                    "--outline-width", str(s["outline_width"]), "--bg-color", s["bg_color"],
                    "--bg-mode", s["bg_mode"], "--bg-opacity", str(s["bg_opacity"]),
                    "--shadow", str(s["shadow"]),
                    "--pos-y", "-1" if s["pos_auto"] else str(s["pos_y"])]
            if s["bold"]:
                cmd.append("--bold")
            if s["italic"]:
                cmd.append("--italic")
            if kind == "dry":
                cmd.append("--dry-run")
            if kind == "export":
                cmd.append("--export-only")
        return cmd

    # ---- chạy hàng đợi
    def set_busy(self, busy):
        clicked = {"preview": self.b_preview, "dry": self.b_dry, "run": self.b_run,
                   "export": self.b_export}.get(self.kind)
        for b in self.action_btns:           # spinner on the button that started the job, the others are disabled
            b.configure(state="disabled" if busy and b is not clicked else "normal")
            b.set_loading(busy and b is clicked)
        self.b_stop.configure(state="normal" if busy else "disabled")
        if busy:
            self.bar.start(12)
        else:
            self.bar.stop()
            self.l_progress.configure(text="")

    def fix_video(self, video):
        """Dịch lại các dòng còn thiếu bản dịch của một video (gọi từ tab chỉnh sửa)."""
        if self.proc:
            messagebox.showinfo("SubTrans", "Đang xử lý, hãy đợi xong hoặc bấm Dừng ở tab Dịch.")
            return
        if video not in self.videos:
            self.videos.append(video)
            self.refresh_list()
        self.start("fix", only=[self.videos.index(video)])

    def start(self, kind, only=None):
        if self.proc or not self.videos:
            if not self.videos:
                messagebox.showwarning("SubTrans", "Hãy thêm ít nhất một video.")
            return
        missing = self.missing_keys(kind)
        if missing:
            if messagebox.askyesno("SubTrans", "Chưa có khóa API cho: " + ", ".join(missing) +
                                   ".\nMở cửa sổ nhập khóa (có hướng dẫn tự lấy khóa) ngay?"):
                self.manage_keys()
            return
        if kind == "run" and not self.vars["full"].get():
            self.write("\n[Chế độ thử đoạn ngắn đang bật; muốn dịch cả video hãy bật 'Dịch toàn bộ video'.]\n")
        self._save_settings()
        self.kind = kind
        self.cancelled = False
        self.tokens = [0, 0]
        self.status = {}
        self.jobs = list(only) if only is not None else list(range(len(self.videos)))
        self._job_total = len(self.jobs)
        self.refresh_list()
        self.set_busy(True)
        self._next_job()

    def _next_job(self):
        while self.jobs and not self.cancelled:
            i = self.jobs.pop(0)
            video = self.videos[i]
            n = len(self.videos)
            if not Path(video).is_file():
                self.status[i] = "✖"
                self.write(f"\n=== [{i + 1}/{n}] Không tìm thấy file: {video} ===\n")
                continue
            self.cur = i
            self.status[i] = "▶"
            self._job_no = self._job_total - len(self.jobs)
            self.tracker.reset()
            self.bar.start()
            self.l_progress.configure(text=self._progress_prefix() + "đang bắt đầu...")
            self.refresh_list()
            self.write(f"\n=== [{i + 1}/{n}] {Path(video).name} ===\n")
            cmd = self.build_cmd(self.kind, video)
            self.write("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd) + "\n")
            env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            self.proc = subprocess.Popen(
                cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=sysdeps.NO_WINDOW,
                start_new_session=not sysdeps.IS_WIN)
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            return
        self._finish()

    def _finish(self):
        ok = sum(1 for s in self.status.values() if s == "✔")
        bad = sum(1 for s in self.status.values() if s == "✖")
        note = "Đã dừng" if self.cancelled else "Hoàn tất"
        self.write(f"\n[{note}: {ok} video thành công, {bad} lỗi.")
        if self.tokens[0] or self.tokens[1]:
            self.write(f" Tổng token cả lượt: vào {self.tokens[0]}, ra {self.tokens[1]}.")
        self.write("]\n")
        self.proc = None
        self.cur = None
        self.set_busy(False)
        self.refresh_list()
        if self.kind in ("fix", "run"):
            self.editor.reload_after_job()

    def _reader(self, proc):
        for line in proc.stdout:
            self.q.put(line)
        proc.wait()
        self.q.put(None)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    code = self.proc.returncode if self.proc else 1
                    if self.cur is not None:
                        self.status[self.cur] = "✔" if code == 0 and not self.cancelled else "✖"
                    self.write(f"[Kết thúc video, mã thoát {code}]\n")
                    self.proc = None
                    self._next_job()
                elif item.startswith("@@PROGRESS "):
                    self._on_progress(parse_line(item))
                else:
                    m = TOKENS_RE.search(item)
                    if m:
                        self.tokens[0] += int(m.group(1))
                        self.tokens[1] += int(m.group(2))
                    self.write(item)
        except queue.Empty:
            pass
        try:
            while True:
                self.ui_q.get_nowait()()          # việc do luồng nền gửi về (vd tải danh sách model)
        except queue.Empty:
            pass
        try:
            while True:
                self.add_paths(self.ipc.get_nowait())
                self.bring_to_front()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _progress_prefix(self):
        return f"Video {self._job_no}/{self._job_total} · " if self._job_total > 1 else ""

    def _on_progress(self, d):
        """Dòng tiến độ từ cli: thanh phần trăm của bước hiện tại + thời gian còn lại ước lượng."""
        if not d:
            return
        if d.get("indeterminate"):        # chưa biết tổng (đang nạp model...): thanh chạy + tên bước
            self.tracker.reset()
            self.bar.start()
            self.l_progress.configure(text=self._progress_prefix() + f"Bước {d['stage']}/3 · {d['name']}...")
            return
        if d["total"] <= 0:
            return
        frac, eta = self.tracker.update((d["stage"], d["name"]), d["done"], d["total"])
        self.bar.set(frac)
        parts = [f"Bước {d['stage']}/3 · {d['name']}"]
        if d["stage"] >= 2:
            parts.append(f"{d['done']}/{d['total']}")
        parts.append(f"{int(frac * 100)}%")
        if d["done"] < d["total"]:
            parts.append(f"còn khoảng {fmt_duration(eta)}" if eta is not None else "đang tính thời gian còn lại...")
        self.l_progress.configure(text=self._progress_prefix() + " · ".join(parts))

    def _kill(self):
        if self.proc:
            if sysdeps.IS_WIN:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=sysdeps.NO_WINDOW)
            else:
                import signal
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)    # cả nhóm tiến trình (ffmpeg con...)
                except OSError:
                    pass

    def stop(self):
        if self.proc:
            self.cancelled = True
            self._kill()
            self.write("\n[Đã dừng. Chạy lại sẽ tiếp tục từ chỗ đã lưu.]\n")


def main(paths=None, srv=None):
    refresh_path()
    T.enable_dpi()          # before the first Tk window exists
    T.register_fonts()
    app = App()
    if paths:
        app.add_paths(paths)
    if srv:
        threading.Thread(target=serve, args=(srv, app.ipc), daemon=True).start()
    app.mainloop()


if __name__ == "__main__":
    main()






