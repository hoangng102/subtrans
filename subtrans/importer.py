"""Nhập file phụ đề (srt/ass/vtt/txt) vào dữ liệu của một video: ghép bản dịch tay vào đúng dòng."""
import re
from pathlib import Path

SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".txt"}
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_TAGS = re.compile(r"\{[^}]*\}|<[^>]+>")


def read_text(path):
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _secs(m):
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def _clean(text):
    text = _TAGS.sub("", text).replace("\\N", "\n").replace("\\n", "\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_srt_vtt(text):
    entries = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                ma, mb = _TIME.search(a), _TIME.search(b)
                if ma and mb:
                    body = _clean("\n".join(lines[i + 1:]))
                    if body:
                        entries.append({"start": _secs(ma), "end": _secs(mb), "text": body})
                break
    return entries


def parse_ass(text):
    entries, fmt = [], ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    for line in text.replace("\r\n", "\n").split("\n"):
        low = line.strip().lower()
        if low.startswith("format:") and "start" in low and "text" in low:
            fmt = [x.strip().lower() for x in line.split(":", 1)[1].split(",")]
        elif low.startswith("dialogue:"):
            parts = line.split(":", 1)[1].split(",", len(fmt) - 1)
            if len(parts) < len(fmt):
                continue
            row = dict(zip(fmt, parts))
            raw = row["text"]
            if "\\p1" in raw or "\\p2" in raw:       # nét vẽ (hộp nền che hardsub), không phải chữ
                continue
            ma, mb = _TIME.search(row["start"]), _TIME.search(row["end"])
            body = _clean(raw)
            if ma and mb and body:
                entries.append({"start": _secs(ma), "end": _secs(mb), "text": body})
    return entries


def parse_txt(text):
    return [{"start": None, "end": None, "text": line.strip()}
            for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


def parse_file(path):
    ext = Path(path).suffix.lower()
    text = read_text(path)
    if ext in (".ass", ".ssa"):
        entries = parse_ass(text)
    elif ext == ".txt":
        entries = parse_txt(text)
    else:
        entries = parse_srt_vtt(text)
    timed = [e for e in entries if e["start"] is not None]
    timed.sort(key=lambda e: e["start"])
    return timed if len(timed) == len(entries) else entries


# ---------------------------------------------------------------- ghép vào dòng phụ đề
def _match_time(cues, entries):
    """entry index -> cue index, theo độ chồng thời gian (hoặc lệch thời điểm bắt đầu rất nhỏ)."""
    order = sorted(range(len(cues)), key=lambda i: cues[i]["start"])
    out = {}
    for ei, e in enumerate(entries):
        best = None
        for ci in order:
            c = cues[ci]
            if c["start"] > e["end"] + 1.5:
                break
            if c["end"] < e["start"] - 1.5:
                continue
            overlap = max(0.0, min(e["end"], c["end"]) - max(e["start"], c["start"]))
            shortest = max(0.001, min(e["end"] - e["start"], c["end"] - c["start"]))
            score, dstart = overlap / shortest, abs(e["start"] - c["start"])
            if score >= 0.4 or dstart <= 0.6:
                key = score - 0.1 * dstart
                if best is None or key > best[0]:
                    best = (key, ci)
        if best:
            out[ei] = best[1]
    return out


def make_plan(cues, entries, mode="time", overwrite=False, add_new=False):
    """Tính trước kết quả nhập (chưa sửa gì). Trả về dict: actions, unmatched, error, stats."""
    plan = {"actions": [], "unmatched": [], "error": None, "mode": mode, "add_new": add_new}
    timed = all(e["start"] is not None for e in entries)
    if mode == "time" and not timed:
        plan["error"] = "File không có thời gian (txt). Hãy chọn ghép 'Theo thứ tự dòng'."
        return plan
    assigned = {}                      # cue index -> [entry index]
    if mode == "time":
        for ei, ci in _match_time(cues, entries).items():
            assigned.setdefault(ci, []).append(ei)
        plan["unmatched"] = [ei for ei in range(len(entries)) if ei not in {e for v in assigned.values() for e in v}]
    else:
        order = sorted(range(len(cues)), key=lambda i: cues[i]["start"])
        empty = [i for i in order if not (cues[i].get("vi") or "").strip()]
        for targets in (empty, order):
            if len(entries) == len(targets):
                for ei, ci in enumerate(targets):
                    assigned[ci] = [ei]
                break
        else:
            plan["error"] = (f"Số dòng trong file ({len(entries)}) không khớp số dòng đang trống bản dịch "
                             f"({len(empty)}) cũng không khớp tổng số dòng ({len(order)}).")
            return plan
    for ci in sorted(assigned):
        text = "\n".join(entries[ei]["text"] for ei in sorted(assigned[ci], key=lambda k: entries[k]["start"] or 0))
        cur = (cues[ci].get("vi") or "").strip()
        if cur == text.strip():
            kind = "same"
        elif not cur:
            kind = "fill"
        else:
            kind = "overwrite" if overwrite else "keep"
        plan["actions"].append({"cue": ci, "text": text, "kind": kind})
    plan["stats"] = {k: sum(1 for a in plan["actions"] if a["kind"] == k) for k in ("fill", "overwrite", "keep", "same")}
    plan["stats"]["unmatched"] = len(plan["unmatched"])
    plan["stats"]["entries"] = len(entries)
    return plan


def apply_plan(cues, entries, plan):
    """Ghi vào danh sách cue. Trả về số dòng đã điền/ghi đè và số dòng mới thêm."""
    changed = 0
    for a in plan["actions"]:
        if a["kind"] in ("fill", "overwrite"):
            c = cues[a["cue"]]
            c["vi"], c["manual"] = a["text"], True
            c.pop("declined", None)
            changed += 1
    added = 0
    if plan.get("add_new") and plan["mode"] == "time":
        nid = max([c.get("id", 0) for c in cues] + [-1]) + 1
        for ei in plan["unmatched"]:
            e = entries[ei]
            cues.append({"id": nid, "start": round(e["start"], 3), "end": round(e["end"], 3),
                         "image": None, "src": "", "vi": e["text"], "manual": True})
            nid += 1
            added += 1
        cues.sort(key=lambda c: c["start"])
    return changed, added
