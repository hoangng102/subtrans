import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


def probe(video: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", video],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    s = data["streams"][0]
    return {"width": int(s["width"]), "height": int(s["height"]),
            "duration": float(data["format"]["duration"])}


def iter_crop_frames(video, info, y0, y1, fps, width_out, start=0.0, duration=None):
    """Yield (time_sec, rgb array) for the subtitle strip of the video."""
    w, h = info["width"], info["height"]
    crop_y = round(h * y0)
    crop_h = round(h * (y1 - y0))
    scale = min(1.0, width_out / w)
    out_w = max(2, int(w * scale) // 2 * 2)
    out_h = max(2, int(crop_h * scale) // 2 * 2)
    vf = f"fps={fps},crop={w}:{crop_h}:0:{crop_y},scale={out_w}:{out_h}"
    cmd = ["ffmpeg", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", video]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = out_w * out_h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(out_h, out_w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def text_mask(img: np.ndarray, mode: str, bright: int, edge_thr: int = 90) -> np.ndarray:
    if mode == "edge":
        # Cạnh nét chữ (chữ + viền tương phản mạnh), không phụ thuộc màu chữ hay độ sáng nền.
        g = img.astype(np.int16).sum(axis=2) // 3
        gx = np.abs(g[:, 1:] - g[:, :-1])[:-1]
        gy = np.abs(g[1:, :] - g[:-1, :])[:, :-1]
        return (gx > edge_thr) | (gy > edge_thr)
    if mode == "white":
        return img.min(axis=2) >= bright
    gray = (img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114)
    return gray >= bright


def _grow(m: np.ndarray) -> np.ndarray:
    g = m.copy()
    g[1:] |= m[:-1]
    g[:-1] |= m[1:]
    g[:, 1:] |= m[:, :-1]
    g[:, :-1] |= m[:, 1:]
    return g


@dataclass
class _Open:
    start: float
    last: float
    best_ratio: float
    best_img: np.ndarray
    prev_mask: np.ndarray


def detect_cues(frames, fps, frames_dir: Path, mode="edge", bright=215,
                min_ratio=None, max_ratio=0.35, change=0.5, min_dur=0.4, edge_thr=90,
                gap_frames=None, log=None):
    """Find when subtitle text appears/changes, saving one representative image per cue.

    Cố ý thiên về tách nhiều cue (mỗi khoảng trống dù ngắn đều tách): các cue trùng chữ
    sẽ được gộp lại sau bước đọc chữ, còn gộp nhầm hai câu thì mất hẳn một câu.
    """
    edge = mode == "edge"
    if min_ratio is None:
        min_ratio = 0.002 if edge else 0.004
    if gap_frames is None:
        gap_frames = 1 if edge else 2
    frames_dir.mkdir(parents=True, exist_ok=True)
    cues = []
    cur = None
    gap = 0
    ema = None   # cạnh luôn hiện diện (watermark, logo) sẽ bị loại khỏi mặt nạ

    def close(end):
        nonlocal cur
        if end - cur.start >= min_dur:
            cid = len(cues)
            path = frames_dir / f"{cid:05d}.png"
            Image.fromarray(cur.best_img).save(path)
            cues.append({"id": cid, "start": round(cur.start, 3), "end": round(end, 3),
                         "image": path.name})
            if log:
                log(cues[-1])
        cur = None

    t = 0.0
    for t, img in frames:
        mask = text_mask(img, mode, bright, edge_thr)
        if edge:
            if ema is None:
                ema = np.zeros(mask.shape, np.float32)
            static = ema > 0.8
            raw = mask
            if static.any():
                mask = mask & ~_grow(static)
            ema += 0.03 * (raw - ema)
        ratio = float(mask.mean())
        has = min_ratio <= ratio <= max_ratio
        if has:
            gap = 0
            if cur is not None:
                union = max(int(mask.sum()), int(cur.prev_mask.sum()), 1)
                diff = int(np.logical_xor(mask, cur.prev_mask).sum()) / union
                if diff > change:
                    close(t)
            if cur is None:
                cur = _Open(t, t, ratio, img.copy(), mask)
            else:
                cur.last = t
                cur.prev_mask = mask
                if ratio >= cur.best_ratio:
                    cur.best_ratio, cur.best_img = ratio, img.copy()
        elif cur is not None:
            gap += 1
            if gap >= gap_frames:
                close(cur.last + 1 / fps)
                gap = 0
    if cur is not None:
        close(cur.last + 1 / fps)
    return cues
