"""Biến các đoạn nhận dạng giọng nói thô thành các cue phụ đề: lọc chữ "ảo" của Whisper, gộp đoạn quá ngắn, tách
đoạn quá dài, và sửa mốc thời gian chồng lấn."""
import re

MAX_DUR = 7.0           # giây: cue dài hơn thì tách
MAX_CHARS = 40          # ký tự chữ gốc trên một cue
MIN_DUR = 0.6
MERGE_GAP = 0.25
MERGE_CHARS = 20
MIN_LOGPROB = -1.2      # dưới mức này gần như chắc là nghe nhầm / chữ bịa
MAX_COMP = 2.6          # tỉ lệ nén cao = lặp vô nghĩa

# Câu Whisper hay bịa ra khi im lặng hoặc có nhạc (tiếng Trung, tiếng Nhật, tiếng Anh)
HALLU = re.compile(
    r"(ご視聴ありがとう|ご覧いただきありがとう|チャンネル登録|高評価|字幕\s*[:：]?\s*(by|由|提供)|Amara\.org|"
    r"请不吝点赞|不吝点赞|订阅.{0,6}(频道|我的)|谢谢观看|感谢观看|謝謝觀看|感謝觀看|"
    r"thanks? for watching|subtitles? by|please subscribe)", re.I)
_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.U)
_LOOP = re.compile(r"(.{1,6}?)\1{5,}")
_SENT_END = re.compile(r"[。！？!?…]$")
_SPLIT = re.compile(r"(?<=[。！？!?…、，,；;])")


def _norm(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    return _LOOP.sub(lambda m: m.group(1) * 3, text)      # "ああああああ…" (vòng lặp) -> giữ ba lần


def _keep(seg, text):
    if not text or _PUNCT_ONLY.match(text) or HALLU.search(text):
        return False
    if seg.get("logprob", 0.0) < MIN_LOGPROB or seg.get("comp", 1.0) > MAX_COMP:
        return False
    if seg.get("no_speech", 0.0) > 0.85 and seg.get("logprob", 0.0) < -0.6:
        return False
    if len(text) >= 10 and len(set(text)) / len(text) < 0.15:
        return False
    return True


def _join(a, b):
    """Nối hai đoạn chữ: chữ Hán/Nhật không cần dấu cách, chữ Latin thì có."""
    if re.search(r"[A-Za-z0-9]$", a) and re.search(r"^[A-Za-z0-9]", b):
        return a + " " + b
    return a + b


def _split(c):
    """Tách một cue quá dài tại dấu câu gần giữa nhất (đệ quy), chia thời gian theo số ký tự."""
    text, dur = c["src"], c["end"] - c["start"]
    if dur <= MAX_DUR and len(text) <= MAX_CHARS:
        return [c]
    if len(text) <= MAX_CHARS:
        # Chữ ngắn nhưng đoạn kéo dài (Whisper gán một tiếng "ừ"/"あ" cho cả chục giây): không có gì để tách, chỉ cần
        # rút ngắn cue theo độ dài chữ. (Tách theo thời gian ở đây từng gây đệ quy vô hạn.)
        c = dict(c)
        c["end"] = c["start"] + max(1.5, min(MAX_DUR, 0.35 * len(text) + 1.2))
        return [c]
    parts = [p for p in _SPLIT.split(text) if p]
    if len(parts) < 2:                                    # không có dấu câu: cắt đôi theo ký tự
        mid = len(text) // 2
        parts = [text[:mid], text[mid:]]
    best, acc, cut = None, 0, 1
    for i, p in enumerate(parts[:-1], 1):
        acc += len(p)
        score = abs(acc - len(text) / 2)
        if best is None or score < best:
            best, cut = score, i
    left, right = "".join(parts[:cut]), "".join(parts[cut:])
    t = c["start"] + dur * len(left) / max(1, len(text))
    out = []
    for piece, s, e in ((left, c["start"], t), (right, t, c["end"])):
        if piece.strip():
            out += _split({"start": s, "end": e, "src": piece.strip()})
    return out


def build(raw):
    """raw: các đoạn {start, end, text, logprob, no_speech, comp} với mốc tuyệt đối. Trả về danh sách
    {start, end, src} đã lọc, gộp, tách và không chồng lấn."""
    items = []
    for s in sorted(raw, key=lambda r: (r["start"], r["end"])):
        text = _norm(s["text"])
        if _keep(s, text) and s["end"] > s["start"]:
            items.append({"start": s["start"], "end": s["end"], "src": text})
    # gộp các đoạn ngắn liền nhau
    merged = []
    for c in items:
        p = merged[-1] if merged else None
        # Không gộp vào câu đã kết thúc (。！？): gộp qua ranh giới câu làm bản dịch lẫn ý của hai câu.
        if (p and c["start"] - p["end"] <= MERGE_GAP and len(p["src"]) + len(c["src"]) <= MERGE_CHARS
                and c["end"] - p["start"] <= 5.0 and not _SENT_END.search(p["src"])):
            p["src"], p["end"] = _join(p["src"], c["src"]), c["end"]
        else:
            merged.append(dict(c))
    out = []
    for c in merged:
        out += _split(c)
    # sửa mốc: không chồng lấn, mỗi cue tối thiểu MIN_DUR nếu còn chỗ
    for i, c in enumerate(out):
        nxt = out[i + 1]["start"] if i + 1 < len(out) else None
        if nxt is not None and c["end"] > nxt - 0.02:
            c["end"] = max(c["start"] + 0.2, nxt - 0.02)
        if c["end"] - c["start"] < MIN_DUR:
            c["end"] = c["start"] + MIN_DUR if nxt is None else min(c["start"] + MIN_DUR, nxt - 0.02)
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return [c for c in out if c["end"] > c["start"]]
