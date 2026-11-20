"""Cài extension VLC 'SubTrans - Danh sách phụ đề' (vlc/SubTransList.lua) vào thư mục extension của người dùng.
Không cần quyền quản trị. Chạy:  python -m subtrans.vlcext"""
import shutil

from . import sysdeps

SRC = sysdeps.resource_dir() / "vlc" / "SubTransList.lua"


def target():
    return sysdeps.vlc_extensions_dir() / SRC.name


def install():
    """Chép (hoặc cập nhật) extension. True nếu có thay đổi."""
    dst = target()
    if not dst or not SRC.exists():
        return False
    try:
        if dst.exists() and dst.read_bytes() == SRC.read_bytes():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC, dst)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    print(("Đã cài vào " if install() else "Đã có bản mới nhất tại ") + str(target()))
