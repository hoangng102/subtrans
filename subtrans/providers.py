"""Các nhà cung cấp mô hình (Claude, OpenAI, Gemini và nhiều nhà khác) sau cùng một giao diện: gửi chữ + ảnh, nhận JSON.

OpenAI, Gemini và các nhà cung cấp tương thích OpenAI (OpenRouter, Grok, DeepSeek, Mistral, Groq, Qwen, Kimi, Ollama)
gọi thẳng qua HTTP (thư viện chuẩn), không cần cài thêm gói. Khóa API lấy từ config và
không bao giờ xuất hiện trong thông báo lỗi. Nếu nhà cung cấp từ chối nội dung, kết quả được báo là
`refused=True`; tool không đổi cài đặt an toàn của họ và không tự chuyển sang nhà khác.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

from . import config

# Nhà cung cấp tương thích OpenAI (giao thức /chat/completions): địa chỉ, tên biến khóa, có đọc được ảnh không.
# Tên model chỉ là gợi ý ban đầu và có thể đã cũ: bấm "Tải danh sách model" để lấy danh sách thật của tài khoản.
COMPAT = {
    "openrouter": dict(label="OpenRouter (nhiều model)", base="https://openrouter.ai/api/v1",
                       env=("OPENROUTER_API_KEY",), base_env="OPENROUTER_BASE_URL", vision=True,
                       model="openai/gpt-4o-mini",
                       suggested=["openai/gpt-4o-mini", "google/gemini-2.5-flash", "anthropic/claude-sonnet-4.5",
                                  "qwen/qwen2.5-vl-72b-instruct", "deepseek/deepseek-chat"]),
    "xai": dict(label="Grok (xAI)", base="https://api.x.ai/v1", env=("XAI_API_KEY",), base_env="XAI_BASE_URL",
                vision=True, model="grok-4", suggested=["grok-4", "grok-3", "grok-3-mini"]),
    "deepseek": dict(label="DeepSeek", base="https://api.deepseek.com/v1", env=("DEEPSEEK_API_KEY",),
                     base_env="DEEPSEEK_BASE_URL", vision=False, model="deepseek-chat",
                     suggested=["deepseek-chat", "deepseek-reasoner"]),
    "mistral": dict(label="Mistral", base="https://api.mistral.ai/v1", env=("MISTRAL_API_KEY",),
                    base_env="MISTRAL_BASE_URL", vision=True, model="mistral-small-latest",
                    suggested=["mistral-small-latest", "mistral-large-latest", "pixtral-large-latest"]),
    "groq": dict(label="Groq (chạy Llama nhanh)", base="https://api.groq.com/openai/v1", env=("GROQ_API_KEY",),
                 base_env="GROQ_BASE_URL", vision=True, model="meta-llama/llama-4-scout-17b-16e-instruct",
                 suggested=["meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile"]),
    "qwen": dict(label="Qwen (Alibaba)", base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                 env=("DASHSCOPE_API_KEY",), base_env="DASHSCOPE_BASE_URL", vision=True, model="qwen-vl-max",
                 text_model="qwen-plus", suggested=["qwen-plus", "qwen-max", "qwen-vl-max", "qwen-vl-plus"]),
    "moonshot": dict(label="Kimi (Moonshot)", base="https://api.moonshot.ai/v1", env=("MOONSHOT_API_KEY",),
                     base_env="MOONSHOT_BASE_URL", vision=False, model="kimi-k2-0905-preview",
                     suggested=["kimi-k2-0905-preview", "moonshot-v1-8k"]),
    "ollama": dict(label="Ollama (chạy trên máy bạn)", base="http://localhost:11434/v1", env=("OLLAMA_API_KEY",),
                   base_env="OLLAMA_BASE_URL", vision=True, key_required=False, model="llama3.2-vision",
                   text_model="llama3.1", suggested=["llama3.2-vision", "qwen2.5vl", "llama3.1"]),
}

PROVIDERS = {"claude": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Gemini (Google)",
             **{k: v["label"] for k, v in COMPAT.items()}}
PROVIDER_OF_LABEL = {v: k for k, v in PROVIDERS.items()}
# Chỉ những nhà cung cấp đọc được ảnh mới dùng được cho bước đọc chữ (OCR).
VISION = {"claude", "openai", "gemini", *(k for k, v in COMPAT.items() if v["vision"])}
VISION_LABEL_OF = {k: v for k, v in PROVIDERS.items() if k in VISION}
# Bước đọc chữ còn có thêm lựa chọn OCR cục bộ (RapidOCR, chạy trên máy, không gọi mô hình nào).
LOCAL_LABEL = "OCR cục bộ (không gọi mô hình)"
OCR_PROVIDER_OF_LABEL = {**{v: k for k, v in VISION_LABEL_OF.items()}, LOCAL_LABEL: "local"}
DEFAULT_MODELS = {"claude": "claude-sonnet-5-5", "openai": "gpt-4o", "gemini": "gemini-flash-lite-latest",
                  **{k: v["model"] for k, v in COMPAT.items()}}


def default_model(prov, vision=False):
    """Model mặc định khi đổi nhà cung cấp; bước dịch có thể dùng model chỉ-chữ rẻ hơn."""
    if not vision and prov in COMPAT and COMPAT[prov].get("text_model"):
        return COMPAT[prov]["text_model"]
    return DEFAULT_MODELS[prov]


def model_belongs(prov, model):
    """Tên model có vẻ thuộc nhà cung cấp này không (để biết có cần đổi về model mặc định khi đổi nhà cung cấp)."""
    m = (model or "").lower()
    if not m:
        return False
    if prov == "claude":
        return m.startswith("claude")
    if prov == "openai":
        return m.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))
    if prov == "gemini":
        return m.startswith("gemini")
    if prov == "openrouter":
        return "/" in m
    if prov == "groq":
        return m.startswith(("llama", "meta-llama", "mixtral", "gemma", "qwen/", "openai/", "moonshotai/", "deepseek-r1"))
    if prov == "ollama":
        return not m.startswith(("claude", "gpt", "gemini", "grok", "deepseek", "mistral-", "qwen-", "kimi"))
    prefixes = {"xai": ("grok",), "deepseek": ("deepseek",), "mistral": ("mistral", "pixtral", "ministral", "magistral"),
                "qwen": ("qwen", "qwq"), "moonshot": ("kimi", "moonshot")}
    return m.startswith(prefixes.get(prov, ()))
# Gợi ý ban đầu (tên "-latest" của Gemini luôn trỏ tới bản đang dùng được). Có model nằm trong danh sách của
# nhà cung cấp nhưng tài khoản mới không dùng được (vd gemini-2.5-flash), nên hãy thử bằng "Dịch lại" một dòng.
SUGGESTED = {
    "claude": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
    "openai": ["gpt-4o", "gpt-5-mini", "gpt-5", "gpt-4.1", "gpt-4o-mini"],
    "gemini": ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-pro-latest", "gemini-3.8-flash"],
    **{k: v["suggested"] for k, v in COMPAT.items()},
}


class ProviderError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _err_text(code, body):
    try:
        e = json.loads(body).get("error", {})
        msg = e.get("message") if isinstance(e, dict) else str(e)
    except ValueError:
        msg = body
    return f"HTTP {code}: {(msg or body or '').strip()[:300]}"


def _http(method, url, headers, body=None, timeout=300):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "SubTrans/1.0", **headers})
    delay = 3.0
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
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
            raise ProviderError(_err_text(e.code, text)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
            # Hết thời gian chờ (model suy luận chậm) chỉ thử lại một lần để không treo hàng chục phút.
            if attempt < (1 if timed_out else 4):
                time.sleep(delay)
                delay *= 2
                continue
            raise ProviderError(("Hết thời gian chờ phản hồi" if timed_out else "Lỗi kết nối") + f": {e}") from None


def _strict(schema):
    """Lược đồ JSON dạng 'strict' của OpenAI: không cho thuộc tính thừa, mọi thuộc tính đều bắt buộc."""
    s = dict(schema)
    if s.get("type") == "object":
        s["properties"] = {k: _strict(v) for k, v in s["properties"].items()}
        s["required"] = list(s["properties"])
        s["additionalProperties"] = False
    elif s.get("type") == "array":
        s["items"] = _strict(s["items"])
    return s


def _gemini_schema(schema):
    """Lược đồ của Gemini: kiểu viết hoa, không có additionalProperties."""
    s = {"type": schema["type"].upper()}
    if "properties" in schema:
        s["properties"] = {k: _gemini_schema(v) for k, v in schema["properties"].items()}
    if "required" in schema:
        s["required"] = schema["required"]
    if "items" in schema:
        s["items"] = _gemini_schema(schema["items"])
    return s


def _parse_items(text):
    try:
        obj = json.loads(text or "")
    except ValueError:
        return None
    return obj.get("items") if isinstance(obj, dict) else None


class ClaudeProvider:
    name = "claude"

    def __init__(self, key):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key, max_retries=5)

    def json_call(self, model, system, parts, schema):
        content = []
        for kind, val in parts:
            if kind == "text":
                content.append({"type": "text", "text": val})
            else:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                             "data": _b64(val)}})
        tool = {"name": "submit", "description": "Submit the results.", "input_schema": schema}
        system += "\n\nAlways respond by calling the `submit` tool, with no other text."
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for attempt in range(3):
            try:
                resp = self.client.messages.create(
                    model=model, max_tokens=4096,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    tools=[tool], tool_choice={"type": "auto"},
                    messages=[{"role": "user", "content": content}])
            except self._anthropic.APIConnectionError:
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
                continue
            u = resp.usage
            usage = {"input": u.input_tokens, "output": u.output_tokens,
                     "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                     "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
            if resp.stop_reason == "refusal":
                return None, usage, True
            blocks = [b for b in resp.content if b.type == "tool_use"]
            if blocks:
                return blocks[0].input.get("items"), usage, False
        return None, usage, False

    def list_models(self):
        return [m.id for m in self.client.models.list(limit=100)]


class OpenAIProvider:
    name = "openai"
    use_schema = True          # json_schema 'strict' (OpenAI); các nhà tương thích dùng json_object cho chắc

    def __init__(self, key):
        self.key = key
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def _headers(self):
        return {"Authorization": "Bearer " + self.key} if self.key else {}

    def json_call(self, model, system, parts, schema):
        content = []
        for kind, val in parts:
            if kind == "text":
                content.append({"type": "text", "text": val})
            else:
                content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(val)}})
        system += "\n\nReply with a JSON object of the form {\"items\": [...]} and nothing else."
        body = {"model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "response_format": ({"type": "json_schema",
                                     "json_schema": {"name": "submit", "schema": _strict(schema), "strict": True}}
                                    if self.use_schema else {"type": "json_object"})}
        try:
            data = _http("POST", self.base + "/chat/completions", self._headers(), body)
        except ProviderError as e:
            if "response_format" not in str(e) and "json_schema" not in str(e):
                raise
            if body["response_format"]["type"] == "json_schema":
                body["response_format"] = {"type": "json_object"}     # model cũ không hỗ trợ json_schema
            else:
                body.pop("response_format")                           # không hỗ trợ cả JSON mode: dựa vào lời nhắc
            data = _http("POST", self.base + "/chat/completions", self._headers(), body)
        u = data.get("usage") or {}
        usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0),
                 "cache_read": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0), "cache_write": 0}
        choices = data.get("choices") or []
        if not choices:
            return None, usage, False
        msg = choices[0].get("message") or {}
        if msg.get("refusal") or choices[0].get("finish_reason") == "content_filter":
            return None, usage, True
        return _parse_items(msg.get("content")), usage, False

    def list_models(self):
        data = _http("GET", self.base + "/models", self._headers())
        skip = ("embed", "whisper", "tts", "audio", "realtime", "image", "moderation", "transcribe", "dall", "search")
        ids = [m["id"] for m in data.get("data", [])
               if m["id"].startswith(("gpt", "o1", "o3", "o4", "chatgpt")) and not any(s in m["id"] for s in skip)]
        return sorted(ids)


class OpenAICompatProvider(OpenAIProvider):
    """Nhà cung cấp nói giao thức OpenAI /chat/completions (OpenRouter, Grok, DeepSeek, Mistral, Groq, Qwen,
    Kimi, Ollama...)."""
    use_schema = False

    def __init__(self, key, name):
        spec = COMPAT[name]
        self.name, self.key = name, key
        self.base = os.environ.get(spec["base_env"], spec["base"]).rstrip("/")

    def list_models(self):
        data = _http("GET", self.base + "/models", self._headers())
        skip = ("embed", "whisper", "tts", "audio", "moderation", "rerank", "guard", "image-gen", "dall")
        ids = {m.get("id") or m.get("name") for m in data.get("data", data.get("models", []))}
        return sorted(i for i in ids if i and not any(s in i.lower() for s in skip))


class GeminiProvider:
    name = "gemini"
    _BLOCKED = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION")

    def __init__(self, key):
        self.key = key
        self.base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    def _headers(self):
        return {"x-goog-api-key": self.key}

    def json_call(self, model, system, parts, schema):
        g = []
        for kind, val in parts:
            if kind == "text":
                g.append({"text": val})
            else:
                g.append({"inline_data": {"mime_type": "image/png", "data": _b64(val)}})
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": g}],
                "generationConfig": {"responseMimeType": "application/json",
                                     "responseSchema": _gemini_schema(schema)}}
        model = model.split("/", 1)[-1] if model.startswith("models/") else model
        data = _http("POST", f"{self.base}/models/{model}:generateContent", self._headers(), body)
        um = data.get("usageMetadata") or {}
        usage = {"input": um.get("promptTokenCount", 0), "output": um.get("candidatesTokenCount", 0),
                 "cache_read": um.get("cachedContentTokenCount", 0), "cache_write": 0}
        if (data.get("promptFeedback") or {}).get("blockReason"):
            return None, usage, True
        cands = data.get("candidates") or []
        if not cands:
            return None, usage, False
        text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
        if not text and cands[0].get("finishReason") in self._BLOCKED:
            return None, usage, True
        return _parse_items(text), usage, False

    def list_models(self):
        data = _http("GET", self.base + "/models?pageSize=1000", self._headers())
        skip = ("embedding", "aqa", "imagen", "veo", "tts", "image", "live")
        ids = [m["name"].split("/", 1)[-1] for m in data.get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
        return sorted(i for i in ids if not any(s in i for s in skip))


_CLASSES = {"claude": ClaudeProvider, "openai": OpenAIProvider, "gemini": GeminiProvider,
            **{k: (lambda key, k=k: OpenAICompatProvider(key, k)) for k in COMPAT}}


def make(name):
    if name not in _CLASSES:
        raise SystemExit(f"Nhà cung cấp không hợp lệ: {name}")
    return _CLASSES[name](config.load_api_key(name))


class Pool:
    """Tạo nhà cung cấp khi cần dùng (nên video chỉ dùng Claude thì không cần khóa OpenAI/Gemini)."""

    def __init__(self):
        self._made = {}

    def get(self, name):
        if name not in self._made:
            self._made[name] = make(name)
        return self._made[name]


