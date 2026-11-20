"""Mọi chỗ khác nhau giữa Windows / macOS / Linux nằm ở đây (đường dẫn dữ liệu, mở thư mục, clipboard ảnh, tìm VLC,
tự chạy cùng hệ thống, PATH). Các module khác chỉ gọi hàm trong file này, không tự kiểm tra hệ điều hành.

Phần Windows đã được dùng thực tế. Phần macOS/Linux viết theo tài liệu của từng hệ thống, CHƯA chạy thử trên máy thật."""
import base64
import io
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))                      # chạy từ bản đóng gói (PyInstaller)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0   # chỉ Windows có cờ này
APP = "SubTrans"


def _home():
    return Path.home()


# ------------------------------------------------------------------ thư mục dữ liệu
def config_dir() -> Path:
    """Nơi lưu cài đặt/khóa/cấu hình nhỏ của ứng dụng."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or _home()) / APP
    if IS_MAC:
        return _home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / APP


def data_dir() -> Path:
    """Nơi lưu dữ liệu lớn (model Whisper)."""
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA") or _home()) / APP
    if IS_MAC:
        return _home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share") / APP


def vlc_config_dir() -> Path:
    """Thư mục chứa vlcrc."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or _home()) / "vlc"
    if IS_MAC:
        return _home() / "Library" / "Preferences" / "org.videolan.vlc"
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / "vlc"


def vlc_extensions_dir() -> Path:
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or _home()) / "vlc" / "lua" / "extensions"
    if IS_MAC:
        return _home() / "Library" / "Application Support" / "org.videolan.vlc" / "lua" / "extensions"
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share") / "vlc" / "lua" / "extensions"


def resource_dir() -> Path:
    """Thư mục gốc chứa assets/ và vlc/ (cạnh mã nguồn, hoặc trong bản đóng gói)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ tiến trình / lệnh
def cli_command():
    """Phần đầu lệnh để chạy phần xử lý (cli) trong một tiến trình con."""
    if FROZEN:
        return [sys.executable, "--subtrans-cli"]
    exe = Path(sys.executable)
    if IS_WIN and exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return [str(exe), "-m", "subtrans"]


def gui_launcher():
    """Lệnh mở ứng dụng chính không hiện cửa sổ console (dùng cho menu chuột phải/tự chạy)."""
    if FROZEN:
        return [sys.executable]
    exe = Path(sys.executable)
    if IS_WIN and exe.name.lower() == "python.exe":
        exe = exe.with_name("pythonw.exe")
    return [str(exe), str(resource_dir() / "SubTrans.pyw")]


def panel_launcher():
    if FROZEN:
        return [sys.executable, "--panel"]
    exe = Path(sys.executable)
    if IS_WIN and exe.name.lower() == "python.exe":
        exe = exe.with_name("pythonw.exe")
    return [str(exe), str(resource_dir() / "SubTransPanel.pyw")]


def fix_ssl():
    """macOS/Linux: Python (nhất là bản đóng gói) thường không biết kho chứng chỉ của hệ thống nên mọi kết nối HTTPS
    báo CERTIFICATE_VERIFY_FAILED. Trỏ OpenSSL tới bộ chứng chỉ của certifi, hoặc file hệ thống nếu không có certifi.
    Biến môi trường được các tiến trình con thừa hưởng. Windows dùng kho chứng chỉ hệ thống nên không đổi gì."""
    if IS_WIN or os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        path = certifi.where()
    except Exception:
        path = next((p for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                                 "/etc/pki/tls/certs/ca-bundle.crt") if Path(p).is_file()), None)
    if path and Path(path).is_file():
        os.environ["SSL_CERT_FILE"] = path


def fix_path():
    """Bổ sung PATH để tìm được ffmpeg: Windows nạp lại từ registry; macOS thêm thư mục Homebrew (ứng dụng mở từ Finder
    không thừa hưởng PATH của terminal)."""
    if IS_WIN:
        try:
            import winreg
            parts = []
            for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                              (winreg.HKEY_CURRENT_USER, "Environment")):
                with winreg.OpenKey(hive, sub) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            os.environ["PATH"] = os.pathsep.join(parts + [os.environ.get("PATH", "")])
        except OSError:
            pass
    elif IS_MAC:
        extra = [p for p in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin") if Path(p).is_dir()]
        os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])
    if FROZEN:                                                   # ffmpeg đi kèm bản đóng gói (nếu có)
        for sub in ("ffmpeg", "bin", ""):
            d = resource_dir() / sub if sub else resource_dir()
            if (d / ("ffmpeg.exe" if IS_WIN else "ffmpeg")).is_file():
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                break


# ------------------------------------------------------------------ mở file / thư mục
def open_path(p):
    p = str(p)
    if IS_WIN:
        os.startfile(p)                                          # noqa: S606
    elif IS_MAC:
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


# ------------------------------------------------------------------ VLC
def find_vlc():
    cands = []
    if IS_WIN:
        cands = [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]
    elif IS_MAC:
        cands = ["/Applications/VLC.app/Contents/MacOS/VLC", str(_home() / "Applications/VLC.app/Contents/MacOS/VLC")]
    for p in cands:
        if Path(p).is_file():
            return p
    return shutil.which("vlc")


def vlc_running():
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq vlc.exe", "/NH"], capture_output=True, text=True,
                                 creationflags=NO_WINDOW, timeout=10).stdout
            return "vlc.exe" in out.lower()
        names = ("VLC",) if IS_MAC else ("vlc",)
        return any(subprocess.run(["pgrep", "-x", n], capture_output=True, timeout=10).returncode == 0 for n in names)
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------ clipboard ảnh
def copy_image(owner, img):
    """Đặt ảnh lên clipboard hệ thống. Ném OSError nếu không làm được."""
    if IS_WIN:
        return _copy_image_win(owner, img)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    png = buf.getvalue()
    if IS_MAC:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png)
        try:
            script = f'set the clipboard to (read (POSIX file "{f.name}") as «class PNGf»)'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20)
            if r.returncode != 0:
                raise OSError(r.stderr.decode("utf-8", "replace").strip() or "osascript lỗi")
        finally:
            Path(f.name).unlink(missing_ok=True)
        return
    for cmd in (["wl-copy", "--type", "image/png"], ["xclip", "-selection", "clipboard", "-t", "image/png", "-i"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=png, check=True, timeout=20)
            return
    raise OSError("Cần cài wl-clipboard hoặc xclip để sao chép ảnh.")


def _copy_image_win(owner, img):
    import ctypes
    from ctypes import wintypes

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]                      # bỏ header file BMP, giữ DIB
    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    handle = kernel32.GlobalAlloc(0x0002, len(data))      # GMEM_MOVEABLE
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(int(owner.winfo_id())):
        raise OSError("Không mở được clipboard")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(8, handle):         # CF_DIB
            raise OSError("Không đặt được ảnh lên clipboard")
    finally:
        user32.CloseClipboard()


# ------------------------------------------------------------------ tự chạy cùng hệ thống (bảng phụ đề VLC)
def autostart_path() -> Path:
    if IS_WIN:
        return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "SubTrans Panel.lnk"
    if IS_MAC:
        return _home() / "Library" / "LaunchAgents" / "com.subtrans.panel.plist"
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / "autostart" / "subtrans-panel.desktop"


def set_autostart(on, command):
    """Bật/tắt chạy `command` (list) khi đăng nhập. Trả về thông báo."""
    link = autostart_path()
    if not on:
        link.unlink(missing_ok=True)
        return "Đã tắt tự chạy cùng hệ thống."
    link.parent.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
              f"$s.TargetPath='{command[0]}';$s.Arguments='{' '.join(chr(34) + c + chr(34) for c in command[1:])}';"
              f"$s.WorkingDirectory='{Path(command[0]).parent}';$s.WindowStyle=7;$s.Save()")
        enc = base64.b64encode(ps.encode("utf-16-le")).decode()
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc], check=True, creationflags=NO_WINDOW)
    elif IS_MAC:
        plist = {"Label": "com.subtrans.panel", "ProgramArguments": list(command), "RunAtLoad": True,
                 "KeepAlive": False, "ProcessType": "Interactive"}
        link.write_bytes(plistlib.dumps(plist))
    else:
        link.write_text("[Desktop Entry]\nType=Application\nName=SubTrans Panel\nExec="
                        + " ".join(f'"{c}"' for c in command) + "\n", encoding="utf-8")
    return f"Đã bật tự chạy cùng hệ thống ({link.name})."


# ------------------------------------------------------------------ menu chuột phải / hành động nhanh
def default_font_family():
    """Họ phông giao diện mặc định theo hệ điều hành (Windows dùng Inter đã nạp riêng, ở theme.py)."""
    if IS_MAC:
        return {"regular": "Helvetica Neue", "medium": "Helvetica Neue", "semibold": "Helvetica Neue", "mono": "Menlo"}, "PingFang SC"
    if IS_WIN:
        return {"regular": "Segoe UI", "medium": "Segoe UI", "semibold": "Segoe UI Semibold", "mono": "Consolas"}, "Microsoft YaHei UI"
    return {"regular": "DejaVu Sans", "medium": "DejaVu Sans", "semibold": "DejaVu Sans", "mono": "DejaVu Sans Mono"}, "Noto Sans CJK SC"
