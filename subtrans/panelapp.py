"""Ứng dụng nhỏ độc lập: chỉ chạy bảng 'Danh sách phụ đề' đi theo VLC (không mở cửa sổ SubTrans chính).
Mở ứng dụng, rồi mở video bằng VLC: bảng tự hiện khi video có file phụ đề cạnh nó và tự theo mọi lần tua.
Tự thoát khi VLC đã đóng một lúc (hoặc không thấy VLC phát gì sau một lúc đầu)."""
import socket
import sys
import time
import tkinter as tk
from tkinter import messagebox

from . import sysdeps, vlcpanel
from .ui import theme as T

LOCK_PORT = vlcpanel.LOCK_PORT
IDLE_AFTER_SEEN = 180       # giây: VLC đã đóng bao lâu thì thoát
IDLE_NEVER_SEEN = 900       # giây: chưa thấy VLC phát gì bao lâu thì thoát


def startup_link():
    return sysdeps.autostart_path()


def set_autostart(on):
    """Bật/tắt tự chạy khi đăng nhập (Windows: lối tắt trong Startup; macOS: LaunchAgent), chạy nền ở chế độ --resident."""
    return sysdeps.set_autostart(on, sysdeps.panel_launcher() + ["--resident"])


def main():
    args = sys.argv[1:]
    if "--autostart" in args:
        val = args[args.index("--autostart") + 1] if len(args) > args.index("--autostart") + 1 else "on"
        print(set_autostart(val != "off"))
        return
    resident = "--resident" in args
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))             # một bản chạy duy nhất
    except OSError:
        return
    T.enable_dpi()
    T.register_fonts()
    root = tk.Tk()
    T.init(root)
    root.withdraw()
    if not vlcpanel.vlc_configured():
        if messagebox.askyesno("SubTrans – Danh sách phụ đề",
                               "Cần bật giao diện web của VLC (chỉ nghe trên máy này, có mật khẩu ngẫu nhiên) để bảng "
                               "theo dõi video đang phát.\n\nĐóng VLC rồi bấm Yes để bật?"):
            if vlcpanel.vlc_running():
                messagebox.showinfo("SubTrans", "Hãy đóng VLC trước, rồi mở lại ứng dụng này.")
                return
            ok, msg = vlcpanel.configure_vlc()
            messagebox.showinfo("SubTrans", msg)
            if not ok:
                return
        else:
            return
    watcher = vlcpanel.Watcher(root)
    watcher.start(force=True)
    started, last_seen = time.monotonic(), None

    def check_idle():
        nonlocal last_seen
        if resident:                      # chạy nền thường trực (tự chạy cùng Windows): không tự thoát
            return
        now = time.monotonic()
        if watcher.found and watcher.found[0]:
            last_seen = now
        limit = IDLE_AFTER_SEEN if last_seen else IDLE_NEVER_SEEN
        if now - (last_seen or started) > limit:
            root.destroy()
            return
        root.after(5000, check_idle)

    root.after(5000, check_idle)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
