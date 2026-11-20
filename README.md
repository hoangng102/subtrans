# SubTrans

**English:** a desktop tool that turns a video into Vietnamese `.ass` subtitles. It can read hard-coded subtitles from the picture (OCR) or transcribe the speech (Whisper, local or via Groq), then translate with the AI provider of your choice (Claude, OpenAI, Gemini, Groq, OpenRouter, DeepSeek, Mistral, Ollama, ...). Everything runs on your machine; you bring your own API key (or use fully local Whisper). Includes a subtitle editor and a live subtitle table that follows VLC playback. MIT licensed.

---

Công cụ chạy trên máy bạn để tạo **phụ đề tiếng Việt (`.ass`)** cho video, dùng với VLC.

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
- **macOS:** `brew install ffmpeg python-tk`. *Hỗ trợ macOS đang ở mức thử nghiệm, chưa được kiểm tra trên máy thật.*
- Video xử lý cạnh file gốc: dữ liệu nằm ở `<video>.subtrans/`, kết quả ở `<video>.vi.ass`.

## Khóa API (tùy chọn)

Bạn có hai cách dùng miễn phí hoàn toàn:

1. **Chỉ dùng Whisper cục bộ** để nhận dạng giọng nói (model tải về lần đầu, 150 MB – 1,6 GB), và OCR cục bộ cho chữ cứng.
2. **Nhập khóa API của chính bạn** ở nút *Quản lý khóa API* trong tab Dịch. Khóa được lưu mã hóa trên máy (Windows: DPAPI, macOS: Keychain) và chỉ gửi tới nhà cung cấp bạn chọn.

Bước dịch cần một nhà cung cấp AI (Claude, OpenAI, Gemini, Groq, ... hoặc Ollama chạy trên máy bạn). Groq cho nhận dạng giọng nói rất nhanh (gói miễn phí có giới hạn tốc độ).

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

Pull request và issue đều được hoan nghênh. Chạy `python tests/test_segmenter.py` trước khi gửi. Phần macOS/Linux cần người có máy thật để kiểm tra.
