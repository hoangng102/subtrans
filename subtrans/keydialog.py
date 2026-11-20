"""Hộp thoại quản lý khóa API: chọn nhà cung cấp AI trong danh sách, dán khóa của mình, kiểm tra khóa và xem
hướng dẫn tự lấy khóa. Khóa mặc định do nhà phát triển cấu hình sẵn (biến môi trường / file khóa) được giấu:
người dùng thường chỉ thấy "Đã cấu hình sẵn" và không thể xem hay sửa nó."""
import queue
import threading
import tkinter as tk
import webbrowser

from . import config, providers, sysdeps
from .ui import theme as T
from .ui import widgets as W

# Hướng dẫn lấy khóa. Trang web của nhà cung cấp có thể đổi giao diện hoặc điều kiện, nên các bước chỉ mô tả ngắn gọn.
GUIDE = {
    "claude": {
        "url": "https://console.anthropic.com/settings/keys", "hint": "Bắt đầu bằng sk-ant-",
        "steps": ("1. Đăng nhập (hoặc tạo tài khoản) tại console.anthropic.com.\n"
                  "2. Vào Settings → Billing, nạp một ít credit (khóa chỉ chạy khi tài khoản còn credit).\n"
                  "3. Vào Settings → API Keys → Create Key, đặt tên rồi sao chép khóa (chỉ hiện một lần)."),
    },
    "openai": {
        "url": "https://platform.openai.com/api-keys", "hint": "Bắt đầu bằng sk-",
        "steps": ("1. Đăng nhập (hoặc tạo tài khoản) tại platform.openai.com.\n"
                  "2. Vào Billing, nạp trước một ít credit.\n"
                  "3. Vào API keys → Create new secret key, rồi sao chép khóa (chỉ hiện một lần)."),
    },
    "gemini": {
        "url": "https://aistudio.google.com/app/apikey", "hint": "Thường bắt đầu bằng AIza",
        "steps": ("1. Đăng nhập tài khoản Google tại aistudio.google.com.\n"
                  "2. Bấm Get API key → Create API key.\n"
                  "3. Sao chép khóa. Gemini thường có gói miễn phí giới hạn (điều kiện do Google quyết định "
                  "và có thể thay đổi)."),
    },
    "openrouter": {
        "url": "https://openrouter.ai/keys", "hint": "Thường bắt đầu bằng sk-or-",
        "steps": ("1. Đăng nhập tại openrouter.ai, nạp credit.\n"
                  "2. Vào Keys → Create Key, sao chép khóa.\n"
                  "3. Một khóa dùng được nhiều model của nhiều hãng. Gõ tên model dạng hãng/model "
                  "(ví dụ google/gemini-2.5-flash) hoặc bấm Tải danh sách model."),
    },
    "xai": {
        "url": "https://console.x.ai", "hint": "Thường bắt đầu bằng xai-",
        "steps": ("1. Đăng nhập tại console.x.ai, thêm phương thức thanh toán hoặc credit.\n"
                  "2. Vào API Keys → Create API key, sao chép khóa.\n"
                  "3. Bấm Tải danh sách model để biết model nào tài khoản dùng được."),
    },
    "deepseek": {
        "url": "https://platform.deepseek.com/api_keys", "hint": "Bắt đầu bằng sk-",
        "steps": ("1. Đăng nhập tại platform.deepseek.com, nạp tiền.\n"
                  "2. Vào API keys → Create new API key, sao chép khóa.\n"
                  "3. Lưu ý: DeepSeek không đọc được ảnh, chỉ dùng cho bước Dịch (bước đọc chữ dùng OCR cục bộ "
                  "hoặc nhà cung cấp khác)."),
    },
    "mistral": {
        "url": "https://console.mistral.ai/api-keys", "hint": "Chuỗi ký tự dài",
        "steps": ("1. Đăng nhập tại console.mistral.ai, bật thanh toán.\n"
                  "2. Vào API Keys → Create new key, sao chép khóa.\n"
                  "3. Model đọc được ảnh thường có tên pixtral hoặc mistral-small/large mới."),
    },
    "groq": {
        "url": "https://console.groq.com/keys", "hint": "Bắt đầu bằng gsk_",
        "steps": ("1. Đăng nhập tại console.groq.com.\n"
                  "2. Vào API Keys → Create API Key, sao chép khóa.\n"
                  "3. Groq thường có gói miễn phí giới hạn tốc độ (điều kiện do Groq quyết định). Model đọc được "
                  "ảnh hiện là dòng Llama 4."),
    },
    "qwen": {
        "url": "https://www.alibabacloud.com/help/en/model-studio/get-api-key", "hint": "Bắt đầu bằng sk-",
        "steps": ("1. Mở trang hướng dẫn, đăng nhập Alibaba Cloud Model Studio.\n"
                  "2. Tạo API key theo hướng dẫn rồi sao chép khóa.\n"
                  "3. Khóa gắn với vùng (quốc tế hoặc Trung Quốc đại lục). Địa chỉ mặc định là vùng quốc tế; nếu "
                  "báo lỗi xác thực, kiểm tra lại vùng của khóa."),
    },
    "moonshot": {
        "url": "https://platform.moonshot.ai/console/api-keys", "hint": "Bắt đầu bằng sk-",
        "steps": ("1. Đăng nhập tại platform.moonshot.ai, nạp tiền.\n"
                  "2. Vào API Keys → tạo khóa mới và sao chép.\n"
                  "3. Các model Kimi trong danh sách này chỉ đọc chữ, dùng cho bước Dịch."),
    },
    "ollama": {
        "url": "https://ollama.com/download", "hint": "",
        "steps": ("1. Cài Ollama (ollama.com) và để nó chạy nền trên máy bạn, không cần khóa API.\n"
                  "2. Tải một model đọc được ảnh, ví dụ gõ ollama pull llama3.2-vision (model chỉ-chữ như llama3.1 "
                  "dùng cho bước Dịch).\n"
                  "3. Bấm Kiểm tra kết nối. Chạy trên máy nên miễn phí nhưng chậm và chất lượng phụ thuộc cấu hình."),
    },
}


def _friendly_error(err, key):
    text = str(err)
    if key:
        text = text.replace(key, "***")
    low = text.lower()
    if any(w in low for w in ("401", "403", "invalid", "authentication", "unauthorized", "api key not valid",
                              "permission")):
        return "Khóa không đúng, đã bị thu hồi hoặc chưa được cấp quyền."
    if any(w in low for w in ("timed out", "timeout", "connection", "getaddrinfo", "network", "refused")):
        return "Không kết nối được tới nhà cung cấp. Kiểm tra mạng (hoặc Ollama đã chạy chưa) rồi thử lại."
    return "Không kiểm tra được: " + text[:160]


class KeyDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.withdraw()
        self.title("Khóa API")
        self.configure(bg=T.WINDOW)
        self.transient(parent.winfo_toplevel())
        px = T.px
        self.vars, self.status, self.entries, self.cards = {}, {}, {}, {}
        self.chips, self.check_btn, self.del_btn = {}, {}, {}
        self.changed = False
        self.q = queue.Queue()            # kết quả kiểm tra từ luồng nền (Tk chỉ được đụng từ luồng chính)

        height = max(px(380), min(px(700), self.winfo_screenheight() - px(140)))
        self.geometry(f"{px(720)}x{height}")
        footer = tk.Frame(self, bg=T.WINDOW)
        footer.pack(side="bottom", fill="x", padx=px(20), pady=(px(8), px(16)))
        page = W.ScrollPage(self)
        page.pack(fill="both", expand=True)
        wrap = tk.Frame(page.inner, bg=T.WINDOW)
        wrap.pack(fill="both", expand=True, padx=px(20), pady=(px(16), 0))

        W.Label(wrap, "Khóa API của bạn", kind="h").pack(anchor="w")
        W.Label(wrap, "Chọn nhà cung cấp AI bạn muốn dùng rồi dán khóa của nhà đó. Bạn trả phí trực tiếp cho nhà "
                      "cung cấp theo lượng dùng (nên đặt hạn mức chi tiêu trong trang của họ). Khóa được mã hóa và "
                      "chỉ lưu trên máy này, chỉ được gửi tới đúng nhà cung cấp đó.",
                kind="hint", wrap=660).pack(anchor="w", pady=(2, px(12)))

        pick = tk.Frame(wrap, bg=T.WINDOW)
        pick.pack(fill="x", pady=(0, px(10)))
        W.Label(pick, "Nhà cung cấp AI", kind="label").pack(anchor="w", pady=(0, px(6)))
        first = next((p for p in providers.PROVIDERS if not config.has_key(p)), "claude")
        self.sel = tk.StringVar(value=providers.PROVIDERS[first])
        W.Select(pick, self.sel, list(providers.PROVIDERS.values())).pack(fill="x")
        self.sel.trace_add("write", lambda *_: self._show())

        self.holder = tk.Frame(wrap, bg=T.WINDOW)
        self.holder.pack(fill="x")
        for prov in providers.PROVIDERS:
            self._card(self.holder, prov)

        self.l_summary = W.Label(wrap, "", kind="hint", wrap=660)
        self.l_summary.pack(anchor="w", pady=(px(4), px(10)))

        W.Button(footer, "Đóng", variant="primary", command=self.destroy).pack(side="right")
        if config.DEV_MODE:
            W.Button(footer, "Mở file khóa (chế độ nhà phát triển)", variant="ghost", small=True,
                     command=self._open_file).pack(side="left")
        self._show()
        self._summary()
        self.update_idletasks()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + max(0, (pw.winfo_width() - self.winfo_width()) // 2)
        y = pw.winfo_rooty() + max(0, (pw.winfo_height() - self.winfo_height()) // 4)
        self.geometry(f"+{x}+{y}")
        self.bind("<Escape>", lambda e: self.destroy())
        self.deiconify()
        self.after(100, self._poll)

    def _poll(self):
        try:
            while True:
                self._done(*self.q.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self.after(100, self._poll)

    # ------------------------------------------------------------ giao diện
    def _card(self, holder, prov):
        px = T.px
        g = GUIDE[prov]
        needs_key = prov not in config.NO_KEY
        card = W.Card(holder)
        self.cards[prov] = card
        b = card.body
        head = tk.Frame(b, bg=T.SURFACE)
        head.pack(fill="x")
        W.Label(head, providers.PROVIDERS[prov], kind="h").pack(side="left")
        self.chips[prov] = W.Chip(head, "")
        self.chips[prov].pack(side="left", padx=(px(10), 0))
        W.Button(head, "Mở trang lấy khóa ↗" if needs_key else "Mở trang tải về ↗", variant="link", small=True,
                 command=lambda u=g["url"]: webbrowser.open(u)).pack(side="right")

        W.Label(b, g["steps"], kind="hint", wrap=640).pack(anchor="w", pady=(px(8), px(10)))

        row = tk.Frame(b, bg=T.SURFACE)
        row.pack(fill="x")
        if needs_key:
            var = self.vars[prov] = tk.StringVar()
            self.entries[prov] = W.Entry(row, var, mono=True, show="•", placeholder=g["hint"])
            self.entries[prov].pack(side="left", fill="x", expand=True)
            W.Button(row, "Hiện", small=True, command=lambda p=prov: self._toggle(p)).pack(side="left",
                                                                                          padx=(px(6), 0))
        self.check_btn[prov] = W.Button(row, "Lưu và kiểm tra" if needs_key else "Kiểm tra kết nối", small=True,
                                        command=lambda p=prov: self._save_check(p))
        self.check_btn[prov].pack(side="left" if needs_key else "right", padx=(px(6), 0))
        if needs_key:
            self.del_btn[prov] = W.Button(row, "Xóa", small=True, variant="ghost",
                                          command=lambda p=prov: self._delete(p))
        self.status[prov] = W.Label(b, "", kind="hint")
        self.status[prov].pack(anchor="w", pady=(px(6), 0))
        self._refresh(prov)

    def _show(self):
        label = self.sel.get()
        for prov, card in self.cards.items():
            card.pack_forget()
            if providers.PROVIDERS[prov] == label:
                card.pack(fill="x")

    def _summary(self):
        have = [providers.PROVIDERS[p].split(" (")[0] for p in providers.PROVIDERS
                if p not in config.NO_KEY and config.has_key(p)]
        self.l_summary.configure(text=("Đã có khóa cho: " + ", ".join(have) + ".") if have else
                                 "Chưa có khóa nào. Chọn một nhà cung cấp ở trên để bắt đầu.")

    def _refresh(self, prov):
        src = config.key_source(prov)
        if prov in config.NO_KEY:
            text, ok = "Không cần khóa", True
        elif src == "app":
            text, ok = "✔ Đã lưu trong ứng dụng", True
        elif src in ("env", "file"):
            # Khóa mặc định của nhà phát triển: người dùng thường không thấy nguồn và không sửa được.
            text = ("✔ Từ biến môi trường" if src == "env" else "✔ Từ file khóa") if config.DEV_MODE \
                else "✔ Đã cấu hình sẵn"
            ok = True
        else:
            text, ok = "Chưa có khóa", False
        self.chips[prov].configure(text=text)
        self.chips[prov]._orange = ok
        self.chips[prov].redraw()
        btn = self.del_btn.get(prov)
        if btn is not None:               # chỉ xóa được khóa người dùng tự nhập, không đụng khóa mặc định
            if src == "app":
                btn.pack(side="left", padx=(T.px(2), 0))
            else:
                btn.pack_forget()

    def _toggle(self, prov):
        ent = self.entries[prov].entry
        ent.configure(show="" if ent.cget("show") else "•")

    def _set_status(self, prov, text, ok=None):
        self.status[prov].configure(text=text, fg=T.ACCENT_TEXT if ok else (T.DANGER_TEXT if ok is False
                                                                              else T.TEXT_MUTED))

    # ------------------------------------------------------------ hành động
    def _save_check(self, prov):
        needs_key = prov not in config.NO_KEY
        key = self.vars[prov].get().strip() if needs_key else ""
        if needs_key and not key:
            if config.has_key(prov):
                key = config.load_api_key(prov)          # kiểm tra khóa đang dùng (không lưu lại)
            else:
                self._set_status(prov, "Hãy dán khóa vào ô trên.", False)
                return
        self.check_btn[prov].set_loading(True)
        self._set_status(prov, "Đang kiểm tra...")

        def work():
            try:
                n = len(providers._CLASSES[prov](key).list_models())
                res = (True, f"Kết nối được ({n} model khả dụng).")
            except SystemExit as e:
                res = (False, str(e))
            except Exception as e:                       # sai khóa, hết hạn mức, mất mạng...
                res = (False, _friendly_error(e, key))
            self.q.put((prov, key, *res))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, prov, key, ok, msg):
        if not self.winfo_exists():
            return
        self.check_btn[prov].set_loading(False)
        if ok and prov in self.vars and self.vars[prov].get().strip():     # khóa mới nhập thì mới lưu
            config.set_key(prov, key)
            self.vars[prov].set("")
            self.changed = True
            msg += " Đã lưu."
        self._set_status(prov, msg, ok)
        self._refresh(prov)
        self._summary()

    def _delete(self, prov):
        if config.key_source(prov) == "app":
            config.clear_key(prov)
            self.changed = True
            self._set_status(prov, "Đã xóa khóa khỏi ứng dụng.")
        self.vars[prov].set("")
        self._refresh(prov)
        self._summary()

    def _open_file(self):
        import os
        p = config.key_file()
        if not p.exists():
            p.write_text("# Mỗi dòng một khóa, dạng TÊN=giá_trị (không dấu cách, không ngoặc kép).\n"
                         "# ANTHROPIC_API_KEY=\n# OPENAI_API_KEY=\n# GEMINI_API_KEY=\n", encoding="utf-8")
        sysdeps.open_path(p)

    def run(self):
        self.grab_set()
        self.wait_window()
        return self.changed
