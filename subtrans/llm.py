import io
import threading

from PIL import Image

from .declined import is_refusal_note

LANG = {"zh": "Chinese", "ja": "Japanese", "auto": "Chinese or Japanese"}
# Ghi chú khi một nhà cung cấp từ chối hẳn một dòng; cli nhận ra và đánh dấu 'declined' (không hỏi lại).
REFUSED_SRC = "[Không đọc: mô hình từ chối]"
REFUSED_VI = "[Không dịch: mô hình từ chối]"


class Usage:
    def __init__(self):
        self.input = 0
        self.output = 0
        self.cache_read = 0
        self.cache_write = 0
        self._lock = threading.Lock()

    def add(self, u):
        with self._lock:                                  # dịch song song: nhiều luồng cùng cộng dồn
            self.input += u.get("input", 0)
            self.output += u.get("output", 0)
            self.cache_read += u.get("cache_read", 0)
            self.cache_write += u.get("cache_write", 0)

    def __str__(self):
        return (f"tokens in={self.input} out={self.output} "
                f"cache_read={self.cache_read} cache_write={self.cache_write}")


def _png_bytes(path, max_w=1000):
    im = Image.open(path)
    if im.width > max_w:
        im = im.resize((max_w, max(1, im.height * max_w // im.width)))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _schema(field):
    return {"type": "object", "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, field: {"type": "string"}},
        "required": ["id", field]}}}, "required": ["items"]}


def _ask_split(prov, usage, model, system, group, build_parts, schema, field, refused_note, out):
    """Gọi mô hình cho một nhóm dòng. Nếu cả nhóm bị từ chối thì chia đôi để tách riêng dòng bị từ chối;
    một dòng đơn lẻ bị từ chối thì ghi lại ghi chú từ chối."""
    items, u, refused = prov.json_call(model, system, build_parts(group), schema)
    usage.add(u)
    if refused:
        if len(group) == 1:
            out[group[0]["id"]] = refused_note
            return
        mid = len(group) // 2
        for half in (group[:mid], group[mid:]):
            _ask_split(prov, usage, model, system, half, build_parts, schema, field, refused_note, out)
        return
    for i in items or []:
        if isinstance(i, dict) and "id" in i and field in i:
            out[i["id"]] = i[field]


def ocr_batch(prov, usage, model, src, cues, frames_dir):
    system = (
        f"You read hard-coded subtitles from cropped video frames. Each image is labelled with "
        f"an id. Transcribe the {LANG[src]} subtitle text exactly as shown, keeping a line break "
        f"between separate lines. Ignore watermarks, logos and scenery text that is clearly not "
        f"a subtitle. If an image has no subtitle, return an empty string. Do not translate."
    )

    def parts(group):
        p = []
        for c in group:
            p.append(("text", f"id {c['id']}:"))
            p.append(("image", _png_bytes(frames_dir / c["image"])))
        return p

    out = {}
    _ask_split(prov, usage, model, system, cues, parts, _schema("text"), "text", REFUSED_SRC, out)
    return out


def summarize(prov, usage, model, src, cues, hint=""):
    """Đọc lướt toàn bộ lời thoại và viết bản ghi chú ngữ cảnh (cốt truyện, nhân vật, cách xưng hô, thuật ngữ) để
    mọi lô dịch dùng chung. Trả về chuỗi rỗng nếu thất bại hoặc bị từ chối (khi đó dịch như bình thường)."""
    lines = [c["src"] for c in cues if (c.get("src") or "").strip()]
    text, total = [], 0
    step = max(1, -(-sum(len(x) for x in lines) // 60000))      # tối đa ~60k ký tự: bỏ bớt dòng đều đặn nếu dài hơn
    for i in range(0, len(lines), step):
        text.append(lines[i]); total += len(lines[i])
    system = (
        f"You prepare notes for a subtitle translator ({LANG[src]} -> Vietnamese). You are given the full dialogue of "
        f"one video, produced by speech recognition (it may contain wrong homophones). Write compact notes in "
        f"Vietnamese, at most 1200 characters, covering: (1) genre, setting and what happens overall; (2) the "
        f"characters you can infer (names, relationships) and which Vietnamese pronouns suit each pair "
        f"(anh/em, tôi/cậu, ông/cháu...); (3) recurring names and terms with the Vietnamese rendering to use "
        f"consistently; (4) speech-recognition errors you notice and the intended word. Do not translate the dialogue."
    )
    user = (f"User hint: {hint}\n\n" if hint else "") + "Dialogue:\n" + "\n".join(text)
    try:
        items, u, refused = prov.json_call(model, system, [("text", user)], _schema("note"))
    except Exception:                                           # ghi chú chỉ để hỗ trợ: lỗi thì bỏ qua
        return ""
    usage.add(u)
    if refused:
        return ""
    for i in items or []:
        if isinstance(i, dict) and (i.get("note") or "").strip():
            return i["note"].strip()[:1500]
    return ""


def translate_batch(prov, usage, model, src, cues, context, glossary, brief="", ahead=None):
    system = (
        f"You are a professional subtitle translator ({LANG[src]} -> Vietnamese) for films and "
        f"series. Translate each numbered line into natural, concise spoken Vietnamese suitable "
        f"for subtitles (at most 2 lines, about 42 characters per line; separate lines with \\n). "
        f"Keep names, forms of address and terminology consistent with the context and glossary. "
        f"The source may contain OCR or speech-recognition mistakes (wrong homophones, a sentence cut in the "
        f"middle); use the surrounding lines to infer the intended text and translate the sentence as a whole. "
        f"Return exactly one translation per id."
    )
    if brief:
        system += "\n\nNotes about this video (follow them for pronouns and names):\n" + brief
    if glossary:
        system += "\n\nGlossary (source = Vietnamese):\n" + glossary

    def parts(group):
        lines = []
        if context:
            lines.append("Context (lines just before; translation shown where already done; do NOT output):")
            lines += [f"{c['src']} => {c['vi']}" if (c.get("vi") or "").strip() else c["src"] for c in context]
            lines.append("")
        lines.append("Translate these:")
        lines += [f"[{c['id']}] {c['src']}" for c in group]
        if ahead:
            lines += ["", "Lines that come next (context only, do NOT output):"] + [c["src"] for c in ahead]
        return [("text", "\n".join(lines))]

    out = {}
    _ask_split(prov, usage, model, system, cues, parts, _schema("vi"), "vi", REFUSED_VI, out)
    return out


def translate_robust(prov, usage, model, src, group, context, glossary, sizes=(8, 3, 1), log=None,
                     brief="", ahead=None):
    """Dịch một nhóm dòng. Dòng nào trả về rỗng (lỗi, không phải từ chối) thì hỏi lại theo lô nhỏ hơn.

    Trả về (got, declined): bản dịch theo id, và tập id mà mô hình từ chối rõ ràng (không hỏi lại)."""
    got, declined = {}, set()

    def take(res, batch):
        for c in batch:
            vi = (res.get(c["id"]) or "").strip()
            if is_refusal_note(vi, c.get("src")):
                declined.add(c["id"])
            elif vi:
                got[c["id"]] = vi

    take(translate_batch(prov, usage, model, src, group, context, glossary, brief, ahead), group)
    for size in sizes:
        missing = [c for c in group if c["id"] not in got and c["id"] not in declined]
        if not missing:
            break
        if log:
            log(f"  {len(missing)} dòng trả về rỗng, hỏi lại theo lô {size}...")
        for i in range(0, len(missing), size):
            sub = missing[i:i + size]
            take(translate_batch(prov, usage, model, src, sub, context, glossary, brief, ahead), sub)
    return got, declined
