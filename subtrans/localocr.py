"""OCR cục bộ (RapidOCR, chạy offline trên CPU) để đọc chữ hardsub mà không cần gọi mô hình.

Đã chỉnh cho dải sub: bỏ bước phân loại hướng chữ, giới hạn cạnh dài khi dò chữ (mặc định RapidOCR phóng
dải sub lên rất lớn nên chậm), và đọc nhiều ảnh song song. Mỗi kết quả kèm điểm tin cậy thấp nhất của các
dòng chữ, để chế độ 'lai' biết dòng nào cần mô hình AI kiểm lại."""
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

DET_SIDE = 960          # cạnh dài tối đa khi dò chữ
INTRA_THREADS = 2       # luồng tính toán cho mỗi lần đọc
_engine = None
_lock = threading.Lock()


def available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(det_limit_side_len=DET_SIDE, det_limit_type="max",
                               intra_op_num_threads=INTRA_THREADS, inter_op_num_threads=1)
        return _engine


def default_workers():
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def read_scored(path, min_score=0.5):
    """Đọc chữ phụ đề trong ảnh dải sub. Trả về (chữ, điểm tin cậy thấp nhất); điểm 0 nếu không đọc được gì.
    Bỏ watermark/logo ở các góc (chữ lệch khỏi giữa khung và ngắn)."""
    result, _ = _get_engine()(str(path), use_cls=False)
    if not result:
        return "", 0.0
    with Image.open(path) as im:
        width = im.width
    items, scores = [], []
    for box, text, score in result:
        text = (text or "").strip()
        if not text or float(score) < min_score:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        cx, w, cy, h = (min(xs) + max(xs)) / 2, max(xs) - min(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys)
        if abs(cx - width / 2) > 0.3 * width and w < 0.4 * width:
            continue
        items.append((cy, h, min(xs), text))
        scores.append(float(score))
    items.sort()
    rows = []          # gom các đoạn cùng một hàng chữ (cách nhau bởi khoảng trắng) thành một dòng
    for cy, h, x, text in items:
        if rows and abs(cy - rows[-1]["cy"]) < 0.5 * max(h, rows[-1]["h"]):
            rows[-1]["parts"].append((x, text))
        else:
            rows.append({"cy": cy, "h": h, "parts": [(x, text)]})
    text = "\n".join(" ".join(t for _, t in sorted(r["parts"])) for r in rows)
    return text, (min(scores) if scores else 0.0)


_LATIN = re.compile(r"[A-Za-z]+")


def is_reliable(text, score, threshold):
    """Chế độ lai: chỉ nhận kết quả cục bộ khi đủ tin cậy và không có chữ Latin dễ nhầm.
    OCR hay đọc "AI" thành "Al" mà vẫn cho điểm cao, nên mọi từ Latin không phải cụm chữ HOA từ 3 ký tự
    trở lên và không chứa I/L/O đều chuyển cho mô hình AI."""
    if not text.strip() or score < threshold:
        return False
    for run in _LATIN.findall(text):
        if len(run) < 3 or not run.isupper() or set(run) & set("ILO"):
            return False
    return True


def read(path, min_score=0.5):
    return read_scored(path, min_score)[0]


def read_many(paths, workers=None, on_done=None):
    """Đọc nhiều ảnh song song. Trả về danh sách (chữ, điểm) đúng thứ tự `paths`; ảnh lỗi cho ("", 0.0).
    on_done(i, chữ, điểm) được gọi (từ luồng nền) ngay khi mỗi ảnh xong."""
    _get_engine()           # nạp model một lần trước khi chạy song song
    out = [("", 0.0)] * len(paths)

    def one(i):
        try:
            res = read_scored(paths[i])
        except Exception:                      # ảnh hỏng, lỗi engine...
            res = ("", 0.0)
        out[i] = res
        if on_done:
            on_done(i, *res)

    with ThreadPoolExecutor(workers or default_workers()) as ex:
        list(ex.map(one, range(len(paths))))
    return out

