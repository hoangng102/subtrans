"""Nhận dạng giọng nói: Whisper chạy trên máy (faster-whisper) hoặc Groq. Cùng một giao diện: nhận mảng âm thanh
16 kHz và trả về các đoạn {start, end, text, logprob, no_speech, comp} tính theo giây từ đầu đoạn âm thanh.

Khóa API chỉ được gửi tới Groq khi người dùng chọn Groq, và không bao giờ xuất hiện trong thông báo lỗi."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from . import audio, config, sysdeps
from .providers import ProviderError, _err_text

MODEL_DIR = sysdeps.data_dir() / "models"
LOCAL_MODELS = {                         # tên model -> dung lượng tải về xấp xỉ (MB)
    "base": 150, "small": 470, "medium": 1500, "large-v3-turbo": 1600,
}
DEFAULT_LOCAL_MODEL = "small"
GROQ_MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")
# Gợi ý chữ giản thể cho tiếng Trung (Whisper hay trộn giản thể và phồn thể)
LANG_PROMPT = {"zh": "以下是普通话的句子。"}


def _lang(code):
    return None if code in (None, "", "auto") else code


class LocalWhisper:
    name = "local"

    def __init__(self, model=DEFAULT_LOCAL_MODEL, log=print, on_status=None):
        """on_status(kind, done, total): kind = "download" (MB đã tải / MB ước tính) hoặc "load" (đang nạp model)."""
        if model not in LOCAL_MODELS:
            raise SystemExit(f"Model Whisper không hợp lệ: {model} (chọn một trong {', '.join(LOCAL_MODELS)})")
        self.model_name, self.log, self.model = model, log, None
        self.on_status = on_status or (lambda *a: None)

    # Tệp cần của faster-whisper (giống faster_whisper.utils.download_model)
    _PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

    def _repo(self):
        try:
            from faster_whisper.utils import _MODELS
            return _MODELS[self.model_name]
        except (ImportError, KeyError):
            return f"Systran/faster-whisper-{self.model_name}"

    def _resolve(self):
        """Trả về thư mục model; tải về nếu chưa có và báo tiến độ (MB đã tải / MB ước tính) qua on_status."""
        import huggingface_hub
        from tqdm.auto import tqdm
        kw = dict(cache_dir=str(MODEL_DIR), allow_patterns=self._PATTERNS)
        try:
            return huggingface_hub.snapshot_download(self._repo(), local_files_only=True, **kw)
        except Exception:                       # chưa có model trong bộ nhớ đệm
            pass
        expected = float(LOCAL_MODELS[self.model_name])
        self.log(f"  Lần đầu dùng model Whisper '{self.model_name}': đang tải khoảng {expected:.0f} MB "
                 f"(chỉ tải một lần, lưu ở {MODEL_DIR})...")
        self.on_status("download", 0.0, expected)
        state, owner = {}, self
        sink = open(os.devnull, "w")

        class Bar(tqdm):                        # chỉ để lấy số liệu; không in gì ra màn hình
            _last = 0.0

            def __init__(self, *a, **k):
                k.pop("name", None)
                k["file"] = sink
                super().__init__(*a, **k)

            def update(self, n=1):
                r = super().update(n)
                if self.unit == "B":
                    state[id(self)] = (self.n, self.total or 0)
                    now = time.monotonic()
                    if now - Bar._last >= 0.3:
                        Bar._last = now
                        # Hugging Face (xet) có thể mở hai thanh cho cùng một file (tải + ghép lại): lấy thanh lớn nhất
                        # thay vì cộng, kẻo số MB bị tính đôi.
                        done = max(v[0] for v in state.values()) / 1e6
                        total = max(max(v[1] for v in state.values()) / 1e6, expected * 0.9, done)
                        owner.on_status("download", done, total)
                return r

        try:
            path = huggingface_hub.snapshot_download(self._repo(), tqdm_class=Bar, **kw)
        finally:
            sink.close()
        done = max((v[0] for v in state.values()), default=0) / 1e6
        self.on_status("download", done, done)
        self.log("  Đã tải xong model Whisper.")
        return path

    def _load(self):
        if self.model is not None:
            return
        from faster_whisper import WhisperModel
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        path = self._resolve()
        self.on_status("load", 0, 0)            # nạp model vào bộ nhớ (vài giây)
        self.model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)

    def _run(self, samples, lang, vad):
        segs, _ = self.model.transcribe(
            samples, language=_lang(lang), beam_size=1, condition_on_previous_text=False,
            initial_prompt=LANG_PROMPT.get(lang), vad_filter=vad,
            vad_parameters=dict(threshold=0.35, min_silence_duration_ms=400, speech_pad_ms=200))
        return [{"start": s.start, "end": s.end, "text": s.text.strip(), "logprob": s.avg_logprob,
                 "no_speech": s.no_speech_prob, "comp": s.compression_ratio} for s in segs]

    def transcribe(self, samples, lang):
        self._load()
        out = self._run(samples, lang, vad=True)
        # Bộ lọc giọng nói (VAD) đôi khi loại hết khi giọng nhỏ hoặc thì thầm: nếu đoạn có tiếng mà VAD không thấy
        # gì thì thử lại không dùng VAD.
        if not out and len(samples) > 5 * audio.SR and float(np.sqrt((samples ** 2).mean())) > 0.01:
            out = self._run(samples, lang, vad=False)
        return out


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (fname, data, ctype) in files.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class GroqWhisper:
    name = "groq"

    def __init__(self, key, model=GROQ_MODELS[0], log=print):
        self.key, self.model, self.log = key, model, log
        self.base = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")

    def transcribe(self, samples, lang):
        fields = [("model", self.model), ("response_format", "verbose_json"), ("temperature", "0"),
                  ("timestamp_granularities[]", "segment")]
        if _lang(lang):
            fields.append(("language", lang))
        if LANG_PROMPT.get(lang):
            fields.append(("prompt", LANG_PROMPT[lang]))
        opus = audio.to_opus_bytes(samples)
        fileinfo = ("chunk.ogg", opus, "audio/ogg") if opus else ("chunk.wav", audio.to_wav_bytes(samples), "audio/wav")
        body, ctype = _multipart(fields, {"file": fileinfo})
        req = urllib.request.Request(self.base + "/audio/transcriptions", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + self.key, "Content-Type": ctype,
                                              "User-Agent": "SubTrans/1.0"})
        delay = 5.0
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    try:
                        wait = float(e.headers.get("Retry-After") or delay)
                    except ValueError:
                        wait = delay
                    time.sleep(min(wait, 60))
                    delay *= 2
                    continue
                raise ProviderError(_err_text(e.code, text).replace(self.key, "***")) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(f"Lỗi kết nối tới Groq: {e}".replace(self.key, "***")) from None
        return [{"start": float(s["start"]), "end": float(s["end"]), "text": (s.get("text") or "").strip(),
                 "logprob": s.get("avg_logprob", 0.0), "no_speech": s.get("no_speech_prob", 0.0),
                 "comp": s.get("compression_ratio", 1.0)} for s in data.get("segments", [])]


def make(engine, model=DEFAULT_LOCAL_MODEL, log=print, on_status=None):
    if engine == "groq":
        return GroqWhisper(config.load_api_key("groq"), log=log)
    return LocalWhisper(model, log=log, on_status=on_status)
