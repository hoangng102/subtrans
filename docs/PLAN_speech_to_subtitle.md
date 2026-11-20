# Kế hoạch: tạo phụ đề từ giọng nói (video không có hardsub)

Trạng thái: bản 1 đã làm xong (Whisper trên máy + Groq, tiếng Trung/Nhật); chưa thử Groq thật, chưa làm OpenAI. Phạm vi đã chốt: tiếng Trung và tiếng Nhật; công cụ nhận dạng giọng nói gồm
**Whisper chạy trên máy** (faster-whisper) và **Groq**; OpenAI whisper-1 làm sau.

## Mục tiêu và luồng dùng
Video không có hardsub thì lấy tiếng nói làm phụ đề: tách âm thanh, nhận dạng thành chữ kèm mốc thời gian,
rồi đi tiếp qua bước dịch và xuất `.ass` đang có. Tab Dịch có thêm **Nguồn phụ đề**: "Chữ cứng trên hình"
(như cũ) hoặc "Giọng nói". Chọn giọng nói thì ẩn "Vùng sub", "Nhận diện sub", "Đọc chữ bằng" và hiện ngôn ngữ
nói (zh, ja), công cụ nhận dạng giọng nói và cỡ model.

## Công cụ nhận dạng giọng nói
| Công cụ | Ưu | Nhược |
|---|---|---|
| Whisper trên máy (faster-whisper) | Miễn phí, offline, không bị từ chối nội dung | Máy không GPU nên model tốt chạy chậm; tải model lần đầu |
| Groq (whisper-large-v3 / turbo) | Rất nhanh, rẻ, giao thức giống OpenAI | Giới hạn dung lượng mỗi file (phải cắt đoạn); có thể từ chối một số nội dung |
| OpenAI whisper-1 (làm sau) | Có mốc thời gian theo đoạn | Đắt hơn Groq |

Claude không nhận âm thanh; gpt-4o-transcribe không có mốc thời gian theo đoạn; Gemini mốc thời gian kém tin cậy.

## Kiến trúc
- `audio.py`: ffmpeg trích âm thanh mono 16 kHz, chia đoạn tại chỗ im lặng, mỗi đoạn dưới giới hạn dung lượng
  của cloud; ghi mốc bù để ra thời gian tuyệt đối trong video.
- `asr.py`: các công cụ nhận dạng sau cùng một giao diện, trả về các đoạn (chữ, bắt đầu, kết thúc).
- `segmenter.py`: gộp đoạn quá ngắn, tách đoạn quá dài, loại đoạn "ảo" (Whisper bịa chữ lúc im lặng/có nhạc),
  loại đoạn lặp.
- Dữ liệu: ghi vào cùng `cues.json` (cue có `src`, `start`, `end`, không có `image`); `meta.source = "speech"`
  và phần `sig` có thêm nguồn + công cụ + model để biết khi nào phải chạy lại.
- Tab Chỉnh sửa đã xử lý cue không có ảnh; bước dịch, xuất `.ass`, nhập phụ đề giữ nguyên.
- Tiến độ và thời gian: dùng lại dòng `@@PROGRESS` (bước 1 tách âm thanh, bước 2 nhận dạng giọng nói, bước 3
  dịch) và bảng thời gian từng công đoạn.
- Chạy lại khi bị dừng: lưu kết quả từng đoạn âm thanh để tiếp tục từ đoạn đã xong.

## Các phần việc
1. Khảo sát: chạy thử Whisper trên máy với đoạn tiếng Trung và tiếng Nhật, đo tốc độ/độ chính xác, chọn mặc định.
2. Lõi tách và chia đoạn âm thanh + chỉnh đoạn.
3. Whisper trên máy: nạp model, tải model lần đầu có tiến độ, chọn cỡ model.
4. Groq: gọi qua giao thức OpenAI, cắt đoạn, nối mốc thời gian.
5. Giao diện: lựa chọn nguồn phụ đề, ẩn hiện ô, "Xem trước" (nhận dạng 60 giây đầu), "Ước lượng".
6. Kiểm tra: nhiều loại video, dừng giữa chừng rồi chạy lại.
7. (Sau) chế độ lai giọng nói + hardsub; thêm OpenAI whisper-1.

## Rủi ro
- Whisper bịa chữ lúc im lặng/có nhạc (chữ bịa sẽ bị dịch tiếp) → lọc kỹ.
- Mốc thời gian lệch vài trăm ms → tab Chỉnh sửa đã có "Lệch giờ".
- Máy không GPU: model tốt chạy chậm → đo thử rồi mới chốt mặc định; cloud (Groq) là đường nhanh.
- Dung lượng thư viện và giấy phép khi đóng gói thương mại → kiểm tra trước khi phát hành.
- Cloud có thể từ chối một số nội dung (như bước OCR); bản chạy trên máy không bị.

## Kết quả khảo sát (máy CPU 8 luồng, Whisper small int8, đoạn 2 phút nhiều thoại)
- Tốc độ khoảng 0,1-0,15x thời lượng (2 phút âm thanh mất 12-18 giây). Đoạn thưa tiếng nói, nhiều hơi thở chậm hơn
  nhiều (khoảng 0,5x) và chất lượng thấp.
- Bộ lọc giọng nói Silero có thể loại hết khi giọng nhỏ/thì thầm, nên khi VAD không thấy gì mà đoạn có tiếng thì
  chạy lại không dùng VAD.
- Mốc thời gian lệch so với phụ đề cứng trung vị khoảng 0,5 giây; 35/37 và 37/37 cue phụ đề cứng được một câu
  Whisper phủ lên (không dùng VAD / dùng VAD).
- Whisper hay bịa chữ hoặc lặp ở đoạn khó (logprob dưới -1,2, hoặc lặp ký tự) nên bộ chỉnh đoạn lọc các trường hợp này.
