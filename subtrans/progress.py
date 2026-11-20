"""Tính phần trăm và thời gian còn lại từ các dòng tiến độ do cli in ra ("@@PROGRESS {...}")."""
import json
import time

PREFIX = "@@PROGRESS "


def parse_line(line):
    """Trả về dict {stage, name, done, total} nếu là dòng tiến độ, ngược lại None."""
    if not line.startswith(PREFIX):
        return None
    try:
        d = json.loads(line[len(PREFIX):])
        return {"stage": int(d["stage"]), "name": str(d["name"]), "done": int(d["done"]), "total": int(d["total"]),
                "indeterminate": bool(d.get("indeterminate"))}
    except (ValueError, KeyError, TypeError):
        return {}


class Tracker:
    """Ước lượng thời gian còn lại của bước đang chạy theo tốc độ gần đây (cửa sổ trượt)."""
    WINDOW = 30

    def __init__(self):
        self.reset()

    def reset(self):
        self.key = None
        self.samples = []
        self.t0 = self.d0 = None

    def update(self, key, done, total, now=None):
        """Trả về (tỉ lệ 0..1, số giây còn lại hoặc None nếu chưa đủ dữ liệu)."""
        now = time.monotonic() if now is None else now
        if key != self.key:
            self.key, self.samples, self.t0, self.d0 = key, [], now, done
        self.samples.append((now, done))
        del self.samples[:-self.WINDOW]
        if total <= 0:
            return 1.0, 0.0
        frac = max(0.0, min(1.0, done / total))
        if done >= total:
            return 1.0, 0.0
        (t1, d1), (t2, d2) = self.samples[0], self.samples[-1]
        rate = None
        if d2 > d1 and t2 - t1 >= 1.0:
            rate = (d2 - d1) / (t2 - t1)
        elif done > self.d0 and now - self.t0 >= 1.0:
            rate = (done - self.d0) / (now - self.t0)
        return frac, ((total - done) / rate if rate else None)


def fmt_duration(seconds):
    """'25 giây', '1 phút 20 giây', '1 giờ 05 phút' (làm tròn cho đỡ nhấp nháy)."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{max(5, 5 * round(s / 5))} giây"
    if s < 3600:
        m, r = divmod(5 * round(s / 5), 60)
        return f"{m} phút {r:02d} giây" if r else f"{m} phút"
    h, rem = divmod(s, 3600)
    return f"{h} giờ {rem // 60:02d} phút"
