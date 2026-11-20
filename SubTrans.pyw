import json
import os
import socket
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
if not FROZEN:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.getcwd())

# Bản đóng gói chỉ có một file chạy: các chế độ phụ được chọn bằng tham số.
def _run_mode(fn):
    """Chạy một chế độ phụ. Lỗi chưa bắt được phải in ra rồi thoát: nếu để lọt ra ngoài, bản đóng gói (không có cửa sổ
    lệnh) sẽ bật hộp thoại báo lỗi và tiến trình nền treo mãi, cửa sổ chính không bao giờ nhận được dòng lỗi."""
    try:
        fn()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)


if "--subtrans-cli" in sys.argv:                 # tiến trình xử lý nền do cửa sổ chính khởi chạy
    sys.argv.remove("--subtrans-cli")
    from subtrans.cli import main as cli_main
    _run_mode(cli_main)
if "--panel" in sys.argv:                        # bảng phụ đề VLC độc lập
    sys.argv.remove("--panel")
    from subtrans.panelapp import main as panel_main
    _run_mode(panel_main)

PORT = int(os.environ.get("SUBTRANS_PORT", "48731"))      # đổi cổng khi cần chạy nhiều bản thử cùng lúc
paths = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("--")]

# Chỉ một cửa sổ: tiến trình nào chiếm được cổng sẽ là cửa sổ chính, các lần mở sau
# (menu chuột phải, shortcut) gửi đường dẫn video vào cửa sổ đó rồi thoát.
srv = socket.socket()
try:
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(16)
except OSError:
    srv.close()
    srv = None
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=2) as c:
                c.sendall(json.dumps(paths).encode("utf-8"))
            sys.exit(0)
        except OSError:
            time.sleep(0.25)

try:
    from subtrans.gui import main
    main(paths, srv)
except Exception:
    # Bản đóng gói không có cửa sổ lệnh: ghi lỗi ra file để người dùng gửi kèm khi báo lỗi.
    import traceback
    text = traceback.format_exc()
    try:
        from subtrans import sysdeps
        log = sysdeps.config_dir() / "crash.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        where = f"\n\nChi tiết đã ghi vào:\n{log}"
    except Exception:
        where = ""
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showerror("SubTrans", "SubTrans gặp lỗi khi khởi động." + where + "\n\n" + text[-600:])
    except Exception:
        pass
    raise
