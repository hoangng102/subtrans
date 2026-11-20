DEFAULT_STYLE = {
    "font": "Arial",
    "font_scale": 100,         # % so với cỡ chữ mặc định
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 2,
    "bg_color": "#000000",
    "bg_mode": "strip",        # none | text | strip
    "bg_opacity": 100,         # 0-100
    "bold": False,
    "italic": False,
    "shadow": 0,               # px
    "pos_auto": True,          # True: giữa dải sub gốc; False: theo pos_y
    "pos_y": 88.0,             # % chiều cao từ trên xuống, tâm dòng chữ
}


def _srt_ts(t):
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_ts(t):
    cs = round(t * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _bgr(hex_color):
    h = hex_color.lstrip("#")
    return f"{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _alpha(opacity):
    return f"{round(255 * (100 - int(opacity)) / 100):02X}"


def effective_style(style, meta):
    """Phụ đề lấy từ giọng nói không có dải hardsub cần che: kiểu nền "che cả dải" đổi thành nền chỉ sau chữ,
    nếu không cả dải 20% dưới của hình sẽ bị phủ màu."""
    st = {**DEFAULT_STYLE, **(style or {})}
    if meta.get("source") == "speech" and st["bg_mode"] == "strip":
        st["bg_mode"] = "text"
    return st


def write_srt(cues, path, key="vi"):
    blocks = []
    for n, c in enumerate(cues, 1):
        blocks.append(f"{n}\n{_srt_ts(c['start'])} --> {_srt_ts(c['end'])}\n{c[key]}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_ass(cues, path, meta, style=None, key="vi"):
    """ASS có màu chữ, viền và nền tuỳ chỉnh. Font mặc định Arial hỗ trợ đủ dấu tiếng Việt."""
    st = effective_style(style, meta)
    w, h = meta["width"], meta["height"]
    y0, y1 = round(h * meta["crop"][0]), round(h * meta["crop"][1])
    cy = (y0 + y1) // 2 if st["pos_auto"] else round(h * float(st["pos_y"]) / 100)
    fs = max(16, int((y1 - y0) * 0.38 * float(st["font_scale"]) / 100))
    text_c, out_c, bg_c = _bgr(st["text_color"]), _bgr(st["outline_color"]), _bgr(st["bg_color"])
    mode = st["bg_mode"]

    if mode == "text":
        # BorderStyle 3: hộp nền sau chữ, màu hộp lấy từ OutlineColour
        border, outline, outline_col = 3, max(2, int(st["outline_width"]) + 3), f"&H{_alpha(st['bg_opacity'])}{bg_c}"
    else:
        border, outline, outline_col = 1, int(st["outline_width"]), f"&H00{out_c}"

    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{st['font']},{fs},&H00{text_c},&H000000FF,{outline_col},&H00000000,"
        f"{-1 if st['bold'] else 0},{-1 if st['italic'] else 0},0,0,100,100,0,0,"
        f"{border},{outline},{int(st['shadow'])},5,10,10,0,163",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    box = (f"{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\c&H{bg_c}&\\1a&H{_alpha(st['bg_opacity'])}&}}"
           f"m 0 {y0} l {w} {y0} l {w} {y1} l 0 {y1}")
    for c in cues:
        a, b = _ass_ts(c["start"]), _ass_ts(c["end"])
        text = c[key].replace("\n", "\\N")
        if mode == "strip":
            out.append(f"Dialogue: 0,{a},{b},Default,,0,0,0,,{box}")
        out.append(f"Dialogue: 1,{a},{b},Default,,0,0,0,,{{\\an5\\pos({w // 2},{cy})}}{text}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8-sig")

