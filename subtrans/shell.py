"""Thêm/gỡ mục "Dịch phụ đề bằng SubTrans" cho file video (chỉ cho tài khoản hiện tại).

    python -m subtrans.shell install
    python -m subtrans.shell uninstall

Windows: menu chuột phải của Explorer (registry HKCU). macOS: một Quick Action ("Dịch vụ") trong Finder, chưa chạy thử
trên máy thật. Linux: chưa hỗ trợ.
"""
import shlex
import sys
from pathlib import Path

from . import sysdeps

EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv", ".m4v"]
LABEL = "Dịch phụ đề bằng SubTrans"
MAC_WORKFLOW = Path.home() / "Library" / "Services" / (LABEL + ".workflow")


def _key(ext):
    return rf"Software\Classes\SystemFileAssociations\{ext}\shell\SubTrans"


def _install_win():
    import winreg
    launch = sysdeps.gui_launcher()
    cmd = " ".join(f'"{c}"' for c in launch) + ' "%1"'
    for ext in EXTS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _key(ext)) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, LABEL)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, launch[0])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _key(ext) + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def _uninstall_win():
    import winreg
    for ext in EXTS:
        for sub in (_key(ext) + r"\command", _key(ext)):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass


_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>NSServices</key><array><dict>
<key>NSMenuItem</key><dict><key>default</key><string>{label}</string></dict>
<key>NSMessage</key><string>runWorkflowAsService</string>
<key>NSRequiredContext</key><dict><key>NSApplicationIdentifier</key><string>com.apple.finder</string></dict>
<key>NSSendFileTypes</key><array><string>public.movie</string></array>
</dict></array></dict></plist>
"""

_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>AMApplicationBuild</key><string>523</string><key>AMApplicationVersion</key><string>2.10</string>
<key>AMDocumentVersion</key><string>2</string>
<key>actions</key><array><dict><key>action</key><dict>
<key>AMAccepts</key><dict><key>Container</key><string>List</string><key>Optional</key><false/>
<key>Types</key><array><string>com.apple.cocoa.path</string></array></dict>
<key>AMActionVersion</key><string>2.0.3</string>
<key>AMApplication</key><array><string>Automator</string></array>
<key>AMParameterProperties</key><dict><key>COMMAND_STRING</key><dict/><key>CheckedForUserDefaultShell</key><dict/>
<key>inputMethod</key><dict/><key>shell</key><dict/><key>source</key><dict/></dict>
<key>AMProvides</key><dict><key>Container</key><string>List</string><key>Types</key><array><string>com.apple.cocoa.string</string></array></dict>
<key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
<key>ActionName</key><string>Run Shell Script</string>
<key>ActionParameters</key><dict>
<key>COMMAND_STRING</key><string>{script}</string>
<key>CheckedForUserDefaultShell</key><true/><key>inputMethod</key><integer>1</integer>
<key>shell</key><string>/bin/zsh</string><key>source</key><string></string></dict>
<key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
<key>CFBundleVersion</key><string>2.0.3</string><key>CanShowSelectedItemsWhenRun</key><false/>
<key>CanShowWhenRun</key><true/><key>Category</key><array><string>AMCategoryUtilities</string></array>
<key>Class Name</key><string>RunShellScriptAction</string>
<key>InputUUID</key><string>00000000-0000-0000-0000-000000000001</string>
<key>Keywords</key><array><string>Shell</string></array>
<key>OutputUUID</key><string>00000000-0000-0000-0000-000000000002</string>
<key>UUID</key><string>00000000-0000-0000-0000-000000000003</string>
<key>UnlocalizedApplications</key><array><string>Automator</string></array>
<key>arguments</key><dict/><key>isViewVisible</key><true/><key>location</key><string>309.000000:253.000000</string>
<key>nibPath</key><string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib</string>
</dict></dict></array>
<key>connectors</key><dict/>
<key>workflowMetaData</key><dict><key>serviceInputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject</string>
<key>serviceApplicationBundleID</key><string>com.apple.finder</string>
<key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string></dict>
</dict></plist>
"""


def _install_mac():
    launch = " ".join(shlex.quote(c) for c in sysdeps.gui_launcher())
    script = f'for f in "$@"; do {launch} "$f" &\ndone'.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    contents = MAC_WORKFLOW / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(_INFO.format(label=LABEL), encoding="utf-8")
    (contents / "document.wflow").write_text(_DOC.format(script=script), encoding="utf-8")


def _uninstall_mac():
    import shutil
    shutil.rmtree(MAC_WORKFLOW, ignore_errors=True)


def install():
    if sysdeps.IS_WIN:
        _install_win()
    elif sysdeps.IS_MAC:
        _install_mac()
    else:
        print("Hệ điều hành này chưa hỗ trợ thêm menu chuột phải.")
        return
    print(f"Đã thêm mục '{LABEL}' cho: {', '.join(EXTS)}")


def uninstall():
    if sysdeps.IS_WIN:
        _uninstall_win()
    elif sysdeps.IS_MAC:
        _uninstall_mac()
    print("Đã gỡ mục menu.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    else:
        print(__doc__)
