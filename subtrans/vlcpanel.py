"""Bảng 'Danh sách phụ đề' đi kèm VLC: hiện các dòng, tô dòng đang chiếu, ghi 'sau X giây' cho các dòng sắp tới,
bấm đúp một dòng để VLC nhảy tới đó.

Lấy vị trí đang phát qua giao diện web (http) của VLC, chỉ lắng nghe trên 127.0.0.1 và có mật khẩu ngẫu nhiên lưu ở
%APPDATA%\\SubTrans\\vlc_http.json. `Watcher` chạy trong SubTrans: thấy VLC đang phát một video có file phụ đề thì tự mở bảng."""
import base64
import bisect
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import ttk

from . import importer, sysdeps
from .ui import theme as T
from .ui.theme import px

LOCK_PORT = 48732           # ứng dụng độc lập panelapp giữ cổng này khi đang chạy
UPCOMING_SOON = 3.0         # giây: dòng sắp hiện trong khoảng này được tô nổi bật
COUNTDOWN_ROWS = 12         # số dòng sắp tới có ghi "sau X giây"
SUB_SUFFIXES = (".vi.ass", ".test.vi.ass", ".vi.srt", ".ass", ".srt")
CONF = sysdeps.config_dir() / "vlc_http.json"
VLCRC = sysdeps.vlc_config_dir() / "vlcrc"


# ------------------------------------------------------------------ cấu hình giao diện web của VLC
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def config():
    """(cổng, mật khẩu) cố định cho giao diện web VLC; tạo ngẫu nhiên ở lần đầu."""
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
        return int(d["port"]), str(d["password"])
    except (OSError, ValueError, KeyError):
        pass
    port, pw = free_port(), secrets.token_urlsafe(12)
    try:
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text(json.dumps({"port": port, "password": pw}), encoding="utf-8")
    except OSError:
        pass
    return port, pw


def vlc_args(port, password):
    """Tham số mở VLC với giao diện web chỉ dành cho máy này."""
    return ["--no-one-instance", "--extraintf=http", "--http-host=127.0.0.1", f"--http-port={port}",
            f"--http-password={password}"]


def _rc_value(text, key):
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    return m.group(1).strip() if m else None


def vlc_configured():
    """True nếu vlcrc đã bật giao diện web với đúng cổng/mật khẩu của SubTrans."""
    try:
        text = VLCRC.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    port, pw = config()
    return (_rc_value(text, "http-port") == str(port) and _rc_value(text, "http-password") == pw
            and _rc_value(text, "http-host") == "127.0.0.1" and "http" in (_rc_value(text, "extraintf") or "").split(":"))


def companion_running():
    """True nếu ứng dụng bảng độc lập (SubTransPanel.pyw) đang chạy: khi đó SubTrans chính không mở thêm bảng thứ hai."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", LOCK_PORT))
            return False
        except OSError:
            return True


def vlc_running():
    return sysdeps.vlc_running()


def configure_vlc():
    """Ghi vào vlcrc: bật giao diện web (http) trên 127.0.0.1 với cổng/mật khẩu của SubTrans, giữ nguyên các giao diện
    phụ khác nếu có. Phải gọi khi VLC đã đóng (VLC ghi đè vlcrc khi thoát). Trả về (ok, thông báo)."""
    if not VLCRC.exists():
        return False, "Chưa thấy cấu hình VLC. Hãy mở VLC một lần rồi đóng lại, sau đó thử lại."
    port, pw = config()
    text = VLCRC.read_text(encoding="utf-8", errors="replace")
    extra = [x for x in (_rc_value(text, "extraintf") or "").split(":") if x and x != "http"] + ["http"]
    wanted = {"extraintf": ":".join(extra), "http-host": "127.0.0.1", "http-port": str(port), "http-password": pw}
    VLCRC.with_name("vlcrc.subtrans-backup").write_text(text, encoding="utf-8")        # bản sao lưu trước khi sửa
    for key, val in wanted.items():
        pat = re.compile(rf"^#?{re.escape(key)}=.*$", re.M)
        if pat.search(text):
            text = pat.sub(lambda m: f"{key}={val}", text, count=1)
        else:
            return False, f"Không tìm thấy mục '{key}' trong cấu hình VLC (phiên bản VLC khác?)."
    VLCRC.write_text(text, encoding="utf-8")
    return True, "Đã bật. Mở VLC lại là dùng được."


# ------------------------------------------------------------------ hỏi VLC
class VlcClient:
    """Hỏi trạng thái VLC (vị trí, đang phát/tạm dừng, file đang phát) và ra lệnh tua."""

    def __init__(self, port, password):
        self.port = port
        self.base = f"http://127.0.0.1:{port}/requests/"
        token = base64.b64encode((":" + password).encode()).decode()
        self.headers = {"Authorization": "Basic " + token}

    def _get(self, name, query=""):
        req = urllib.request.Request(self.base + name + query, headers=self.headers)
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def status(self):
        """Trả về (giây, đang_phát, tốc_độ) hoặc None nếu VLC chưa sẵn sàng/đã đóng."""
        try:
            d = self._get("status.json")
        except (OSError, ValueError):
            return None
        length, pos = float(d.get("length") or 0), float(d.get("position") or 0)
        t = pos * length if length > 0 else float(d.get("time") or 0)
        return t, d.get("state") == "playing", float(d.get("rate") or 1.0)

    def playing_path(self):
        """Đường dẫn file video VLC đang phát (chỉ file trên máy), hoặc None."""
        try:
            d = self._get("playlist.json")
        except (OSError, ValueError):
            return None

        def walk(node):
            if node.get("current") == "current" and node.get("uri"):
                return node["uri"]
            for ch in node.get("children") or []:
                r = walk(ch)
                if r:
                    return r
            return None
        uri = walk(d)
        if not uri or not uri.startswith("file:"):
            return None
        return urllib.request.url2pathname(urllib.parse.urlparse(uri).path)

    def seek(self, seconds):
        try:
            self._get("status.json", "?command=seek&val=" + urllib.parse.quote(f"{max(0, int(seconds))}"))
        except (OSError, ValueError):
            pass


def find_subs(video):
    """Tìm phụ đề cạnh video. Trả về (các dòng {start,end,vi}, đường dẫn file, mtime) hoặc None."""
    base = Path(video).with_suffix("")
    for suf in SUB_SUFFIXES:
        p = base.with_name(base.name + suf)
        try:
            if not p.is_file():
                continue
            entries = [e for e in importer.parse_file(p) if e.get("start") is not None]
            if entries:
                return ([{"start": e["start"], "end": e["end"], "vi": e["text"]} for e in entries], p, p.stat().st_mtime)
        except (OSError, ValueError):
            continue
    return None


def fmt_t(t):
    t = int(max(0, t))
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ------------------------------------------------------------------ cửa sổ bảng
class SubListWindow(tk.Toplevel):
    def __init__(self, parent, cues, client, title="Danh sách phụ đề", on_close=None):
        super().__init__(parent)
        self.configure(bg=T.WINDOW)
        w, h = px(520), px(640)
        self.geometry(f"{w}x{h}+{max(0, self.winfo_screenwidth() - w - px(24))}+{px(60)}")
        self.client, self.on_close = client, on_close
        self.latest, self.alive, self.fails = None, True, 0
        self.cur, self.now_on, self.countdown = -1, False, set()

        self.status_l = tk.Label(self, text="Đang kết nối với VLC...", bg=T.WINDOW, fg=T.TEXT_MUTED, anchor="w",
                                 font=T.font(12))
        self.status_l.pack(fill="x", padx=px(12), pady=(px(10), px(4)))
        box = tk.Frame(self, bg=T.WINDOW)
        box.pack(fill="both", expand=True, padx=px(12))
        self.tree = ttk.Treeview(box, columns=("t", "in", "text"), show="headings", selectmode="browse")
        for col, text, wd in (("t", "Lúc", 64), ("in", "Còn", 84), ("text", "Phụ đề", 320)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=px(wd), anchor="w", stretch=(col == "text"))
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, kw in (("past", dict(foreground=T.TEXT_MUTED)), ("now", dict(background="#FFD27A", foreground="#000000")),
                        ("soon", dict(background="#FFF1DD", foreground="#B34A00")), ("next", dict(foreground=T.TEXT))):
            self.tree.tag_configure(tag, **kw)
        self.tree.bind("<Double-1>", self.on_seek)
        self.top_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Luôn nằm trên cùng", variable=self.top_var, bg=T.WINDOW, fg=T.TEXT_MUTED,
                       activebackground=T.WINDOW, font=T.font(12), anchor="w", bd=0, highlightthickness=0,
                       command=lambda: self.attributes("-topmost", self.top_var.get())
                       ).pack(fill="x", padx=px(10), pady=(px(4), px(8)))
        self.load(cues, title)
        self.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.poll, daemon=True).start()
        self.after(150, self.tick)

    # ---------------------------------------------------------------- dữ liệu
    def load(self, cues, title="Danh sách phụ đề"):
        self.title("SubTrans – " + title)
        self.cues = sorted((c for c in cues if (c.get("vi") or "").strip()), key=lambda c: c["start"])
        self.starts = [c["start"] for c in self.cues]
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.cues):
            self.tree.insert("", "end", iid=str(i), values=(fmt_t(c["start"]), "", c["vi"].replace("\n", " ⏎ ")),
                             tags=("next",))
        self.cur, self.now_on, self.countdown = -1, False, set()

    # ---------------------------------------------------------------- vòng hỏi VLC (luồng riêng)
    def poll(self):
        while self.alive:
            self.latest = (self.client.status(), time.monotonic())
            time.sleep(0.4)

    def now_time(self):
        st = self.latest
        if not st or st[0] is None:
            return None
        (t, playing, rate), at = st
        return t + (time.monotonic() - at) * rate if playing else t

    # ---------------------------------------------------------------- cập nhật giao diện
    def tag_for(self, i, t):
        c = self.cues[i]
        if i < self.cur or (i == self.cur and t >= c["end"]):
            return "past"
        if i == self.cur:
            return "now"
        return "soon" if c["start"] - t < UPCOMING_SOON else "next"

    def tick(self):
        if not self.alive:
            return
        t = self.now_time()
        if t is None:
            self.fails += 1
            if self.fails > 2:
                self.status_l.configure(text="Chưa kết nối được VLC (đã đóng VLC?)")
        else:
            self.fails = 0
            if self.cues:
                self.update_view(t)
        self.after(200, self.tick)

    def update_view(self, t):
        cur = bisect.bisect_right(self.starts, t) - 1
        on = cur >= 0 and t < self.cues[cur]["end"]
        old = self.cur
        self.cur = cur
        lo, hi = min(cur, old) - 1, max(cur, old) + 1
        for i in range(max(0, lo), min(len(self.cues), hi + 1)):          # chỉ các dòng đổi trạng thái
            self.tree.item(str(i), tags=(self.tag_for(i, t),))
        if on != self.now_on and 0 <= cur < len(self.cues):
            self.tree.item(str(cur), tags=(self.tag_for(cur, t),))
        self.now_on = on
        want = set(range(cur + 1, min(len(self.cues), cur + 1 + COUNTDOWN_ROWS)))
        for i in self.countdown - want:
            self.tree.set(str(i), "in", "")
        for i in want:
            wait = self.cues[i]["start"] - t
            self.tree.set(str(i), "in", "sắp hiện" if wait < 0.5 else f"sau {int(wait + 0.999)} giây")
            if wait < UPCOMING_SOON:
                self.tree.item(str(i), tags=("soon",))
        self.countdown = want
        if cur != old and cur >= 0:
            self.tree.see(str(min(len(self.cues) - 1, cur + 4)))
            self.tree.see(str(cur))
        self.status_l.configure(text=f"Đang ở {fmt_t(t)} · dòng {cur + 1}/{len(self.cues)}"
                                     "  ·  bấm đúp một dòng để tua tới đó")

    def on_seek(self, _e):
        sel = self.tree.selection()
        if sel:
            threading.Thread(target=self.client.seek, args=(self.cues[int(sel[0])]["start"] - 0.5,), daemon=True).start()

    def close(self):
        self.alive = False
        self.destroy()
        if self.on_close:
            self.on_close()


# ------------------------------------------------------------------ tự mở bảng khi VLC phát video có phụ đề
class Watcher:
    """Chạy trong SubTrans: cứ vài giây hỏi VLC đang phát file nào; có phụ đề cạnh file đó thì mở/cập nhật bảng."""
    EVERY = 2.0

    def __init__(self, root):
        self.root, self.alive, self.found = root, False, None
        self.client = VlcClient(*config())
        self.panel, self.sig, self.dismissed = None, None, None
        self.lock = threading.Lock()

    def start(self, force=False):
        """force=True: dùng cho chính ứng dụng bảng độc lập (nó tự giữ cổng khóa nên không được tự chặn mình)."""
        if self.alive or (not force and companion_running()):
            return
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()
        self.root.after(800, self._apply)

    def stop(self):
        self.alive = False

    def _loop(self):
        while self.alive:
            path = self.client.playing_path()
            subs = find_subs(path) if path else None
            with self.lock:
                self.found = (path, subs)
            time.sleep(self.EVERY)

    def _apply(self):
        if not self.alive:
            return
        with self.lock:
            found = self.found
        if found:
            path, subs = found
            if not subs:
                self.sig = None
            else:
                sig = (path, str(subs[1]), subs[2])
                if sig != self.sig and path != self.dismissed:
                    self.sig = sig
                    self._show(subs[0], Path(path).name)
        self.root.after(1000, self._apply)

    def _show(self, cues, name):
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.load(cues, name)
        else:
            self.panel = SubListWindow(self.root, cues, self.client, name, on_close=self._closed)

    def _closed(self):
        self.panel = None
        if self.found:
            self.dismissed = self.found[0]          # người dùng đã đóng bảng cho video này: không tự mở lại

    def open_now(self):
        """Mở lại bảng ngay (kể cả khi trước đó đã đóng)."""
        self.dismissed, self.sig = None, None
        self.start()
