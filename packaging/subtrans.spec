# -*- mode: python ; coding: utf-8 -*-
# Build:  python -m PyInstaller packaging/subtrans.spec --noconfirm --distpath dist --workpath build
# (hoặc chạy packaging/build_windows.ps1). Kết quả: dist/SubTrans/SubTrans.exe (thư mục, không phải một file).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    (str(ROOT / "vlc" / "SubTransList.lua"), "vlc"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
binaries, hiddenimports = [], ["tkinter", "tkinter.ttk", "tkinter.colorchooser"]

# Các gói có file dữ liệu / thư viện động đi kèm (model OCR, VAD của Whisper, tkdnd, onnxruntime, ctranslate2...)
for pkg in ("rapidocr_onnxruntime", "faster_whisper", "ctranslate2", "onnxruntime", "tkinterdnd2", "av"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:                       # gói không cài: bỏ qua, build vẫn chạy
        print(f"[spec] bỏ qua {pkg}: {e}")

a = Analysis(
    [str(ROOT / "SubTrans.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "torch", "tensorflow"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubTrans",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SubTrans", upx=False)
