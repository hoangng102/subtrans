"""Nhận biết dòng mà mô hình từ chối dịch (nó viết ghi chú thay cho bản dịch)."""
import re

_NOTE = re.compile(r"^\s*[\[\(（【].{0,160}[\]\)）】]\s*$")
_REFUSAL_WORDS = ("không dịch", "không phiên dịch", "không thể dịch", "từ chối", "nội dung",
                  "bỏ qua", "lược bỏ", "vị thành niên")


def is_refusal_note(vi, src=""):
    """Mô hình đôi khi viết ghi chú kiểu '[Không dịch: ...]' thay cho bản dịch."""
    vi = (vi or "").strip()
    return (bool(_NOTE.match(vi)) and not _NOTE.match((src or "").strip())
            and any(w in vi.lower() for w in _REFUSAL_WORDS))


_SRC_WORDS = ("不转录", "无法", "不翻译", "拒绝", "露骨", "色情", "不能", "抱歉", "cannot", "can't",
              "unable", "not transcrib", "explicit", "không thể", "không phiên", "không dịch",
              "withheld", "redact", "omitted", "content", "không đọc", "từ chối")


def is_refusal_src(src):
    """Ở bước đọc chữ, mô hình có thể viết ghi chú từ chối thay cho chữ trong ảnh."""
    s = (src or "").strip()
    return bool(_NOTE.match(s)) and any(w in s.lower() for w in _SRC_WORDS)


def mark_declined(cues):
    """Biến các ghi chú từ chối (ở chữ gốc hoặc bản dịch) thành dòng trống có cờ 'declined'
    (không xuất, không tự hỏi lại)."""
    n = 0
    for c in cues:
        if is_refusal_src(c.get("src")):
            c["src"], c["vi"], c["declined"] = "", "", True
            n += 1
        elif is_refusal_note(c.get("vi"), c.get("src")):
            c["vi"], c["declined"] = "", True
            n += 1
    return n
