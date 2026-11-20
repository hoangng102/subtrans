# Đóng gói SubTrans cho Windows (PyInstaller, dạng thư mục) và nén thành .zip.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [-WithFfmpeg]
# -WithFfmpeg: chép ffmpeg.exe/ffprobe.exe đang có trong PATH vào gói (kiểm tra giấy phép FFmpeg trước khi phát hành).
param([switch]$WithFfmpeg)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install --quiet -r requirements.txt pyinstaller
python -m PyInstaller packaging\subtrans.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller lỗi" }

$out = Join-Path $root "dist\SubTrans"
if ($WithFfmpeg) {
    $ff = Join-Path $out "ffmpeg"
    New-Item -ItemType Directory -Force $ff | Out-Null
    foreach ($n in "ffmpeg.exe", "ffprobe.exe") {
        $src = (Get-Command $n -ErrorAction Stop).Source
        Copy-Item $src $ff -Force
    }
}
$zip = Join-Path $root "dist\SubTrans-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip
"Xong: $zip"
