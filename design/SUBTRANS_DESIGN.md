# SubTrans UI — Design Spec (v2)

Source of truth for the SubTrans desktop UI redesign.
Visual reference: `design/reference/Main.dc.html` (tab "Dịch") and `design/reference/Edit.dc.html` (tab "Chỉnh sửa & kiểu phụ đề", v2). Both are plain HTML with inline styles — read the markup for exact values. PNG exports (if present) live in `design/reference/*.png`.

## Changelog

### v2 (tab "Chỉnh sửa & kiểu phụ đề" only)
- **"Kiểu phụ đề" + "Công cụ AI cho dòng chọn" merged into ONE panel with 2 tabs.** Default tab = "Kiểu phụ đề". Same controls, same handlers; only the container changed.
- **"Dòng đang chọn" is now a full-width card above the panel**, and its two text fields ("Chữ gốc", "Tiếng Việt") sit on ONE row, each one text-line high, auto-growing with content (newlines allowed), max ~4 lines then scroll.
- **"Xem trước"** now sits beside the tabbed panel (same row, stretches to the same height). It is no longer stacked above the AI card.
- Board is shorter (1180 → 1100). Tab "Dịch" is unchanged.

## 1. Principles

- Clean, modern, neutral. Orange is an **accent only**: primary action, active tab, selected row, progress, focus, checkbox, small links.
- No gradients. No heavy shadows (only the popup menu has one).
- Text on orange is **near-black `#1A0A00`, never white** (white on `#F97316` fails contrast).
- Orange used as *text* on white must be `#C2410C` (not `#F97316`).
- Cards on a light-grey window. Labels above inputs. One primary button per context.
- UI language: Vietnamese. Keep every existing Vietnamese string unless this spec renames it.

## 2. Tokens

### Color
| Token | Value | Use |
|---|---|---|
| `bg.window` | `#F5F5F5` | window / page background |
| `surface` | `#FFFFFF` | cards, title bar, tab bar, inputs |
| `surface.muted` | `#FAFAFA` | readonly fields, log, dropzone, table header |
| `surface.subtle` | `#F0F0F0` | neutral chips |
| `hover` | `#F5F5F5` | button hover |
| `hover.ghost` | `#EDEDED` | ghost button / window control hover |
| `border.card` | `#E6E6E6` | card + tab bar border |
| `border.control` | `#D9D9D9` | inputs, selects, buttons |
| `border.control.hover` | `#C4C4C4` | hover |
| `divider` | `#EFEFEF` | dividers, table row borders (`#F0F0F0`) |
| `border.window` | `#D4D4D4` | window outline |
| `text` | `#171717` | primary text |
| `text.secondary` | `#404040` / `#525252` | labels, ghost buttons |
| `text.muted` | `#6B6B6B` | hints, inactive tab |
| `text.empty` | `#8A8A8A` | "Chưa dịch", "(trống)" placeholders |
| `text.disabled` | `#A3A3A3` on `#F5F5F5` | disabled controls |
| `accent` | `#F97316` | primary button bg, tab underline, progress, checkbox |
| `accent.hover` | `#FB8A3C` | primary hover |
| `on.accent` | `#1A0A00` | text/icons on accent |
| `accent.text` | `#C2410C` | orange text / icons on white |
| `accent.tint` | `#FFF4EC` | selected row, selected queue item |
| `accent.chip.bg` | `#FFF1E6` | active filter chip, "Dòng 1" chip |
| `accent.chip.text` | `#9A3412` | text on chip |
| `accent.chip.border` | `#FDBA8C` | active filter chip border |
| `accent.chip.count` | `#FFDDC2` | count badge on active chip |
| `preview.bg` | `#2B2B2B` | subtitle preview box |
| `track` | `#EAEAEA` | progress trough |

### Typography
- UI: **Inter** 400 / 500 / 600. Fallback `Segoe UI`.
- Mono: **JetBrains Mono** 400 — timestamps, numbers in fields, hex codes, log. Fallback `Consolas`.
- CJK fallback: `Noto Sans SC`, `Microsoft YaHei`.
- Sizes: base 13 · small/label/hint 12 · micro 11–11.5 · source-text box 15/500 · subtitle sample 15/600.
- Label: 12 / 500 / `#525252`, sits above the field (6px gap). Card title: 13 / 600.

### Spacing / sizing
- Scale: 4 · 6 · 8 · 10 · 12 · 14 · 16 · 20 · 24.
- Window content padding: 20 top/bottom, 24 left/right. Card padding 16. Gap between cards 12–16.
- Heights: title bar 40 · tab bar 45 · control 32 · small control 28 · table row 34 · table header 30 · progress 6.
- Radius: window 10 · card 12 · dropzone 10 · control 8 · small button 6 · chip/pill 999.
- Shadow: popup menu only — `0 8px 24px rgba(0,0,0,.12)`.
- Focus ring: 2px `#F97316`, offset 2.

## 3. Components

- **Title bar** (white, 40): 20px orange rounded app mark with two dark bars, "SubTrans" 600 + muted subtitle; window controls 46×40, hover `#EDEDED`.
- **Tabs** (white bar, bottom border): text tabs, 28px gap. Active = `#171717` + 2px orange underline. Inactive = `#6B6B6B`.
- **Card**: white, 1px `#E6E6E6`, radius 12, padding 16.
- **Button**: height 32, radius 8, 1px `#D9D9D9`, white bg, 13/500. Variants:
  - `primary`: bg `#F97316`, text `#1A0A00`, 600. Max one per row.
  - `ghost`: transparent, text `#404040`, hover `#EDEDED`.
  - `sm`: height 28, radius 6, 12px.
  - `icon`: 32×32, no padding.
  - `disabled`: text `#A3A3A3`, bg `#F5F5F5`.
  - Link-like ghost in orange: text `#C2410C` ("Tải danh sách model").
  - Step button: leading 18px circle with number (neutral `#EDEDED`; inside primary: `#1A0A00` bg + `#F97316` text).
- **Input / Select**: height 32, radius 8, 1px `#D9D9D9`, padding 0 10. Select has custom 12px chevron right. Mono for numeric/time fields. Disabled: bg `#F5F5F5`.
- **Checkbox**: 16px, accent `#F97316`, 8px gap to label.
- **Chip**: height 24, pill, `#F0F0F0`/`#404040`. Orange variant `#FFF1E6`/`#9A3412`.
- **Filter chip** ("Chọn nhanh"): height 28, pill, 1px `#D9D9D9`; contains label + count badge (min 18px, pill, `#F0F0F0`). Active: orange chip colors + badge `#FFDDC2`.
- **Color swatch field**: 32px high, 18px rounded swatch with 1px dark-alpha border + hex in mono.
- **Table (subtitle list)**: grid `44px 112px 112px 1fr 1.15fr`, header on `#FAFAFA`, rows 34px, 1px row border. Selected/matched row bg `#FFF4EC` with orange bold index. Empty cells italic `#8A8A8A`. Body scrolls (≈5 rows visible).
- **Progress**: 6px, trough `#EAEAEA`, fill `#F97316`, both pill.
- **Log**: card + inner mono 12px / line-height 1.7 on `#FAFAFA`, 1px `#EFEFEF`, radius 8.
- **Popup menu** (more): white, 1px `#E0E0E0`, radius 10, padding 6, items 34px high with 14px icon, hover `#F5F5F5`, `<hr>` divider. Opens upward from its button.
- **Preview box**: `#2B2B2B`, radius 8, 16:9. Subtitle sample yellow `#FFFF00`, 600, black outline (1px 4-way + soft shadow), centered near bottom. Original hardsub shown small and grey (`#8C8C8C`) at bottom-right.

## 4. Screens

### Tab "Dịch"
1. Card **Hàng đợi video**: title + hint left; buttons right (`Thêm video…`, `Thêm thư mục…` | ghost `Xóa mục chọn`, `Xóa tất cả`). Below: dashed dropzone (64px) with queue items; selected item bg `#FFF4EC`.
2. Two equal columns: **Nhận dạng và dịch** | **Mô hình AI**.
   - Left: 2-col grid (Ngôn ngữ gốc, Vùng sub), full-width selects (Nhận diện sub, Đọc chữ bằng), divider, checkbox *Dịch toàn bộ video*, 2-col (Chỉ thử đoạn: từ giây, Dài (giây)) disabled when full video is on, checkbox OCR cục bộ.
   - Right: two provider+model pairs (Đọc chữ trong ảnh, Dịch sang tiếng Việt), each with an orange ghost `Tải danh sách model` on the label row; divider; API key chips (Claude / OpenAI / Gemini with check icon) + `Mở file khóa API`; muted note block.
3. Info line (icon + hint) pointing to the other tab.
4. Card **run**: `1 Xem trước (miễn phí)`, `2 Ước lượng`, `3 Dịch` (primary), ghost `Dừng` (disabled when idle), right-aligned `Xuất lại theo kiểu hiện tại`; progress bar below.
5. Card **Nhật ký** (flex-grow): header with ghost buttons `Chỉnh sửa phụ đề của video chọn`, `Mở ảnh xem trước`, `Mở thư mục video`; mono log below.

### Tab "Chỉnh sửa & kiểu phụ đề"
1. Card **subtitle list** (no padding): row *Video* (readonly path + `Tải phụ đề`); toolbar (`Thêm dòng`, `Xóa dòng`, `Gộp với dòng sau`, ghost `Hoàn tác` | `Lệch giờ (giây)` field + `Tất cả` / `Từ dòng chọn` … right: `Tìm`, `Thay bằng`, `Thay hết`); **Chọn nhanh** bar; table.
2. Card **Dòng đang chọn** (full width, compact):
   - Header: title + chip `Dòng N` left; live stats `3.00s · 48 ký tự · 16 ký tự/giây` right (mono 11px).
   - Row 1: `Bắt đầu` field + `−0.1` `+0.1`, `Kết thúc` field + `−0.1` `+0.1`.
   - Row 2 (one row, 2 equal columns): `Chữ gốc` (readonly, `Chép` ghost button on the label row) | `Tiếng Việt` (editable). Each field is **one text line tall (32px)** and **auto-grows** as content wraps or the user types a newline (Enter inserts a newline), up to ~4 lines (96px), then scrolls. Source field uses 15/500 + CJK fallback font and `#FAFAFA` bg.
3. Row `1fr | 400px` (equal height):
   - **Tabbed panel card** (no card padding; tab bar on top with bottom border, body padding 16, body min-height ≈ 257 so switching tabs does not resize the card):
     - Tab 1 (default) **`Kiểu phụ đề`**: 4-col grid (Font, Cỡ chữ %, In đậm, In nghiêng / Màu chữ, Màu viền, Màu nền, Độ đục nền % / Độ dày viền, Đổ bóng, Kiểu nền span 2) / divider / `Vị trí theo sub gốc`, `Cách đỉnh (%)` (disabled when "theo sub gốc"), ghost `Đặt lại mặc định`.
     - Tab 2 **`Công cụ AI cho dòng chọn`**: two columns — `Dịch lại bằng` (provider + model, orange ghost `Tải danh sách model`, `Dịch lại dòng chọn`) and `Đọc lại chữ (OCR) bằng` (same pattern, `Đọc lại dòng chọn`); hint block at the bottom. The header shows chip `Đã chọn N dòng` (mirrors quick-select) only on this tab.
     - Tab bar item: 13/500, `#6B6B6B`; active `#171717` + 2px `#F97316` underline; 24px gap; height 44. Keyboard: Left/Right switches tabs; both tab bodies keep their widget state when hidden (do not rebuild).
   - **Card `Xem trước`**: header (`Xem trước` + hint `Gần đúng`), the dark preview box fills the remaining height (min 207).
3. Card **Xuất kèm**: row 1 = title + hint, checkboxes `.srt (không có màu/viền/nền)`, `Chữ gốc (.src.srt)`, right-aligned status line. Row 2 = primary `Lưu và xuất .ass`, `Xem trong VLC`, **more (⋯)** menu, divider, ghost `OCR cục bộ dòng chưa đọc được`.
   - More menu items: `Xuất chữ gốc (.srt)`, `Nhập phụ đề đã dịch…`, —, `Đọc/dịch lại dòng trống`.

## 5. Behaviors (new)

- **Chọn nhanh (quick select)**: chips = `Tất cả`, `Chưa dịch` (has source, no translation), `Chưa có chữ gốc` (blank row), `Đã dịch`; each shows a live count. Clicking a chip selects all matching rows (tinted); clicking it again clears. `Đã chọn N dòng` + `Bỏ chọn` show when a filter is active. Checkbox `Chỉ hiện dòng khớp` hides non-matching rows. "Dịch lại dòng chọn" / "Đọc lại dòng chọn" operate on this selection and the `Đã chọn N dòng` chip mirrors it. This replaces the old button `Chọn các dòng chưa có chữ gốc`.
- Possible later criteria: too fast (> N chars/s), overlapping times, edited manually.
- **More menu**: toggles on click, closes on outside click / Esc.
- **Auto-grow text fields** (v2): `Chữ gốc` and `Tiếng Việt` start at 1 line and resize to fit wrapped/newline content (clamp 1–4 lines); recompute on edit, on row change and on window resize.
- **Style / AI tabs** (v2): default `Kiểu phụ đề`; switching must not reset any field; AI actions still act on the quick-select selection.

## 6. Implementation notes (Tkinter)

- Put all tokens in one module (e.g. `ui/theme.py`); no hex literals elsewhere.
- Base theme `clam` + `ttk.Style`. Map: button states, `TCheckbutton` indicator color to accent, `Horizontal.TProgressbar` (trough/bar colors), `Treeview` (rowheight 34, header style, tags for matched rows).
- Native Tk has no rounded corners: use a small Canvas-drawn rounded-frame helper for cards/chips/buttons, or `customtkinter`/`ttkbootstrap` if the project already uses it or the owner approves. Prefer the smallest dependency footprint.
- Replace `ttk.Notebook` tab strip with a custom tab bar (labels + 2px underline) if styling the notebook cannot reach the look.
- Fonts: bundle Inter + JetBrains Mono `.ttf` under `assets/fonts`, register at startup (Windows: `AddFontResourceExW` via ctypes); fall back to Segoe UI / Consolas.
- Enable DPI awareness on Windows (`SetProcessDpiAwareness(1)`) and size by scaling factor.
- Do not change business logic, variable names, callbacks or file formats — this is a visual + small interaction change.
