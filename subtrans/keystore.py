"""Kho khóa API của người dùng, lưu cục bộ.

- Windows: mã hóa bằng DPAPI (chỉ tài khoản Windows này giải mã được), file keys.dat.
- macOS: lưu trong Keychain của người dùng (dịch vụ "SubTrans"), chưa chạy thử trên máy thật.
- Linux: file keys.dat quyền 0600 (không mã hóa, chỉ chủ file đọc được).

Khóa không bao giờ được in ra log và không rời máy, ngoại trừ khi gửi tới đúng nhà cung cấp AI mà người dùng chọn.
"""
import base64
import ctypes
import json
import os
import subprocess
from pathlib import Path

from . import sysdeps

KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT = "SubTrans", "api-keys"


def store_path() -> Path:
    return sysdeps.config_dir() / "keys.dat"


def _dpapi(data: bytes, protect: bool) -> bytes:
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI thất bại")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _keychain_get():
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                       capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else None


def _keychain_set(text):
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
                        "-w", text], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise OSError("Không ghi được vào Keychain: " + r.stderr.strip())


def _load() -> dict:
    try:
        if sysdeps.IS_MAC:
            raw = _keychain_get()
            return json.loads(base64.b64decode(raw).decode("utf-8")) if raw else {}
        p = store_path()
        if not p.is_file():
            return {}
        blob = base64.b64decode(p.read_bytes())
        if sysdeps.IS_WIN:
            blob = _dpapi(blob, protect=False)
        return json.loads(blob.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}                        # file hỏng hoặc của tài khoản khác: coi như chưa có khóa


def _save(data: dict):
    raw = json.dumps(data).encode("utf-8")
    if sysdeps.IS_MAC:
        _keychain_set(base64.b64encode(raw).decode())
        return
    p = store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = _dpapi(raw, protect=True) if sysdeps.IS_WIN else raw
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(base64.b64encode(blob))
    if not sysdeps.IS_WIN:
        os.chmod(tmp, 0o600)
    tmp.replace(p)


def get(name: str):
    return _load().get(name) or None


def set_key(name: str, value: str):
    data = _load()
    data[name] = value.strip()
    _save(data)


def delete(name: str):
    data = _load()
    if data.pop(name, None) is not None:
        _save(data)
