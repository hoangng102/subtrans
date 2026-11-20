# SubTrans

**English:** a desktop tool that turns a video into Vietnamese `.ass` subtitles. It can read hard-coded subtitles from the picture (OCR) or transcribe the speech (Whisper, local or via Groq), then translate with the AI provider of your choice (Claude, OpenAI, Gemini, Groq, OpenRouter, DeepSeek, Mistral, Ollama, ...). Everything runs on your machine; you bring your own API key (or use fully local Whisper). Includes a subtitle editor and a live subtitle table that follows VLC playback. MIT licensed.

---

Công cụ chạy trên máy bạn để tạo **phụ đề tiếng Việt (`.ass`)** cho video, dùng với VLC.

## Tải về và dùng ngay

Vào trang **[Releases](../../releases/latest)**, tải bản cho hệ điều hành của bạn, giải nén rồi chạy. Cần cài **FFmpeg** trước (chương trình sẽ báo nếu thiếu).

| Hệ điều hành | Tải | Cài FFmpeg | Chạy | Trạng thái |
|---|---|---|---|---|
| Windows 10/11 | `SubTrans-windows.zip` | `winget install Gyan.FFmpeg` | `SubTrans\SubTrans.exe` | Đã dùng thực tế |
| macOS (Apple Silicon) | `SubTrans-macos.zip` | `brew install ffmpeg` | xem bên dưới | Đã chạy tốt trên một máy Mac Apple Silicon |

- **Windows:** SmartScreen có thể cảnh báo vì file chưa ký: bấm *More info → Run anyway*.
- **macOS:** file chưa ký/công chứng nên cần gỡ cờ kiểm dịch rồi chạy từ Terminal:
  ```bash
  xattr -cr ~/Downloads/SubTrans && ~/Downloads/SubTrans/SubTrans
  ```
  (đổi đường dẫn theo nơi bạn giải nén). Bản macOS là file chạy thường, chưa phải `.app`.
- Lần đầu dùng: mở **Quản lý khóa API** để dán khóa của nhà cung cấp AI bạn chọn, hoặc chọn Whisper chạy trên máy (không cần khóa cho bước nhận dạng).
- Gặp lỗi khi mở? Gửi kèm file `crash.log` (Windows: `%APPDATA%\SubTrans`, macOS: `~/Library/Application Support/SubTrans`) khi [báo lỗi](../../issues).

## Tính năng

- **Hai nguồn chữ**
  - *Chữ cứng trên hình* (hardsub, tiếng Trung/Nhật): tự tìm các dòng chữ, đọc bằng OCR cục bộ (RapidOCR) và/hoặc mô hình AI.
  - *Giọng nói*: tách âm thanh và nhận dạng bằng Whisper chạy trên máy (miễn phí, offline) hoặc qua Groq (rất nhanh).
- **Dịch bằng AI** theo ngữ cảnh: tự ghi chú nhân vật/xưng hô cho cả video, dịch nhiều lô song song.
- **Trình chỉnh sửa**: sửa từng dòng, dịch lại bằng model khác, đọc lại chữ, nhập phụ đề có sẵn, xem trước kiểu chữ.
- **Bảng phụ đề đi theo VLC**: hiện các dòng sắp tới, "sau X giây", bấm đúp để tua.
- Xuất một file `<video>.vi.ass` (màu chữ, viền, nền, vị trí nằm trong file); tùy chọn `.srt` và chữ gốc.

## Cài đặt (chạy từ mã nguồn)

Cần Python 3.10 trở lên (đã thử với 3.12), có Tk (có sẵn trong bản Python cài từ python.org) và **FFmpeg + ffprobe** trong PATH.

```bash
pip install -r requirements.txt
python SubTrans.pyw
```

- **Windows:** cài FFmpeg (ví dụ `winget install Gyan.FFmpeg`).
- **macOS:** `brew install ffmpeg python-tk`. *macOS mới được kiểm tra trên một máy Apple Silicon; chạy từ mã nguồn trên Mac chưa được thử.*
- Video xử lý cạnh file gốc: dữ liệu nằm ở `<video>.subtrans/`, kết quả ở `<video>.vi.ass`.

## Khóa API: khi nào cần, khi nào không

| Bước | Không cần khóa | Cần khóa / dịch vụ ngoài |
|---|---|---|
| Nhận dạng giọng nói | Whisper chạy trên máy (model tải về lần đầu, 150 MB – 1,6 GB) | Groq (nhanh hơn nhiều) |
| Đọc chữ cứng trên hình | OCR cục bộ (RapidOCR) | Mô hình AI (chính xác hơn với chữ khó) |
| **Dịch sang tiếng Việt** | **Ollama chạy trên máy bạn** (cần tự cài Ollama và một model) | Claude, OpenAI, Gemini, Groq, ... bằng khóa của chính bạn |

**Nhận dạng thì không cần khóa API, nhưng bước dịch cần một mô hình AI**: hoặc khóa API của bạn, hoặc Ollama chạy trên máy. Không có cả hai, chương trình dừng với thông báo "Chưa có khóa API" sau bước nhận dạng. (Hỗ trợ Ollama mới được thử với máy chủ giả lập, chưa thử với Ollama thật.)

Nhập khóa ở nút *Quản lý khóa API* trong tab Dịch. Khóa được lưu mã hóa trên máy (Windows: DPAPI, macOS: Keychain) và chỉ gửi tới nhà cung cấp bạn chọn. Groq cho nhận dạng giọng nói rất nhanh (gói miễn phí có giới hạn tốc độ).

> Không bao giờ đưa file khóa lên kho mã. `.gitignore` đã chặn `api_key.env*`, `settings.json`, `keys.dat`.

## Dòng lệnh

```bash
python -m subtrans run video.mp4 --source speech --asr-engine groq --asr-lang ja --src ja
python -m subtrans run video.mp4 --crop 0.8-1.0 --src zh
python -m subtrans --help
```

## Bảng phụ đề đi theo VLC

Ứng dụng nhỏ `SubTransPanel.pyw` đọc vị trí đang phát qua giao diện web của VLC (chỉ nghe trên máy bạn, mật khẩu ngẫu nhiên) và hiện bảng phụ đề. Lần đầu nó hỏi để bật giao diện web trong cấu hình VLC (có sao lưu `vlcrc.subtrans-backup`). Bật tự chạy: `python -m subtrans.panelapp --autostart on`.

## Cấu trúc

| Thư mục/file | Nội dung |
|---|---|
| `subtrans/cli.py` | quy trình chính (quét/ASR → OCR → dịch → xuất) |
| `subtrans/gui.py`, `editor.py`, `ui/` | giao diện Tk |
| `subtrans/providers.py`, `llm.py` | gọi các nhà cung cấp AI, lời nhắc dịch |
| `subtrans/asr.py`, `audio.py`, `segmenter.py` | nhận dạng giọng nói |
| `subtrans/sysdeps.py` | mọi chỗ khác nhau giữa Windows/macOS/Linux |
| `subtrans/vlcpanel.py`, `panelapp.py` | bảng phụ đề VLC |
| `design/` | tài liệu thiết kế giao diện |

## Đóng gói

Xem `packaging/README.md` (Windows dùng PyInstaller).

## Lưu ý sử dụng

Hãy chỉ xử lý video bạn có quyền sử dụng. Khi dùng khóa API của nhà cung cấp nào, bạn phải tuân thủ điều khoản và chính sách sử dụng của nhà cung cấp đó (một số nhà cung cấp hạn chế một số loại nội dung). Tác giả không chịu trách nhiệm về cách bạn dùng công cụ.

## Giấy phép

MIT, xem `LICENSE`. Phần mềm và font bên thứ ba: `THIRD_PARTY_NOTICES.md`.

## Đóng góp

Pull request và issue đều được hoan nghênh. Chạy `python tests/test_segmenter.py` trước khi gửi. Phần macOS/Linux cần người có máy thật để kiểm tra: nếu bạn dùng Mac hoặc Linux, mọi báo cáo lỗi và bản sửa đều rất quý.

Không bao giờ đưa khóa API, `settings.json` hay video của bạn vào commit (`.gitignore` đã chặn các file này).
