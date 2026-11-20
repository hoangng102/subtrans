# Đóng gói SubTrans

## Windows
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1            # -> dist\SubTrans\SubTrans.exe + dist\SubTrans-windows.zip
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -WithFfmpeg # kèm ffmpeg/ffprobe lấy từ PATH
iscc packaging\installer.iss                                                     # (tùy chọn) trình cài đặt, cần Inno Setup 6
```
- Bản đóng gói là một thư mục (nhanh khởi động hơn một file `.exe` tự giải nén).
- Cài đặt và khóa API của bản đóng gói nằm ở `%APPDATA%\SubTrans`, model Whisper ở `%LOCALAPPDATA%\SubTrans\models`.
- Không có FFmpeg đi kèm theo mặc định: hoặc người dùng tự cài, hoặc build với `-WithFfmpeg`. FFmpeg là LGPL/GPL tùy bản build: nếu phát hành lại, hãy làm theo giấy phép của bản bạn dùng (ghi nguồn, kèm văn bản giấy phép).
- Windows SmartScreen sẽ cảnh báo file chưa ký. Ký mã (code signing) cần chứng chỉ trả phí.

## macOS (chưa kiểm tra trên máy thật)
PyInstaller không build chéo, cần chạy trên macOS (máy Mac hoặc runner macOS của GitHub Actions, xem `.github/workflows/build.yml`).
```bash
brew install ffmpeg python-tk
pip install -r requirements.txt pyinstaller
python -m PyInstaller packaging/subtrans.spec --noconfirm
```
- Tạo `.app` đầy đủ (biểu tượng, `Info.plist`) bằng cách thêm khối `BUNDLE(...)` vào spec.
- Phân phối rộng rãi cần ký bằng Apple Developer ID (Apple Developer Program, ~99 USD/năm) và công chứng (notarize); nếu không, người dùng phải bấm chuột phải > Open lần đầu.
- Phần cần kiểm tra trên Mac: giao diện Tk (phông, DPI, nút tự vẽ), Keychain, clipboard ảnh, tìm VLC, Quick Action chuột phải, LaunchAgent.

## Lưu ý
- Chế độ chạy phụ của bản đóng gói được chọn bằng tham số của chính file chạy: `--subtrans-cli` (tiến trình xử lý nền) và `--panel` (bảng phụ đề VLC).
