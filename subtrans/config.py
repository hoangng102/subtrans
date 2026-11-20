import os
from pathlib import Path

from . import keystore, sysdeps

# ROOT: nơi đặt settings.json, file khóa, glossary.txt, dev.flag. Chạy từ mã nguồn thì là thư mục dự án; bản đóng gói
# (chỉ đọc) thì là thư mục dữ liệu của người dùng.
ROOT = sysdeps.config_dir() if sysdeps.FROZEN else Path(__file__).resolve().parent.parent
KEY_FILES = ["api_key.env", "api_key.env.txt", ".env"]

OCR_MODEL = "claude-sonnet-5-5"
TRANSLATE_MODEL = "claude-sonnet-5-5"

# Tên biến chứa khóa API của từng nhà cung cấp (trong môi trường hoặc file khóa ở thư mục dự án).
ENV_NAMES = {
    "claude": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "qwen": ("DASHSCOPE_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
}
NO_KEY = {"ollama"}        # chạy trên máy người dùng, không cần khóa

# Chế độ nhà phát triển: hiện chi tiết nguồn khóa và nút mở file khóa. Người dùng thường không thấy khóa mặc định
# (biến môi trường / api_key.env.txt) và không sửa được nó trong giao diện. Bật bằng biến môi trường SUBTRANS_DEV=1
# hoặc tạo file dev.flag trong thư mục dự án.
DEV_MODE = os.environ.get("SUBTRANS_DEV") == "1" or (ROOT / "dev.flag").is_file()


def _file_keys() -> dict:
    """Đọc các dòng KEY=VALUE từ file khóa. Riêng khóa Anthropic cũng được ghi trần (sk-ant-...).

    Giá trị khóa không bao giờ được in ra.
    """
    found = {}
    for name in KEY_FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip("\"'")
                if v:
                    found.setdefault(k.strip(), v)
            elif line.startswith("sk-ant"):
                found.setdefault("ANTHROPIC_API_KEY", line)
    return found


def key_file() -> Path:
    """File khóa đang dùng (hoặc file mặc định sẽ được tạo nếu chưa có)."""
    for name in KEY_FILES:
        if (ROOT / name).is_file():
            return ROOT / name
    return ROOT / "api_key.env.txt"


def _find(provider: str):
    """Trả về (khóa, nguồn) theo thứ tự ưu tiên: biến môi trường > khóa nhập trong ứng dụng > file khóa."""
    names = ENV_NAMES[provider]
    stored = keystore.get(names[0])           # khóa người dùng tự nhập luôn được ưu tiên hơn khóa mặc định
    if stored:
        return stored, "app"
    for n in names:
        if os.environ.get(n):
            return os.environ[n], "env"
    file_keys = _file_keys()
    for n in names:
        if file_keys.get(n):
            return file_keys[n], "file"
    return None, None


def _lookup(provider: str):
    return _find(provider)[0]


def has_key(provider: str) -> bool:
    return provider in NO_KEY or bool(_lookup(provider))


def key_source(provider: str):
    """"env" | "app" | "file" | None (không bao giờ trả về giá trị khóa)."""
    return _find(provider)[1]


def set_key(provider: str, value: str):
    """Lưu khóa nhập trong ứng dụng (mã hóa DPAPI, chỉ trên máy này)."""
    keystore.set_key(ENV_NAMES[provider][0], value)


def clear_key(provider: str):
    keystore.delete(ENV_NAMES[provider][0])


def load_api_key(provider: str = "claude") -> str:
    if provider in NO_KEY:
        return _lookup(provider) or ""
    key = _lookup(provider)
    if key:
        return key
    name = ENV_NAMES[provider][0]
    raise SystemExit(f"Chưa có khóa API cho {provider}. Mở SubTrans, bấm \"Quản lý khóa API\" ở tab Dịch để "
                     f"dán khóa (hoặc đặt biến môi trường {name}).")


