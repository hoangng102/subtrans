"""Tách âm thanh từ video và chia thành các đoạn tại chỗ im lặng để nhận dạng giọng nói."""
import io
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import sysdeps

SR = 16000
NO_WINDOW = sysdeps.NO_WINDOW
FRAME = 0.05            # độ dài khung đo năng lượng (giây)


PARALLEL_MIN = 600.0     # video ngắn hơn (giây) thì tách một lượt cho đơn giản


def _probe_duration(video):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
        return float(r.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _extract_part(video, out, t0, length):
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(video), "-t", f"{length:.3f}",
           "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not Path(out).is_file():
        raise OSError(r.stderr.decode("utf-8", "replace")[-200:])


def extract_wav_parallel(video, out, start=0.0, duration=None, workers=None):
    """Chia video thành nhiều đoạn thời gian, mỗi đoạn tách bằng một ffmpeg riêng chạy cùng lúc rồi nối lại
    (nhanh hơn nhiều với video dài vì giải mã âm thanh một luồng là điểm nghẽn). Trả về None nếu không dùng được."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    total = _probe_duration(video)
    if not total:
        return None
    span = min(total - (start or 0.0), duration) if duration else total - (start or 0.0)
    if span < PARALLEL_MIN:
        return None
    n = max(2, min(workers or (os.cpu_count() or 4), 8, int(span // 120)))
    length = span / n
    out = Path(out)
    parts = [out.with_name(f"{out.stem}.part{i}.wav") for i in range(n)]
    try:
        with ThreadPoolExecutor(n) as ex:
            futs = [ex.submit(_extract_part, video, parts[i], (start or 0.0) + i * length,
                              length if i < n - 1 else span - length * (n - 1)) for i in range(n)]
            for f in futs:
                f.result()
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            for p in parts:
                with wave.open(str(p), "rb") as r:
                    while True:
                        blk = r.readframes(SR * 60)
                        if not blk:
                            break
                        w.writeframes(blk)
    except (OSError, wave.Error):
        return None
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
    return out


def extract_wav(video, out, start=0.0, duration=None):
    """Trích âm thanh mono 16 kHz 16-bit ra file WAV. Báo lỗi dễ hiểu nếu video không có âm thanh."""
    got = extract_wav_parallel(video, out, start, duration)
    if got and Path(out).stat().st_size > 1000:
        return got
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 or not Path(out).is_file() or Path(out).stat().st_size < 1000:
        if "does not contain any stream" in err or "matches no streams" in err:
            raise SystemExit("Video này không có luồng âm thanh nên không thể tạo phụ đề từ giọng nói.")
        raise SystemExit("Không tách được âm thanh: " + err.strip()[-200:])
    return Path(out)


def duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def read_samples(path, t0, t1):
    """Đọc đoạn [t0, t1) giây của file WAV thành mảng float32 trong [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        w.setpos(min(int(t0 * sr), w.getnframes()))
        n = max(0, int((t1 - t0) * sr))
        raw = w.readframes(n)
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def to_wav_bytes(samples):
    """Mảng float32 -> bytes WAV 16-bit mono 16 kHz (để gửi lên dịch vụ đám mây)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def to_opus_bytes(samples, bitrate="32k"):
    """Nén đoạn âm thanh thành Ogg/Opus (nhỏ hơn WAV ~15 lần) để tải lên nhanh. Trả về None nếu ffmpeg không nén được."""
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
    cmd = ["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
           "-c:a", "libopus", "-b:a", bitrate, "-application", "voip", "-f", "ogg", "pipe:1"]
    try:
        r = subprocess.run(cmd, input=pcm, capture_output=True, creationflags=NO_WINDOW, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 and len(r.stdout) > 200 else None


def _energy(path):
    """Năng lượng (RMS) mỗi khung 50 ms, đọc từng khối để không tốn bộ nhớ."""
    out = []
    step = int(FRAME * SR)
    with wave.open(str(path), "rb") as w:
        while True:
            raw = w.readframes(step * 1200)               # ~60 giây một khối
            if not raw:
                break
            x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
            n = len(x) // step
            if n:
                out.append(np.sqrt((x[:n * step].reshape(n, step) ** 2).mean(axis=1)))
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def plan_chunks(path, target=300.0, search=15.0, min_tail=20.0):
    """Chia âm thanh thành các đoạn dài khoảng `target` giây, mỗi điểm cắt đặt vào chỗ yên lặng nhất trong
    khoảng ±`search` giây quanh mốc dự kiến. Trả về danh sách (bắt đầu, kết thúc) tính bằng giây."""
    total = duration(path)
    if total <= target + min_tail:
        return [(0.0, total)]
    env = _energy(path)
    cuts = [0.0]
    ideal = target
    while ideal < total - min_tail:
        lo, hi = int(max(cuts[-1] + 30, ideal - search) / FRAME), int(min(total - min_tail, ideal + search) / FRAME)
        if hi <= lo:
            cut = ideal
        else:
            seg = env[lo:hi]
            # khung yên lặng nhất; nếu có nhiều khung gần bằng nhau lấy khung giữa cho chắc
            quiet = np.flatnonzero(seg <= seg.min() * 1.05 + 1e-6)
            cut = (lo + int(np.median(quiet))) * FRAME
        cuts.append(cut)
        ideal = cut + target
    cuts.append(total)
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
