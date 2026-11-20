"""Chạy: python tests/test_segmenter.py  (không cần pytest). Kiểm tra bộ chỉnh đoạn phụ đề từ giọng nói."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from subtrans import segmenter


def seg(a, b, t, lp=-0.3):
    return {"start": a, "end": b, "text": t, "logprob": lp, "no_speech": 0.05, "comp": 1.0}


def check(name, raw, expect_cues=None):
    out = segmenter.build(raw)
    assert all(c["end"] - c["start"] <= segmenter.MAX_DUR + 0.01 and len(c["src"]) <= segmenter.MAX_CHARS for c in out), name
    assert all(out[i]["end"] <= out[i + 1]["start"] for i in range(len(out) - 1)), name
    if expect_cues is not None:
        assert len(out) == expect_cues, (name, len(out))
    print("ok:", name)


sys.setrecursionlimit(200)       # một lỗi đệ quy phải nổ ở đây, không được ẩn sau giới hạn mặc định
varied = "".join(chr(0x3042 + (i * 7) % 80) for i in range(63))
check("một ký tự kéo dài 13 giây (từng gây RecursionError)", [seg(600.0, 613.3, "あ")], 1)
check("hai ký tự kéo dài 20 giây", [seg(10, 30, "はい")], 1)
check("chữ ngắn kéo dài 9 giây", [seg(0, 9.5, "ええと、そうですね")], 1)
check("chữ dài không dấu câu, 30 giây", [seg(0, 30, varied)], 2)
check("câu hỏi toàn dấu câu", [seg(0, 12, "。")], 0)
check("hai đoạn chồng lấn", [seg(30, 33, "overlap A"), seg(32, 35, "overlap B")])
print("tất cả đạt")
