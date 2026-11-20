"""Hộp thoại chọn vùng phụ đề trực quan: xem vài khung hình đại diện, tua tới khung có phụ đề rồi kéo hai cạnh
(hoặc cả dải) cho khít với chữ. Kết quả là chuỗi "y0-y1" (tỉ lệ theo chiều cao) dùng cho tham số --crop."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk

from . import frames
from .editor import grab_frame
from .ui import theme as T
from .ui import widgets as W

DEFAULT_CROP = (0.75, 1.0)
MIN_GAP = 0.03       # dải tối thiểu 3% chiều cao
SNAP = 0.005         # làm tròn tới 0,5%
THUMBS = 8


def parse_crop(text):
    try:
        a, b = (float(x) for x in text.strip().split("-"))
        if 0 <= a < b <= 1:
            return a, b
    except ValueError:
        pass
    return DEFAULT_CROP


def fmt_clock(t):
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


class CropDialog(tk.Toplevel):
    def __init__(self, parent, video, crop="0.75-1.0"):
        super().__init__(parent)
        self.withdraw()
        self.title("Chọn vùng phụ đề")
        self.configure(bg=T.WINDOW)
        self.transient(parent.winfo_toplevel())
        self.video, self.result = video, None
        try:
            info = frames.probe(video)
        except Exception as e:                       # thiếu ffprobe, file hỏng...
            messagebox.showerror("SubTrans", f"Không đọc được video: {e}", parent=parent)
            self.destroy()
            return
        self.dur = max(1.0, info["duration"])
        self.vw, self.vh = info["width"], info["height"]
        self.y0, self.y1 = parse_crop(crop)
        px = T.px
        # keep the whole dialog on screen: the fixed parts (title, slider, thumbnails, strip, buttons) need ~520px
        max_h = max(px(180), min(px(430), self.winfo_screenheight() - px(520) - 60))
        max_w = min(px(860), self.winfo_screenwidth() - 120)
        s = min(max_w / self.vw, max_h / self.vh)
        self.cw, self.ch = max(200, int(self.vw * s)), max(120, int(self.vh * s))
        self.full = self._small = self._dim = None
        self._photo = self._strip_photo = None
        self._req = 0
        self._job = None
        self._drag = None
        self._silent = False
        self.q = queue.Queue()
        self._thumbs = []
        self._build()
        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self.bind("<Shift-Left>", lambda e: self._step(-10))
        self.bind("<Shift-Right>", lambda e: self._step(10))
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + max(0, (pw.winfo_width() - self.winfo_reqwidth()) // 2)
        y = pw.winfo_rooty() + max(0, (pw.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.after(50, self._poll)
        self._seek(self.dur * 0.3)
        threading.Thread(target=self._load_thumbs, daemon=True).start()

    # ------------------------------------------------------------ giao diện
    def _build(self):
        px = T.px
        wrap = tk.Frame(self, bg=T.WINDOW)
        wrap.pack(fill="both", expand=True, padx=px(20), pady=px(16))
        W.Label(wrap, "Chọn vùng phụ đề", kind="h").pack(anchor="w")
        W.Label(wrap, "Chọn một khung hình có phụ đề (bấm ảnh nhỏ hoặc kéo thanh thời gian), rồi kéo hai cạnh cam "
                      "hoặc kéo cả dải sao cho khít với dòng chữ. Phần bị làm tối sẽ không được quét.",
                kind="hint", wrap=860).pack(anchor="w", pady=(2, px(10)))

        card = W.Card(wrap, pad=10)
        card.pack(fill="x")
        self.cv = tk.Canvas(card.body, width=self.cw, height=self.ch, bg=T.PREVIEW_BG, highlightthickness=0, bd=0,
                            cursor="arrow")
        self.cv.pack()
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.cv.bind("<Motion>", self._hover)

        # thanh thời gian
        bar = tk.Frame(wrap, bg=T.WINDOW)
        bar.pack(fill="x", pady=(px(10), 0))
        for text, d in (("‹ 10 giây", -10), ("‹ 1 giây", -1)):
            W.Button(bar, text, small=True, command=lambda d=d: self._step(d)).pack(side="left", padx=(0, px(6)))
        self.scale = tk.Scale(bar, from_=0, to=self.dur, resolution=0.5, orient="horizontal", showvalue=False,
                              bd=0, highlightthickness=0, bg=T.ACCENT, troughcolor=T.TRACK, sliderlength=px(18),
                              width=px(14), sliderrelief="flat", activebackground=T.ACCENT_HOVER,
                              command=self._on_slide)
        self.scale.pack(side="left", fill="x", expand=True, padx=px(6))
        for text, d in (("1 giây ›", 1), ("10 giây ›", 10)):
            W.Button(bar, text, small=True, command=lambda d=d: self._step(d)).pack(side="left", padx=(px(6), 0))
        self.l_time = W.Label(bar, "", kind="mono")
        self.l_time.configure(width=18, anchor="e")
        self.l_time.pack(side="left", padx=(px(10), 0))

        # khung hình đại diện
        W.Label(wrap, "Khung hình đại diện (bấm để xem)", kind="label").pack(anchor="w", pady=(px(12), px(6)))
        row = tk.Frame(wrap, bg=T.WINDOW)
        row.pack(fill="x")
        tw = (self.cw - (THUMBS - 1) * px(6)) // THUMBS
        th = max(30, int(tw * self.vh / self.vw))
        self._tsize = (tw, th)
        for i in range(THUMBS):
            lb = tk.Label(row, bg=T.TRACK, cursor="hand2", bd=0)
            lb.grid(row=0, column=i, padx=(0 if i == 0 else px(6), 0))
            lb.configure(width=tw, height=th, image=self._blank(tw, th), compound="center")
            lb.bind("<Button-1>", lambda e, i=i: self._pick_thumb(i))
            self._thumbs.append(lb)
        self._tphotos = [None] * THUMBS

        # dải đã chọn, phóng to để kiểm tra
        W.Label(wrap, "Dải sẽ được quét", kind="label").pack(anchor="w", pady=(px(12), px(6)))
        self.l_strip = tk.Label(wrap, bg=T.PREVIEW_BG, bd=0)
        self.l_strip.pack(anchor="w")

        foot = tk.Frame(wrap, bg=T.WINDOW)
        foot.pack(fill="x", pady=(px(14), 0))
        self.l_info = W.Label(foot, "", kind="mono")
        self.l_info.pack(side="left")
        W.Button(foot, "Dùng vùng này", variant="primary", command=self._ok).pack(side="right")
        W.Button(foot, "Hủy", command=self._cancel).pack(side="right", padx=px(8))
        W.Button(foot, "Đặt lại 75–100%", variant="ghost", command=self._reset).pack(side="right")

    @staticmethod
    def _blank(w, h):
        return ImageTk.PhotoImage(Image.new("RGB", (w, h), T.TRACK))

    # ------------------------------------------------------------ nạp khung hình (luồng nền)
    def _seek(self, t):
        t = max(0.0, min(self.dur, t))
        self._silent = True                    # đặt thanh trượt mà không kích hoạt nạp khung hình trễ
        self.scale.set(t)
        self._silent = False
        self._request(t)

    def _step(self, d):
        self._seek(self.scale.get() + d)

    def _on_slide(self, value):
        t = float(value)
        self.l_time.configure(text=f"{fmt_clock(t)} / {fmt_clock(self.dur)}")
        if self._silent:
            return
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(250, lambda: self._request(t))

    def _request(self, t):
        self._job = None
        self._req += 1
        rid = self._req

        def work():
            self.q.put(("frame", rid, grab_frame(self.video, t)))

        threading.Thread(target=work, daemon=True).start()

    def _load_thumbs(self):
        for i in range(THUMBS):
            t = self.dur * (i + 0.5) / THUMBS
            self.q.put(("thumb", i, t, grab_frame(self.video, t)))

    def _pick_thumb(self, i):
        t = self.dur * (i + 0.5) / THUMBS
        self._seek(t)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "frame":
                    if item[1] == self._req and item[2] is not None:
                        self._show(item[2])
                else:
                    _, i, t, img = item
                    if img is not None and i < len(self._thumbs):
                        tw, th = self._tsize
                        self._tphotos[i] = ImageTk.PhotoImage(img.resize((tw, th), Image.LANCZOS))
                        self._thumbs[i].configure(image=self._tphotos[i])
        except queue.Empty:
            pass
        except tk.TclError:
            return                              # hộp thoại đã đóng
        self.after(80, self._poll)

    # ------------------------------------------------------------ vẽ và kéo
    def _show(self, img):
        self.full = img
        self._small = img.resize((self.cw, self.ch), Image.LANCZOS)
        self._dim = self._small.point(lambda v: int(v * 0.3))      # phần ngoài vùng chọn: làm tối
        self.cv.delete("img")
        self.cv.create_image(0, 0, anchor="nw", tags="img")
        self.cv.tag_lower("img")
        self._overlay()

    def _overlay(self):
        px = T.px
        cv, w, h = self.cv, self.cw, self.ch
        cv.delete("ov")
        a, b = int(self.y0 * h), int(self.y1 * h)
        if self._small is not None:
            im = self._dim.copy()
            im.paste(self._small.crop((0, a, w, b)), (0, a))
            self._photo = ImageTk.PhotoImage(im)
            cv.itemconfigure("img", image=self._photo)
        cv.create_rectangle(1, a, w - 1, b, outline=T.ACCENT, width=2, tags="ov")
        for y in (a, b):
            cv.create_rectangle(w / 2 - px(26), y - px(4), w / 2 + px(26), y + px(4), fill=T.ACCENT, outline="",
                                tags="ov")
        cv.create_text(px(8), max(px(10), a - px(10)), text=f"{self.y0 * 100:.1f}%", fill=T.ACCENT, anchor="w",
                       font=T.font(12, "semibold", mono=True), tags="ov")
        cv.create_text(px(8), min(h - px(10), b + px(10)), text=f"{self.y1 * 100:.1f}%", fill=T.ACCENT, anchor="w",
                       font=T.font(12, "semibold", mono=True), tags="ov")
        self.l_info.configure(text=f"--crop {self.y0:.3f}-{self.y1:.3f}  (cao {(self.y1 - self.y0) * 100:.1f}%)")
        self._strip()

    def _strip(self):
        if self.full is None:
            return
        w, h = self.full.size
        top, bot = int(self.y0 * h), max(int(self.y1 * h), int(self.y0 * h) + 2)
        crop = self.full.crop((0, top, w, bot))
        sw = self.cw
        sh = max(1, int(crop.height * sw / crop.width))
        if sh > T.px(110):                      # dải quá cao thì thu nhỏ cho vừa
            sh = T.px(110)
            sw = max(1, int(crop.width * sh / crop.height))
        self._strip_photo = ImageTk.PhotoImage(crop.resize((sw, sh), Image.LANCZOS))
        self.l_strip.configure(image=self._strip_photo)

    def _y(self, event):
        return max(0.0, min(1.0, event.y / self.ch))

    def _hit(self, event):
        near = T.px(9)
        a, b = self.y0 * self.ch, self.y1 * self.ch
        if abs(event.y - a) <= near:
            return "top"
        if abs(event.y - b) <= near:
            return "bottom"
        return "move" if a < event.y < b else "new"

    def _hover(self, event):
        mode = self._hit(event)
        self.cv.configure(cursor={"top": "sb_v_double_arrow", "bottom": "sb_v_double_arrow", "move": "fleur",
                                  "new": "crosshair"}[mode])

    def _press(self, event):
        mode = self._hit(event)
        y = self._y(event)
        self._drag = {"mode": mode, "anchor": y, "off": y - self.y0, "h": self.y1 - self.y0}

    @staticmethod
    def _snap(v):
        return round(v / SNAP) * SNAP

    def _motion(self, event):
        d = self._drag
        if not d:
            return
        y = self._snap(self._y(event))
        if d["mode"] == "top":
            self.y0 = max(0.0, min(y, self.y1 - MIN_GAP))
        elif d["mode"] == "bottom":
            self.y1 = min(1.0, max(y, self.y0 + MIN_GAP))
        elif d["mode"] == "move":
            top = self._snap(y - d["off"])
            top = max(0.0, min(top, 1.0 - d["h"]))
            self.y0, self.y1 = top, top + d["h"]
        else:                                    # kéo ra dải mới từ điểm bấm
            lo, hi = sorted((self._snap(d["anchor"]), y))
            if hi - lo >= MIN_GAP:
                self.y0, self.y1 = lo, hi
        self.y0, self.y1 = round(self.y0, 3), round(self.y1, 3)
        self._overlay()

    # ------------------------------------------------------------ kết thúc
    def _reset(self):
        self.y0, self.y1 = DEFAULT_CROP
        self._overlay()

    def _ok(self):
        self.result = f"{self.y0:.3f}-{self.y1:.3f}"
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    def run(self):
        if not self.winfo_exists():
            return None
        self.grab_set()
        self.wait_window()
        return self.result



