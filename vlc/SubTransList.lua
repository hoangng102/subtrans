--[[
SubTrans - Danh sach phu de (VLC 3.x). Hoat dong doc lap, khong can SubTrans.
Tu tim file phu de canh video (.vi.ass, .test.vi.ass, .vi.srt, .ass, .srt), hien dong dang chieu va cac dong sap toi
voi "sau X giay", cap nhat theo vi tri dang phat (ke ca khi tua) va tu nap lai khi doi video.
Bat: menu Xem (View) > "SubTrans - Danh sach phu de".
--]]

local UPCOMING = 14
local PAST = 3
local TICK_US = 300000

local dlg, w_head, w_now, w_list, w_goto
local cues, cue_src, cue_len = {}, nil, -1

function descriptor()
    return {
        title = "SubTrans - Danh sách phụ đề",
        version = "4.0",
        author = "SubTrans",
        shortdesc = "SubTrans - Danh sách phụ đề",
        description = "Hiện dòng phụ đề đang chiếu và các dòng sắp tới của video đang phát.",
        capabilities = { "input-listener", "playing-listener", "meta-listener" }
    }
end

-- nhat ky chan doan: %APPDATA%\SubTrans\vlc_ext.log
local logf
local function log(msg)
    pcall(function()
        if not logf then
            local base = os.getenv("APPDATA")
            if not base then return end
            logf = io.open(base .. "\\SubTrans\\vlc_ext.log", "w")
        end
        if logf then logf:write(msg, "\n"); logf:flush() end
    end)
end

------------------------------------------------------------ doc file phu de
local function read_file(path)
    local f = io.open(path, "rb")
    if not f then return nil end
    local s = f:read("*a")
    f:close()
    if s:sub(1, 3) == "\239\187\191" then s = s:sub(4) end
    return s
end

local function ass_time(t)
    local h, m, s = t:match("^%s*(%d+):(%d+):([%d%.]+)")
    if not h then return nil end
    return tonumber(h) * 3600 + tonumber(m) * 60 + tonumber(s)
end

local function srt_time(t)
    local h, m, s, ms = t:match("(%d+):(%d+):(%d+)[,%.](%d+)")
    if not h then return nil end
    return tonumber(h) * 3600 + tonumber(m) * 60 + tonumber(s) + tonumber(ms) / (10 ^ #ms)
end

local function clean(text)
    text = text:gsub("{[^}]*}", ""):gsub("<[^>]+>", "")
    text = text:gsub("\\[Nn]", " / "):gsub("\r", ""):gsub("\n", " / ")
    return (text:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function parse_ass(s)
    local out = {}
    for line in s:gmatch("[^\n]+") do
        local a, b, text = line:match("^Dialogue:%s*%d+,([^,]+),([^,]+),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(.*)$")
        if a and not text:find("\\p1", 1, true) then
            local t0, t1 = ass_time(a), ass_time(b)
            text = clean(text)
            if t0 and t1 and text ~= "" then out[#out + 1] = { s = t0, e = t1, text = text } end
        end
    end
    return out
end

local function parse_srt(s)
    local out = {}
    s = s:gsub("\r\n", "\n"):gsub("\r", "\n")
    for block in (s .. "\n\n"):gmatch("(.-)\n\n") do
        local a, b = block:match("(%d+:%d+:%d+[,%.]%d+)%s*%-%->%s*(%d+:%d+:%d+[,%.]%d+)")
        if a then
            local body = block:gsub("^.-%-%->[^\n]*\n?", "")
            local t0, t1, text = srt_time(a), srt_time(b), clean(body)
            if t0 and t1 and text ~= "" then out[#out + 1] = { s = t0, e = t1, text = text } end
        end
    end
    return out
end

local function media_base()
    local item = vlc.input.item()
    if not item then return nil end
    local uri = item:uri()
    if not uri or not uri:find("^file://") then return nil end
    local path = vlc.strings.decode_uri((uri:gsub("^file:///", "")))
    if not path:match("^%a:") then path = "/" .. path end
    return (path:gsub("%.[^%./\\]+$", ""))
end

local function load_cues()
    local base = media_base()
    if not base then return {}, nil, -1 end
    for _, suf in ipairs({ ".vi.ass", ".test.vi.ass", ".vi.srt", ".ass", ".srt" }) do
        local p = base .. suf
        local s = read_file(p)
        if s then
            local list = suf:match("srt$") and parse_srt(s) or parse_ass(s)
            if #list > 0 then
                table.sort(list, function(x, y) return x.s < y.s end)
                return list, p, #s
            end
        end
    end
    return {}, nil, -1
end

------------------------------------------------------------ hien thi
local function fmt_t(t)
    local h = math.floor(t / 3600)
    local m = math.floor((t % 3600) / 60)
    local s = math.floor(t % 60)
    if h > 0 then return string.format("%d:%02d:%02d", h, m, s) end
    return string.format("%d:%02d", m, s)
end

local function locate(t)       -- chi so dong cuoi co start <= t (0 neu chua toi dong nao)
    local lo, hi, ans = 1, #cues, 0
    while lo <= hi do
        local mid = math.floor((lo + hi) / 2)
        if cues[mid].s <= t then ans = mid; lo = mid + 1 else hi = mid - 1 end
    end
    return ans
end

local shown = { "", "" }
local html_sig = ""
local function put(widget, idx, text)
    if shown[idx] ~= text then
        widget:set_text(text)
        shown[idx] = text
        return true
    end
    return false
end

local function put_html(html)
    if html == html_sig then return false end
    html_sig = html
    w_list:set_text(html)
    return true
end

local function esc(s)
    return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

-- bang that su (HTML): cot Luc / Con / Phu de thang hang, to mau dong dang chieu va dong sap toi
local function render(t)
    if #cues == 0 then
        local changed = put(w_head, 1, "Không tìm thấy file phụ đề (.vi.ass / .vi.srt / .ass / .srt) cạnh video này.")
        changed = put(w_now, 2, "") or changed
        changed = put_html("") or changed
        return changed
    end
    local i = locate(t)
    local rows = {
        '<table width="100%" cellspacing="0" cellpadding="5" style="font-size:13px">' ..
        '<tr bgcolor="#e4e4e4"><td width="62"><b>Lúc</b></td><td width="105"><b>Còn</b></td><td><b>Phụ đề</b></td></tr>'
    }
    local function row(bg, color, time_txt, wait_txt, text, bold)
        local b1, b2 = bold and "<b>" or "", bold and "</b>" or ""
        rows[#rows + 1] = string.format(
            '<tr bgcolor="%s"><td width="62"><font color="%s">%s%s%s</font></td><td width="105"><font color="%s">%s%s%s</font></td>' ..
            '<td><font color="%s">%s%s%s</font></td></tr>',
            bg, color, b1, time_txt, b2, color, b1, wait_txt, b2, color, b1, esc(text), b2)
    end
    for k = math.max(1, i - PAST + 1), math.min(#cues, i + UPCOMING) do
        local c = cues[k]
        if k <= i then
            if k == i and t < c.e then
                row("#ffd27a", "#000000", fmt_t(c.s), "ĐANG HIỆN", c.text, true)
            else
                row("#ffffff", "#8a8a8a", fmt_t(c.s), "đã qua", c.text, false)
            end
        else
            local wait = c.s - t
            local soon = wait < 3
            row(soon and "#fff1dd" or "#ffffff", soon and "#b34a00" or "#000000", fmt_t(c.s),
                wait < 0.5 and "sắp hiện" or string.format("sau %d giây", math.ceil(wait)), c.text, false)
        end
    end
    rows[#rows + 1] = "</table>"
    local now_txt = "Chưa tới dòng đầu tiên"
    if i >= 1 then now_txt = (t < cues[i].e and "Đang hiện:  " or "Vừa qua:  ") .. cues[i].text end
    local head = string.format("%s  ·  dòng %d/%d  ·  %s", fmt_t(t), math.max(i, 0), #cues,
        cue_src and cue_src:match("[^/\\]+$") or "")
    local changed = put(w_head, 1, head)
    changed = put(w_now, 2, now_txt) or changed
    changed = put_html(table.concat(rows)) or changed
    return changed
end

local function playing_time()
    local input = vlc.object.input()
    if not input then return nil end
    local us = vlc.var.get(input, "time")
    return us and (us / 1000000) or nil
end

local state = { base = nil, last_q = -1, cb_input = nil, n = 0 }

-- nap lai phu de neu doi video (hoac file phu de doi)
local function refresh_cues(force)
    local base = media_base()
    if force or base ~= state.base then
        local list, src, len = load_cues()
        cues, cue_src, cue_len = list, src, len
        shown = { "", "" }; html_sig = ""
        state.base, state.last_q = base, -1
        log("nap phu de: base=" .. tostring(base) .. " src=" .. tostring(src) .. " dong=" .. #list)
    end
end

local function draw(t)
    if render(t) then dlg:update() end
end

local function redraw(t)
    local ok, err = pcall(function()
        t = t or playing_time()
        if t then draw(t) end
    end)
    if not ok then log("redraw loi: " .. tostring(err)) end
end

local function seek_to(sec)
    local input = vlc.object.input()
    if input then vlc.var.set(input, "time", math.floor(math.max(0, sec) * 1000000)) end
    redraw(math.max(0, sec))
end

function jump_prev()
    local t = playing_time()
    if not t or #cues == 0 then return end
    local i = locate(t)
    local k = (i >= 1 and t - cues[i].s > 1.5) and i or i - 1      -- ve dau dong dang xem neu da qua 1,5 giay
    if k >= 1 then seek_to(cues[k].s - 0.3) end
end

function jump_next()
    local t = playing_time()
    if not t or #cues == 0 then return end
    local k = locate(t) + 1
    if k <= #cues then seek_to(cues[k].s - 0.3) end
end

function jump_time()
    local txt = w_goto:get_text() or ""
    local parts = {}
    for n in txt:gmatch("%d+") do parts[#parts + 1] = tonumber(n) end
    local sec
    if #parts == 1 then sec = parts[1]
    elseif #parts == 2 then sec = parts[1] * 60 + parts[2]
    elseif #parts >= 3 then sec = parts[1] * 3600 + parts[2] * 60 + parts[3] end
    if sec then seek_to(sec) end
end

function refresh_now()
    refresh_cues(true)
    redraw()
end

function activate()
    log("activate v4")
    dlg = vlc.dialog("SubTrans - Danh sách phụ đề")
    w_head = dlg:add_label("Đang nạp...", 1, 1, 4, 1)
    w_now = dlg:add_label("", 1, 2, 4, 1)
    w_list = dlg:add_html("", 1, 3, 4, 12)
    dlg:add_button("◀ Dòng trước", jump_prev, 1, 15, 1, 1)
    dlg:add_button("Dòng sau ▶", jump_next, 2, 15, 1, 1)
    w_goto = dlg:add_text_input("", 3, 15, 1, 1)
    dlg:add_button("Tua tới (mm:ss)", jump_time, 4, 15, 1, 1)
    dlg:add_button("↻ Làm mới bảng (theo vị trí hiện tại)", refresh_now, 1, 16, 4, 1)
    dlg:show()
    refresh_cues(true)
    redraw()
    log("activate xong")
end

-- VLC khong cho extension co bo hen gio: bang chi cap nhat khi co su kien (doi video, phat/tam dung, bam nut)
function input_changed() pcall(function() refresh_cues(false) end); redraw() end
function playing_changed() redraw() end
function meta_changed() redraw() end

function deactivate()
    if dlg then dlg:delete() end
end

function close()
    vlc.deactivate()
end
