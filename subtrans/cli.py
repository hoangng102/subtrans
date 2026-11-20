import argparse
import json
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from difflib import SequenceMatcher

from . import asr, audio, config, export, frames, llm, providers, segmenter
from .declined import is_refusal_note, is_refusal_src, mark_declined
from .providers import ProviderError


def parse_crop(s):
    a, b = s.split("-")
    return float(a), float(b)


def norm(t):
    return re.sub(r"\s+", "", t or "")


def save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def progress(stage, name, done, total, indeterminate=False):
    """Dòng tiến độ có cấu trúc để cửa sổ chính vẽ thanh phần trăm và thời gian còn lại (không hiện trong nhật ký).
    indeterminate=True: chưa biết tổng (ví dụ đang nạp model), cửa sổ chính hiện thanh chạy và tên bước."""
    d = {"stage": stage, "name": name, "done": int(done), "total": int(total)}
    if indeterminate:
        d["indeterminate"] = True
    print("@@PROGRESS " + json.dumps(d, ensure_ascii=False), flush=True)


def model_status(stage):
    """Hàm báo trạng thái model Whisper (đang tải / đang nạp) thành dòng tiến độ."""
    def cb(kind, done, total):
        if kind == "download":
            progress(stage, "Tải model Whisper (MB)", round(done), round(total))
        else:
            progress(stage, "Nạp model Whisper vào bộ nhớ", 0, 0, indeterminate=True)
    return cb


def fmt_hms(seconds):
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} giờ {m:02d} phút {s:02d} giây"
    return f"{m} phút {s:02d} giây" if m else f"{s} giây"


def record_timing(args, video, data, timing, t_start, counts):
    """In bảng thời gian từng công đoạn và lưu vào meta["timing"] (giữ 20 lần chạy gần nhất) để lần sau tham khảo."""
    total = time.monotonic() - t_start
    try:
        vid_len = round(frames.probe(str(video))["duration"], 1)
    except Exception:                                   # ffprobe lỗi thì bỏ qua độ dài video
        vid_len = None
    entry = {"at": datetime.now().isoformat(timespec="seconds"), "video_seconds": vid_len,
             "ocr_engine": args.ocr_engine, "total": round(total, 1), **timing, **counts}
    data.setdefault("meta", {}).setdefault("timing", []).append(entry)
    del data["meta"]["timing"][:-20]
    parts = []
    speech = args.source == "speech"
    stages = ((("audio", "tách âm thanh"), ("asr", "nhận dạng giọng nói")) if speech
              else (("scan", "quét"), ("ocr", "đọc chữ"))) + (("translate", "dịch"),)
    for key, label in stages:
        if key in timing:
            parts.append(f"{label} {fmt_hms(timing[key])}")
        else:
            parts.append(f"{label}: bỏ qua (đã có dữ liệu)")
    extra = f" (video dài {fmt_hms(vid_len)})" if vid_len else ""
    print("Thời gian: " + " · ".join(parts) + f" · tổng {fmt_hms(total)}{extra}")
    detail = [f"{counts[k]} {lbl}" for k, lbl in (("cues", "cue"), ("ocr_local", "ảnh đọc bằng OCR cục bộ"),
                                                    ("ocr_cloud", "ảnh gửi mô hình AI"), ("translated", "dòng dịch"))
              if counts.get(k)]
    if detail:
        print("  Khối lượng: " + ", ".join(detail))


def add_common(p):
    p.add_argument("video")
    p.add_argument("--crop", default="0.75-1.0", help="vùng sub theo chiều cao, vd 0.78-1.0")
    p.add_argument("--fps", type=float, default=4)
    p.add_argument("--start", type=float, default=0, help="giây bắt đầu (để thử clip ngắn)")
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--mode", choices=["edge", "white", "bright"], default="edge",
                   help="edge: theo nét chữ, mọi màu/nền (mặc định); white: chữ trắng; bright: mọi màu sáng")
    p.add_argument("--bright", type=int, default=215)
    p.add_argument("--edge-thr", type=int, default=90)
    p.add_argument("--min-ratio", type=float, default=None)
    p.add_argument("--change", type=float, default=0.6)


def detect(args, workdir):
    info = frames.probe(args.video)
    y0, y1 = parse_crop(args.crop)
    fr = frames.iter_crop_frames(args.video, info, y0, y1, args.fps, 1000, args.start, args.duration)
    span = min(info["duration"] - args.start, args.duration or 1e12)
    total = max(1, int(span * args.fps))
    step = max(1, total // 200)
    name = "Quét tìm mốc sub"

    def counted(it):
        progress(1, name, 0, total)
        for i, item in enumerate(it, 1):
            if i % step == 0:
                progress(1, name, min(i, total), total)
            yield item
        progress(1, name, total, total)

    cues = frames.detect_cues(
        counted(fr), args.fps, workdir / "frames", args.mode, args.bright, args.min_ratio,
        change=args.change, edge_thr=args.edge_thr,
        log=lambda c: print(f"  cue {c['id']:4d}  {c['start']:8.2f} -> {c['end']:8.2f}"))
    meta = {"video": str(Path(args.video).resolve()), "width": info["width"],
            "height": info["height"], "crop": [y0, y1], "sig": detect_sig(args)}
    return {"meta": meta, "cues": cues}


def detect_sig(args):
    """Các tham số quyết định kết quả quét; đổi một trong số này thì phải quét lại."""
    return {"crop": args.crop, "mode": args.mode, "bright": args.bright, "min_ratio": args.min_ratio,
            "edge_thr": args.edge_thr, "algo": 2, "change": args.change, "fps": args.fps, "start": args.start, "duration": args.duration}


def merge_duplicates(cues, gap=0.6, sim=0.85):
    """Gộp cue liền kề có chữ (gần như) giống nhau, do một câu bị tách vì nhấp nháy/đổi nền."""
    out = []
    for c in cues:
        if (out and c["start"] - out[-1]["end"] <= gap and norm(c["src"])
                and SequenceMatcher(None, norm(out[-1]["src"]), norm(c["src"])).ratio() >= sim):
            out[-1]["end"] = c["end"]
            if len(c["src"]) > len(out[-1]["src"]):
                out[-1]["src"] = c["src"]
        else:
            out.append(dict(c))
    return out


def style_from_args(args):
    return {
        "font": args.font, "font_scale": args.font_scale,
        "text_color": args.text_color, "outline_color": args.outline_color,
        "outline_width": args.outline_width, "bg_color": args.bg_color,
        "bg_mode": args.bg_mode, "bg_opacity": args.bg_opacity,
        "bold": args.bold, "italic": args.italic, "shadow": args.shadow,
        "pos_auto": args.pos_y < 0, "pos_y": args.pos_y if args.pos_y >= 0 else export.DEFAULT_STYLE["pos_y"],
    }


CJK = re.compile(r"[぀-ヿ㐀-鿿]")


def report_declined(cues):
    ids = [c["id"] for c in cues if c.get("declined") and not (c.get("vi") or "").strip()]
    if ids:
        print(f"[LƯU Ý] {len(ids)} dòng bị mô hình từ chối đọc/dịch nên để trống, không đưa vào phụ đề "
              f"(id: {ids[:30]}). Tool không tự ép dịch lại các dòng này; bạn có thể tự gõ ở tab Chỉnh sửa.")


def needs_translation(c):
    """Có chữ gốc nhưng chưa có bản dịch dùng được (thiếu, rỗng, hoặc còn nguyên chữ Hán/Nhật)."""
    if c.get("declined"):
        return False
    src = (c.get("src") or "").strip()
    if not src:
        return False
    vi = (c.get("vi") or "").strip()
    return not vi or (vi == src and bool(CJK.search(src)))


def batches(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def translate_pending(args, client, usage, data, cpath, glossary):
    """Dịch các dòng chưa có bản dịch. Dòng nào mô hình trả về rỗng thì hỏi lại theo lô nhỏ hơn,
    và nếu vẫn không được thì để trống (có cảnh báo) để lần chạy sau thử lại, không điền chữ gốc."""
    cues = data["cues"]

    mark_declined(cues)
    pending = [c for c in cues if needs_translation(c)]
    done_tr = 0
    hint = (getattr(args, "hint", "") or "").strip()
    speech = data.get("meta", {}).get("source") == "speech"
    brief = ""
    if speech and len(cues) >= 8:
        meta = data["meta"]
        if meta.get("brief") and meta.get("brief_hint") == hint:      # đã có ghi chú ngữ cảnh: dùng lại
            brief = meta["brief"]
        else:
            progress(3, "Đọc lướt lời thoại để nắm ngữ cảnh", 0, 0, True)
            print("Đọc lướt toàn bộ lời thoại để ghi chú ngữ cảnh (cốt truyện, nhân vật, cách xưng hô)...")
            brief = llm.summarize(client, usage, args.tr_model, args.src, cues, hint)
            meta["brief"], meta["brief_hint"] = brief, hint
            save(cpath, data)
            print("  " + ("đã có ghi chú ngữ cảnh." if brief else "không tạo được ghi chú, dịch bình thường."))
    elif hint:
        brief = "User hint: " + hint
    if speech and hint and brief and not brief.startswith("User hint"):
        brief = "User hint: " + hint + "\n" + brief
    progress(3, "Dịch sang tiếng Việt", 0, len(pending))
    nctx = 8 if speech else 5
    pos = {id(c): i for i, c in enumerate(cues)}
    jobs = []
    for b in batches(pending, args.tr_batch):
        idx, end = pos[id(b[0])], pos[id(b[-1])] + 1
        # Các lô chạy cùng lúc nên không chờ bản dịch của lô trước: ngữ cảnh là các dòng ngay trước (kèm bản dịch nếu
        # đã có) và, với giọng nói, vài dòng ngay sau. Ghi chú ngữ cảnh chung (brief) giữ nhất quán xưng hô/tên riêng.
        context = [c for c in cues[max(0, idx - nctx):idx] if (c.get("src") or "").strip()]
        ahead = [c for c in cues[end:end + 6] if (c.get("src") or "").strip()] if speech else None
        jobs.append((b, [dict(c) for c in context], ahead))
    workers = max(1, min(int(getattr(args, "tr_workers", 8) or 1), len(jobs) or 1))
    t0 = time.monotonic()
    print(f"Dịch {len(pending)} dòng thành {len(jobs)} lô, chạy {workers} lô cùng lúc...")

    def work(job):
        b, context, ahead = job
        # Dòng mô hình từ chối rõ ràng thì tôn trọng, không hỏi lại; chỉ hỏi lại các dòng trả về rỗng.
        return llm.translate_robust(client, usage, args.tr_model, args.src, b, context, glossary, log=print,
                                    brief=brief, ahead=ahead)

    def apply(b, got, declined):
        nonlocal done_tr
        for c in b:
            if c["id"] in got:
                c["vi"] = got[c["id"]]
            elif c["id"] in declined:
                c["vi"], c["declined"] = "", True
        save(cpath, data)
        failed = [c["id"] for c in b if c["id"] not in got and c["id"] not in declined]
        print(f"  dịch {b[0]['id']}..{b[-1]['id']}  {usage}")
        done_tr += len(b)
        progress(3, "Dịch sang tiếng Việt", done_tr, len(pending))
        if failed:
            print(f"  [CẢNH BÁO] {len(failed)} dòng vẫn chưa có bản dịch (id: {failed[:20]}). "
                  f"Chạy lại hoặc dịch tay ở tab Chỉnh sửa.")

    if workers == 1:
        for job in jobs:
            apply(job[0], *work(job))
    else:
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(work, job): job for job in jobs}
            try:
                for fut in as_completed(futs):
                    apply(futs[fut][0], *fut.result())
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
    print(f"Dịch xong trong {time.monotonic() - t0:.0f} giây.")


def do_export(args, video, data, tag=""):
    mark_declined(data["cues"])
    cues = [c for c in data["cues"] if (c.get("vi") or "").strip()]
    missing = len(data["cues"]) - len(cues)
    if missing:
        print(f"[CẢNH BÁO] {missing} dòng chưa có bản dịch nên không được đưa vào file phụ đề.")
    report_declined(data["cues"])
    mid = ".test" if tag else ""
    # Mặc định chỉ xuất một file .ass (có màu chữ/viền/nền). .srt và chữ gốc chỉ xuất khi được yêu cầu.
    ass = video.with_suffix(f"{mid}.vi.ass")
    export.write_ass(cues, ass, data["meta"], style_from_args(args))
    print(f"Xong: {ass}")
    if getattr(args, "also_srt", False):
        srt = video.with_suffix(f"{mid}.vi.srt")
        export.write_srt(cues, srt)
        print(f"Xong (kèm .srt không có màu/viền): {srt}")
    if getattr(args, "also_src", False):
        # Phụ đề gốc: giữ toàn bộ chữ đã nhận diện, kể cả dòng mô hình không dịch.
        src_cues = [c for c in data["cues"] if (c.get("src") or "").strip()]
        if src_cues:
            src_srt = video.with_suffix(f"{mid}.src.srt")
            export.write_srt(src_cues, src_srt, key="src")
            print(f"Xong (chữ gốc, {len(src_cues)} dòng): {src_srt}")


def add_speech_args(p):
    p.add_argument("--source", choices=["hardsub", "speech"], default="hardsub",
                   help="hardsub: đọc chữ cứng trên hình; speech: nhận dạng giọng nói trong video")
    p.add_argument("--asr-engine", choices=["local", "groq"], default="local",
                   help="local: Whisper chạy trên máy (miễn phí, offline); groq: Whisper qua Groq (nhanh)")
    p.add_argument("--asr-model", default=asr.DEFAULT_LOCAL_MODEL, choices=list(asr.LOCAL_MODELS),
                   help="cỡ model Whisper khi chạy trên máy")
    p.add_argument("--asr-lang", choices=["zh", "ja", "auto"], default="auto", help="ngôn ngữ nói trong video")
    p.add_argument("--asr-workers", type=int, default=6, help="số đoạn âm thanh gửi Groq cùng lúc")
    p.add_argument("--hint", default="", help="gợi ý ngữ cảnh cho bản dịch (thể loại, quan hệ nhân vật, tên riêng)")


def speech_sig(args):
    """Các tham số quyết định kết quả nhận dạng giọng nói; đổi một trong số này thì phải nhận dạng lại."""
    return {"source": "speech", "engine": args.asr_engine,
            "model": args.asr_model if args.asr_engine == "local" else "groq",
            "lang": args.asr_lang, "start": args.start, "duration": args.duration, "algo": 1}


def run_asr(args, video, workdir, timing):
    """Tách âm thanh rồi nhận dạng giọng nói từng đoạn (kết quả mỗi đoạn được lưu để chạy lại không mất công).
    Trả về dữ liệu cues.json (cue không có ảnh, chữ gốc lấy từ giọng nói)."""
    wav = workdir / "audio.wav"
    t0 = time.monotonic()
    print("Bước 1/3: tách âm thanh...")
    progress(1, "Tách âm thanh", 0, 1)
    audio.extract_wav(video, wav, args.start, args.duration)
    progress(1, "Tách âm thanh", 1, 1)
    timing["audio"] = round(time.monotonic() - t0, 1)

    chunks = audio.plan_chunks(wav)
    sig, plan = speech_sig(args), [[round(a, 2), round(b, 2)] for a, b in chunks]
    rawp = workdir / "asr_raw.json"
    store = {"sig": sig, "plan": plan, "chunks": {}}
    if rawp.exists():
        old = json.loads(rawp.read_text(encoding="utf-8"))
        if old.get("sig") == sig and old.get("plan") == plan:
            store = old
    engine = asr.make(args.asr_engine, args.asr_model, log=print, on_status=model_status(2))
    label = "Nhận dạng giọng nói"
    t0 = time.monotonic()
    total = len(chunks)
    done = sum(1 for i in range(total) if str(i) in store["chunks"])
    print(f"Bước 2/3: nhận dạng giọng nói ({total} đoạn âm thanh"
          + (f", đã xong {done}" if done else "") + ") bằng "
          + ("Groq Whisper" if args.asr_engine == "groq" else f"Whisper '{args.asr_model}' trên máy") + "...")
    progress(2, label, done, total)
    failed = []
    todo = [(i, a, b) for i, (a, b) in enumerate(chunks) if str(i) not in store["chunks"]]

    def one(item):
        i, a, b = item
        return i, a, engine.transcribe(audio.read_samples(wav, a, b), args.asr_lang)

    def finish(i, a, segs):
        nonlocal done
        store["chunks"][str(i)] = [{**s, "start": s["start"] + a, "end": s["end"] + a} for s in segs]
        save(rawp, store)
        done += 1
        print(f"  đoạn {i + 1}/{total}: {len(segs)} câu")
        progress(2, label, done, total)

    def fail(i, e):
        msg = str(e)
        if "HTTP 401" in msg or "HTTP 403" in msg:
            raise SystemExit("Groq từ chối khóa API (sai khóa hoặc chưa có quyền). "
                             "Kiểm tra trong 'Quản lý khóa API'.")
        print(f"  [CẢNH BÁO] Đoạn {i + 1}/{total} lỗi: {msg}")
        failed.append(i)

    workers = max(1, min(int(getattr(args, "asr_workers", 6) or 1), len(todo) or 1)) if args.asr_engine == "groq" else 1
    if workers == 1:                         # Whisper chạy trên máy đã dùng hết nhân CPU nên không song song
        for item in todo:
            try:
                finish(*one(item))
            except ProviderError as e:
                fail(item[0], e)
    else:
        print(f"  gửi {workers} đoạn cùng lúc")
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(one, item): item for item in todo}
            try:
                for fut in as_completed(futs):
                    try:
                        finish(*fut.result())
                    except ProviderError as e:
                        fail(futs[fut][0], e)
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
    if failed:
        raise SystemExit(f"{len(failed)} đoạn âm thanh bị lỗi (xem cảnh báo ở trên). Kết quả các đoạn đã xong được giữ; "
                         "chạy lại để thử tiếp các đoạn còn thiếu.")
    timing["asr"] = round(time.monotonic() - t0, 1)

    off = args.start or 0.0
    raw = [{**s, "start": s["start"] + off, "end": s["end"] + off}
           for i in range(total) for s in store["chunks"][str(i)]]
    built = segmenter.build(raw)
    print(f"Whisper trả về {len(raw)} câu; sau khi lọc chữ bịa/độ tin cậy thấp và gộp/tách còn {len(built)} cue.")
    cues = [{"id": i, "start": c["start"], "end": c["end"], "src": c["src"], "ocr": "asr"}
            for i, c in enumerate(built)]
    info = frames.probe(str(video))
    meta = {"video": str(Path(video).resolve()), "width": info["width"], "height": info["height"],
            "crop": [0.8, 1.0], "sig": sig, "source": "speech"}
    try:
        wav.unlink()
    except OSError:
        pass
    return {"meta": meta, "cues": cues}


def preview_speech(args):
    """Nhận dạng thử một đoạn ngắn (mặc định 60 giây đầu), chỉ in kết quả, không ghi dữ liệu."""
    video = Path(args.video)
    workdir = video.with_suffix(".subtrans") / "preview"
    workdir.mkdir(parents=True, exist_ok=True)
    dur = args.duration or 60
    if not args.start:        # không chỉ định: thử ở khoảng 25% video (đầu video thường là nhạc/giới thiệu)
        try:
            total = frames.probe(str(video))["duration"]
            args.start = round(max(0.0, min(total * 0.25, total - dur)), 1)
        except Exception:
            args.start = 0.0
    wav = workdir / "audio.wav"
    print(f"Nhận dạng thử {dur:g} giây âm thanh từ giây {args.start:g}...")
    audio.extract_wav(video, wav, args.start, dur)
    engine = asr.make(args.asr_engine, args.asr_model, log=print, on_status=model_status(1))
    t0 = time.monotonic()
    try:
        segs = engine.transcribe(audio.read_samples(wav, 0, audio.duration(wav)), args.asr_lang)
    except ProviderError as e:
        raise SystemExit(f"Nhận dạng thử lỗi: {e}")
    off = args.start or 0.0
    built = segmenter.build([{**s, "start": s["start"] + off, "end": s["end"] + off} for s in segs])
    for c in built:
        print(f"  [{c['start']:8.1f} -> {c['end']:8.1f}] {c['src']}")
    print(f"Tổng: {len(built)} cue trong {dur:g} giây, mất {time.monotonic() - t0:.0f} giây. Kết quả này chỉ để xem thử, "
          "chưa lưu gì.")
    try:
        wav.unlink()
    except OSError:
        pass


def cmd_preview(args):
    if args.source == "speech":
        return preview_speech(args)
    workdir = Path(args.video).with_suffix(".subtrans") / "preview"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"Phát hiện cue (không gọi API), ảnh lưu ở {workdir / 'frames'}")
    data = detect(args, workdir)
    print(f"Tổng: {len(data['cues'])} cue. Mở thư mục frames để kiểm tra vùng crop/chữ.")


def cmd_run(args):
    video = Path(args.video)
    # Chế độ thử đoạn ngắn có thư mục và file xuất riêng, không đè lên bản dịch cả phim.
    tag = "_test" if (args.start or args.duration) else ""
    workdir = video.with_suffix(".subtrans" + tag)
    workdir.mkdir(exist_ok=True)
    cpath = workdir / "cues.json"

    if args.export_only:
        if not cpath.exists():
            print("Chưa có dữ liệu. Hãy bấm Dịch trước.")
            return
        data = json.loads(cpath.read_text(encoding="utf-8"))
        do_export(args, video, data, tag)
        return

    t_run = time.monotonic()
    timing, counts = {}, {}
    speech = args.source == "speech"
    data = None
    if cpath.exists() and not args.redetect:
        data = json.loads(cpath.read_text(encoding="utf-8"))
        if data.get("meta", {}).get("sig") != (speech_sig(args) if speech else detect_sig(args)):
            print("Tham số quét đã đổi (nguồn phụ đề/vùng sub/công cụ nhận dạng/đoạn thử), làm lại từ đầu.")
            data = None
        else:
            print(f"Dùng lại {cpath} ({len(data['cues'])} cue). Dùng --redetect để quét lại.")
    if data is None and speech:
        if args.dry_run:
            info = frames.probe(str(video))
            span = min(info["duration"] - args.start, args.duration or 1e12)
            print(f"[ước lượng] nhận dạng giọng nói {span / 60:.1f} phút âm thanh, khoảng "
                  f"{max(1, round(span / 300))} đoạn; sau đó dịch toàn bộ lời thoại tìm được.")
            return
        data = run_asr(args, video, workdir, timing)
        save(cpath, data)
    elif data is None:
        shutil.rmtree(workdir / "frames", ignore_errors=True)
        print("Bước 1/3: tìm mốc thời gian sub...")
        t0 = time.monotonic()
        data = detect(args, workdir)
        timing["scan"] = round(time.monotonic() - t0, 1)
        save(cpath, data)
    cues = data["cues"]

    todo_ocr = [] if speech else [c for c in cues if "src" not in c]
    todo_tr = [c for c in cues if needs_translation(c)]
    if args.dry_run:
        print(f"[ước lượng] {len(cues)} cue; cần đọc chữ {len(todo_ocr)} ảnh "
              f"({len(batches(todo_ocr, args.ocr_batch))} request); "
              f"cần dịch ~{len(todo_ocr) + len(todo_tr)} dòng.")
        return

    pool = providers.Pool()
    usage = llm.Usage()

    counts["cues"] = len(cues)
    t0 = time.monotonic()
    if todo_ocr:
        n_ocr = len(todo_ocr)
        if args.ocr_engine == "local":
            counts["ocr_local"] = n_ocr
            print("Bước 2/3: đọc chữ bằng OCR cục bộ (offline, không gọi mô hình nào)...")
            read_with_local(todo_ocr, workdir / "frames", cpath, data)
        else:
            if args.ocr_engine == "hybrid":
                print(f"Bước 2/3: đọc nhanh bằng OCR cục bộ (tin cậy >= {args.hybrid_score:g}); "
                      "dòng khó nhờ mô hình AI...")
                ok = read_with_local(todo_ocr, workdir / "frames", cpath, data, accept=args.hybrid_score,
                                     tag="local-fast")
                todo_ocr = [c for c in todo_ocr if "src" not in c]
                counts["ocr_local"] = ok
                print(f"  OCR cục bộ đọc chắc {ok} ảnh; {len(todo_ocr)} ảnh gửi mô hình AI.")
            counts["ocr_cloud"] = len(todo_ocr)
            print(f"Bước 2/3: đọc chữ bằng {providers.PROVIDERS[args.ocr_provider]} ({args.ocr_model})...")
            ocr_prov = pool.get(args.ocr_provider)
            done_ocr = 0
            progress(2, "Đọc chữ (mô hình AI)", 0, len(todo_ocr))
            for b in batches(todo_ocr, args.ocr_batch):
                res = llm.ocr_batch(ocr_prov, usage, args.ocr_model, args.src, b, workdir / "frames")
                for c in b:
                    c["src"] = (res.get(c["id"]) or "").strip()
                save(cpath, data)
                print(f"  OCR {b[0]['id']}..{b[-1]['id']}  {usage}")
                done_ocr += len(b)
                progress(2, "Đọc chữ (mô hình AI)", done_ocr, len(todo_ocr))
            refused = [c for c in todo_ocr if is_refusal_src(c.get("src"))]
            if refused and args.ocr_fallback:
                print(f"  {len(refused)} ảnh mô hình không đọc, chuyển sang OCR cục bộ để vẫn nhận diện đủ chữ...")
                read_with_local(refused, workdir / "frames", cpath, data)
        mark_declined(cues)
        data["cues"] = cues = merge_duplicates([c for c in cues if c.get("src") or c.get("declined")])
        save(cpath, data)
        timing["ocr"] = round(time.monotonic() - t0, 1)

    print(f"Bước 3/3: dịch sang tiếng Việt bằng {providers.PROVIDERS[args.tr_provider]} ({args.tr_model})...")
    counts["translated"] = sum(1 for c in data["cues"] if needs_translation(c))
    t0 = time.monotonic()
    translate_pending(args, pool.get(args.tr_provider), usage, data, cpath, load_glossary(video))
    timing["translate"] = round(time.monotonic() - t0, 1)

    do_export(args, video, data, tag)
    print(f"Tổng {usage}")
    record_timing(args, video, data, timing, t_run, counts)
    save(cpath, data)


def read_with_local(targets, frames_dir, cpath, data, accept=None, tag="local"):
    """Đọc chữ các cue bằng OCR cục bộ (song song). Chữ đọc được thay cho chữ gốc (đánh dấu ocr=tag).
    accept: chỉ nhận kết quả có điểm tin cậy >= accept (cue còn lại không bị đụng tới). Trả về số cue đã nhận."""
    from . import localocr
    if not localocr.available():
        print("  [CẢNH BÁO] Chưa cài OCR cục bộ: pip install rapidocr-onnxruntime")
        return 0
    jobs = [(c, frames_dir / c["image"]) for c in targets if c.get("image") and (frames_dir / c["image"]).is_file()]
    if not jobs:
        return 0
    got, done, lock = [0], [0], threading.Lock()
    label = "Đọc chữ (OCR cục bộ)"
    progress(2, label, 0, len(jobs))

    def on_done(i, text, score):
        c = jobs[i][0]
        with lock:
            done[0] += 1
            if accept is None or localocr.is_reliable(text, score, accept):
                c["src"], c["ocr"] = text.strip(), tag
                if c["src"]:
                    c.pop("declined", None)
                    got[0] += 1
            if done[0] % 5 == 0 or done[0] == len(jobs):
                progress(2, label, done[0], len(jobs))
            if done[0] % 25 == 0 or done[0] == len(jobs):
                save(cpath, data)
                print(f"  OCR cục bộ {done[0]}/{len(jobs)}")

    localocr.read_many([p for _, p in jobs], on_done=on_done)
    return got[0]


def load_glossary(video):
    for name in (Path(video).with_name("glossary.txt"), config.ROOT / "glossary.txt"):
        if name.is_file():
            return name.read_text(encoding="utf-8")
    return ""


def cmd_fix(args):
    """Chỉ dịch lại các dòng còn thiếu bản dịch trong dữ liệu đã có (không quét, không đọc chữ lại)."""
    video = Path(args.video)
    for tag in ("", "_test"):
        cpath = video.with_suffix(".subtrans" + tag) / "cues.json"
        if cpath.exists():
            break
    else:
        print("Chưa có dữ liệu cho video này. Hãy bấm Dịch trước.")
        return
    data = json.loads(cpath.read_text(encoding="utf-8"))
    if mark_declined(data["cues"]):
        save(cpath, data)
    if args.ocr_fallback:
        # Ảnh mà bước đọc chữ trước đây bị từ chối: đọc bằng OCR cục bộ để có đủ chữ nhận diện.
        unread = [c for c in data["cues"] if c.get("declined") and not (c.get("src") or "").strip() and c.get("image")]
        if unread:
            print(f"{len(unread)} ảnh chưa có chữ nhận diện, đọc bằng OCR cục bộ...")
            n = read_with_local(unread, cpath.parent / "frames", cpath, data)
            print(f"  đọc được {n}/{len(unread)} ảnh.")
    todo = [c for c in data["cues"] if needs_translation(c)]
    print(f"{len(todo)} dòng cần dịch lại trên tổng {len(data['cues'])} dòng.")
    usage = llm.Usage()
    if todo:
        translate_pending(args, providers.make(args.tr_provider), usage, data, cpath, load_glossary(video))
    do_export(args, video, data, tag)
    print(f"Tổng {usage}")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    d = export.DEFAULT_STYLE
    ap = argparse.ArgumentParser(prog="subtrans")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preview", help="chỉ tìm mốc thời gian, không gọi API (hoặc nhận dạng thử giọng nói)")
    add_common(p)
    add_speech_args(p)
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("run", help="đọc chữ hoặc nhận dạng giọng nói + dịch + xuất .srt/.ass")
    add_common(p)
    add_speech_args(p)
    p.add_argument("--src", choices=["zh", "ja", "auto"], default="auto")
    p.add_argument("--ocr-model", default=config.OCR_MODEL)
    p.add_argument("--ocr-engine", choices=["cloud", "claude", "local", "hybrid"], default="cloud",
                   help="cloud: mô hình đám mây (xem --ocr-provider); local: OCR cục bộ offline; "
                        "hybrid: OCR cục bộ trước, chỉ gửi dòng đọc không chắc cho mô hình đám mây")
    p.add_argument("--hybrid-score", type=float, default=0.9,
                   help="chế độ hybrid: điểm tin cậy tối thiểu để nhận kết quả OCR cục bộ")
    p.add_argument("--ocr-provider", choices=list(providers.PROVIDERS), default="claude")
    p.add_argument("--tr-provider", choices=list(providers.PROVIDERS), default="claude")
    p.add_argument("--no-ocr-fallback", dest="ocr_fallback", action="store_false",
                   help="tắt việc đọc bằng OCR cục bộ những ảnh Claude không đọc")
    p.add_argument("--also-srt", action="store_true", help="xuất kèm .srt không có màu/viền")
    p.add_argument("--also-src", action="store_true", help="xuất kèm chữ gốc (.src.srt)")
    p.add_argument("--tr-model", default=config.TRANSLATE_MODEL)
    p.add_argument("--ocr-batch", type=int, default=15)
    p.add_argument("--tr-batch", type=int, default=50)
    p.add_argument("--tr-workers", type=int, default=8, help="số lô dịch chạy cùng lúc")
    p.add_argument("--redetect", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--export-only", action="store_true", help="chỉ xuất lại file từ bản dịch đã có")
    p.add_argument("--font", default=d["font"])
    p.add_argument("--font-scale", type=int, default=d["font_scale"])
    p.add_argument("--text-color", default=d["text_color"])
    p.add_argument("--outline-color", default=d["outline_color"])
    p.add_argument("--outline-width", type=int, default=d["outline_width"])
    p.add_argument("--bg-color", default=d["bg_color"])
    p.add_argument("--bg-mode", choices=["none", "text", "strip"], default=d["bg_mode"])
    p.add_argument("--bg-opacity", type=int, default=d["bg_opacity"])
    p.add_argument("--bold", action="store_true")
    p.add_argument("--italic", action="store_true")
    p.add_argument("--shadow", type=int, default=d["shadow"])
    p.add_argument("--pos-y", type=float, default=-1,
                   help="vị trí dọc (%% chiều cao từ trên xuống); âm = theo dải sub gốc")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("fix", help="dịch lại các dòng còn thiếu bản dịch")
    p.add_argument("video")
    p.add_argument("--hint", default="", help="gợi ý ngữ cảnh cho bản dịch")
    p.add_argument("--src", choices=["zh", "ja", "auto"], default="auto")
    p.add_argument("--tr-model", default=config.TRANSLATE_MODEL)
    p.add_argument("--tr-provider", choices=list(providers.PROVIDERS), default="claude")
    p.add_argument("--tr-batch", type=int, default=50)
    p.add_argument("--tr-workers", type=int, default=8, help="số lô dịch chạy cùng lúc")
    p.add_argument("--no-ocr-fallback", dest="ocr_fallback", action="store_false")
    p.add_argument("--also-srt", action="store_true", help="xuất kèm .srt không có màu/viền")
    p.add_argument("--also-src", action="store_true", help="xuất kèm chữ gốc (.src.srt)")
    p.add_argument("--font", default=d["font"])
    p.add_argument("--font-scale", type=int, default=d["font_scale"])
    p.add_argument("--text-color", default=d["text_color"])
    p.add_argument("--outline-color", default=d["outline_color"])
    p.add_argument("--outline-width", type=int, default=d["outline_width"])
    p.add_argument("--bg-color", default=d["bg_color"])
    p.add_argument("--bg-mode", choices=["none", "text", "strip"], default=d["bg_mode"])
    p.add_argument("--bg-opacity", type=int, default=d["bg_opacity"])
    p.add_argument("--bold", action="store_true")
    p.add_argument("--italic", action="store_true")
    p.add_argument("--shadow", type=int, default=d["shadow"])
    p.add_argument("--pos-y", type=float, default=-1)
    p.set_defaults(fn=cmd_fix)

    args = ap.parse_args()
    args.fn(args)





