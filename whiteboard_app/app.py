"""Factory whiteboard prototype.

A digital version of the factory monthly-schedule whiteboard:
- 月予定タブ     : drag magnet-style cards between days (for the touchscreen).
- 手書きノートタブ: multi-page pressure-sensitive whiteboard with PDF/image
                   backgrounds and PNG/PDF export.
View mode is read-only and auto-refreshes for phones / tablets. Edit mode is
for the large touch panel. Both share one SQLite file so changes propagate
between devices.
"""

import base64
import calendar
import io
import json
from datetime import datetime

import streamlit as st

import db
import export as exporter
import pdf_utils
from calendar_component import register_calendar_board
from whiteboard_canvas import register_whiteboard_canvas

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]
COLOR_LABELS = {"yellow": "黄", "blue": "青", "orange": "橙", "white": "白"}
CANVAS_W = 1280
CANVAS_H = 800
THUMB_W = 160

st.set_page_config(page_title="工場ホワイトボード", layout="wide")
db.init_db()

# ---- session state ---------------------------------------------------------
if "rev" not in st.session_state:
    st.session_state.rev = 0
if "note_page_no" not in st.session_state:
    st.session_state.note_page_no = 1
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "calendar"

# ---- URL params (deep-link share) ------------------------------------------
qp = st.query_params
if "tab" in qp and qp["tab"] in ("calendar", "note"):
    st.session_state.active_tab = qp["tab"]
if "page" in qp:
    try:
        st.session_state.note_page_no = max(1, int(qp["page"]))
    except ValueError:
        pass


def card_text(card):
    parts = [card["destination"], card["truck"], card["person"], card["time"]]
    return " ".join(p for p in parts if p)


def card_label(card):
    return f"[{COLOR_LABELS.get(card['color'], '?')}] {card_text(card) or '(空札)'} ⟨{card['id']}⟩"


# ===========================================================================
# 月予定タブ  (calendar + cards)
# ===========================================================================


def render_calendar_view(year, mon, month_key):
    cards = db.get_cards(month_key)
    by_day = {}
    for card in cards:
        by_day.setdefault(card["day"], []).append(card)

    ndays = calendar.monthrange(year, mon)[1]
    first_wd = calendar.weekday(year, mon, 1)

    header = st.columns(7)
    for i, col in enumerate(header):
        col.markdown(f"**{WEEKDAY_JA[i]}**")

    cells = [None] * first_wd + list(range(1, ndays + 1))
    while len(cells) % 7:
        cells.append(None)

    for week_start in range(0, len(cells), 7):
        cols = st.columns(7)
        for i, day in enumerate(cells[week_start : week_start + 7]):
            with cols[i]:
                if day is None:
                    continue
                wd = (first_wd + day - 1) % 7
                day_color = "#c0392b" if wd >= 5 else "inherit"
                st.markdown(
                    f"<div style='font-weight:bold;color:{day_color}'>{day}</div>",
                    unsafe_allow_html=True,
                )
                for card in by_day.get(day, []):
                    bg = db.COLORS.get(card["color"], "#eeeeee")
                    st.markdown(
                        f"<div style='background:{bg};border:1px solid #999;"
                        f"border-radius:4px;padding:2px 6px;margin:3px 0;"
                        f"font-size:12px'>{card_text(card) or '&nbsp;'}</div>",
                        unsafe_allow_html=True,
                    )


def render_calendar_edit(year, mon, month_key):
    cards = db.get_cards(month_key)
    data = {
        "year": year,
        "month": mon,
        "ndays": calendar.monthrange(year, mon)[1],
        "first_weekday": calendar.weekday(year, mon, 1),
        "weekday_names": WEEKDAY_JA,
        "colors": db.COLORS,
        "cards": [
            {
                "id": c["id"],
                "day": c["day"],
                "text": card_text(c) or "(空札)",
                "color": c["color"],
            }
            for c in cards
        ],
    }

    st.caption("札をドラッグして日付の間を移動できます(マウス・タッチ対応)。")
    calendar_board = register_calendar_board()
    result = calendar_board(
        key=f"board_{month_key}_{st.session_state.rev}",
        data=data,
        height="content",
        on_layout_change=lambda: None,
    )

    layout = result.get("layout") if result is not None else None
    if layout:
        current = {c["id"]: (c["day"], c["sort_order"]) for c in cards}
        changed = [
            (int(it["id"]), int(it["day"]), int(it["order"]))
            for it in layout
            if current.get(int(it["id"])) != (int(it["day"]), int(it["order"]))
        ]
        if changed:
            db.set_positions(changed)

    with st.expander("札を編集・削除"):
        if not cards:
            st.info("札がありません。サイドバーの「札を追加」から登録してください。")
        else:
            options = {card_label(c): c for c in cards}
            selected = options[st.selectbox("対象の札", list(options))]
            with st.form(f"edit_{selected['id']}"):
                e_dest = st.text_input("行先", selected["destination"])
                e_truck = st.text_input("車番", selected["truck"])
                e_person = st.text_input("氏名", selected["person"])
                e_time = st.text_input("出庫時間", selected["time"])
                color_keys = list(COLOR_LABELS)
                e_color = st.selectbox(
                    "色",
                    color_keys,
                    index=color_keys.index(selected["color"])
                    if selected["color"] in color_keys
                    else 0,
                    format_func=lambda k: COLOR_LABELS[k],
                )
                col_update, col_delete = st.columns(2)
                if col_update.form_submit_button("更新", use_container_width=True):
                    db.update_card(
                        selected["id"],
                        destination=e_dest,
                        truck=e_truck,
                        person=e_person,
                        time=e_time,
                        color=e_color,
                    )
                    st.session_state.rev += 1
                    st.rerun()
                if col_delete.form_submit_button("削除", use_container_width=True):
                    db.delete_card(selected["id"])
                    st.session_state.rev += 1
                    st.rerun()


# ===========================================================================
# 手書きノートタブ (multi-page whiteboard)
# ===========================================================================


def _clamp_page_no(board_key, requested):
    total = db.count_pages(board_key)
    if total == 0:
        db.ensure_page(board_key, 1)
        return 1
    return max(1, min(int(requested), total))


def _bg_for_component(page):
    if not page or not page.get("bg_data") or page.get("bg_type") == "blank":
        return None
    return base64.b64encode(page["bg_data"]).decode("ascii")


def render_note_view(board_key):
    pages_meta = db.list_pages(board_key)
    if not pages_meta:
        st.info("このボードにはまだページがありません。")
        return

    page_no = _clamp_page_no(board_key, st.session_state.note_page_no)
    st.session_state.note_page_no = page_no
    total = len(pages_meta)
    page = db.get_page(board_key, page_no)

    nav_l, nav_c, nav_r = st.columns([1, 2, 1])
    if nav_l.button("◀ 前", use_container_width=True, disabled=(page_no <= 1)):
        st.session_state.note_page_no = page_no - 1
        st.rerun()
    nav_c.markdown(
        f"<div style='text-align:center;font-weight:bold;font-size:20px;padding-top:6px'>"
        f"ページ {page_no} / {total}</div>",
        unsafe_allow_html=True,
    )
    if nav_r.button("次 ▶", use_container_width=True, disabled=(page_no >= total)):
        st.session_state.note_page_no = page_no + 1
        st.rerun()

    if page and page.get("image_png"):
        st.image(page["image_png"], use_container_width=True)
    elif page and page.get("bg_data"):
        st.image(page["bg_data"], use_container_width=True)
    else:
        st.caption("(空白ページ)")


def render_note_edit(board_key):
    page_no = _clamp_page_no(board_key, st.session_state.note_page_no)
    st.session_state.note_page_no = page_no
    page = db.ensure_page(board_key, page_no)
    total = db.count_pages(board_key)

    nav_l, nav_mid, nav_r = st.columns([1, 2, 1])
    if nav_l.button("◀ 前", use_container_width=True, disabled=(page_no <= 1), key="np_prev"):
        st.session_state.note_page_no = page_no - 1
        st.rerun()
    nav_mid.markdown(
        f"<div style='text-align:center;font-weight:bold;font-size:18px;padding-top:6px'>"
        f"ページ {page_no} / {total}</div>",
        unsafe_allow_html=True,
    )
    if nav_r.button("次 ▶", use_container_width=True, disabled=(page_no >= total), key="np_next"):
        st.session_state.note_page_no = page_no + 1
        st.rerun()

    bg_b64 = _bg_for_component(page)

    component = register_whiteboard_canvas()
    payload = component(
        key=f"wb_{board_key}_{page['id']}_{st.session_state.rev}",
        data={
            "page_id": page["id"],
            "strokes_json": page.get("strokes_json") or "[]",
            "bg_image_b64": bg_b64,
            "width": CANVAS_W,
            "height": CANVAS_H,
        },
        height="content",
        on_stroke_done=lambda: None,
    )

    if payload:
        done = payload.get("stroke_done")
        if done and done.get("page_id") == page["id"]:
            strokes_json = done.get("strokes_json") or "[]"
            img_b64 = done.get("image_png_b64") or ""
            try:
                img_bytes = base64.b64decode(img_b64) if img_b64 else None
            except Exception:
                img_bytes = None
            if strokes_json != (page.get("strokes_json") or "[]") or img_bytes is not None:
                db.save_strokes(page["id"], strokes_json, img_bytes)

    _render_thumbnails(board_key, page_no)


def _render_thumbnails(board_key, current_no):
    pages_meta = db.list_pages(board_key)
    if not pages_meta:
        return
    st.markdown("##### ページ一覧")
    cols_per_row = 6
    rows = [pages_meta[i : i + cols_per_row] for i in range(0, len(pages_meta), cols_per_row)]
    for row in rows:
        cols = st.columns(cols_per_row)
        for col, meta in zip(cols, row):
            with col:
                page_full = db.get_page_by_id(meta["id"])
                thumb = page_full.get("image_png") or page_full.get("bg_data")
                if thumb:
                    st.image(thumb, use_container_width=True)
                else:
                    st.markdown(
                        "<div style='aspect-ratio:1.6;background:#fafafa;"
                        "border:1px solid #ddd;border-radius:4px'></div>",
                        unsafe_allow_html=True,
                    )
                is_cur = meta["page_no"] == current_no
                label = f"● ページ {meta['page_no']}" if is_cur else f"ページ {meta['page_no']}"
                if st.button(label, key=f"thumb_{meta['id']}", use_container_width=True,
                             disabled=is_cur):
                    st.session_state.note_page_no = meta["page_no"]
                    st.rerun()


# ===========================================================================
# Sidebar
# ===========================================================================


st.sidebar.title("工場ホワイトボード")
mode = st.sidebar.radio("モード", ["閲覧", "編集"], horizontal=True, key="mode_radio")
tab_label = st.sidebar.radio(
    "表示",
    ["月予定", "手書きノート"],
    horizontal=True,
    index=0 if st.session_state.active_tab == "calendar" else 1,
    key="tab_radio",
)
st.session_state.active_tab = "calendar" if tab_label == "月予定" else "note"

year = st.sidebar.selectbox("年", list(range(2024, 2031)), index=2)
mon = st.sidebar.selectbox("月", list(range(1, 13)), index=datetime.now().month - 1)
month_key = f"{year:04d}-{mon:02d}"
ndays_in_month = calendar.monthrange(year, mon)[1]
board_key = month_key

if mode == "編集" and st.session_state.active_tab == "calendar":
    with st.sidebar.form("add_card", clear_on_submit=True):
        st.subheader("札を追加")
        a_dest = st.text_input("行先")
        a_truck = st.text_input("車番")
        a_person = st.text_input("氏名")
        a_time = st.text_input("出庫時間")
        a_color = st.selectbox(
            "色", list(COLOR_LABELS), format_func=lambda k: COLOR_LABELS[k]
        )
        a_day = st.selectbox("日", list(range(1, ndays_in_month + 1)))
        if st.form_submit_button("追加", use_container_width=True):
            db.add_card(month_key, a_day, a_dest, a_truck, a_person, a_time, a_color)
            st.session_state.rev += 1
            st.rerun()

if mode == "編集" and st.session_state.active_tab == "note":
    st.sidebar.markdown("---")
    st.sidebar.subheader("ノート操作")

    page_no_now = _clamp_page_no(board_key, st.session_state.note_page_no)
    total_pages = db.count_pages(board_key)

    cc1, cc2 = st.sidebar.columns(2)
    if cc1.button("＋ 新規ページ", use_container_width=True):
        new_page = db.add_page(board_key, after_page_no=page_no_now)
        st.session_state.note_page_no = new_page["page_no"]
        st.session_state.rev += 1
        st.rerun()
    if cc2.button("− 削除", use_container_width=True,
                  disabled=(total_pages <= 1)):
        current = db.get_page(board_key, page_no_now)
        if current:
            db.delete_page(current["id"])
            st.session_state.note_page_no = max(1, page_no_now - 1)
            st.session_state.rev += 1
            st.rerun()

    st.sidebar.markdown("**背景**")
    bg_choice = st.sidebar.radio(
        "種類",
        ["変更しない", "なし(白紙)", "画像", "PDF"],
        index=0,
        horizontal=False,
        key="bg_choice",
    )

    if bg_choice == "なし(白紙)":
        if st.sidebar.button("背景を消す", use_container_width=True):
            current = db.get_page(board_key, page_no_now)
            db.clear_background(current["id"])
            st.session_state.rev += 1
            st.rerun()

    elif bg_choice == "画像":
        up = st.sidebar.file_uploader(
            "画像を選択", type=["png", "jpg", "jpeg", "webp"], key="bg_img_uploader"
        )
        if up and st.sidebar.button("背景に設定", use_container_width=True,
                                    key="set_bg_img"):
            img_bytes = up.read()
            current = db.get_page(board_key, page_no_now)
            db.set_background(current["id"], "image", img_bytes,
                              {"name": up.name})
            st.session_state.rev += 1
            st.rerun()

    elif bg_choice == "PDF":
        up = st.sidebar.file_uploader(
            "PDFを選択", type=["pdf"], key="bg_pdf_uploader"
        )
        if up:
            pdf_bytes = up.read()
            try:
                n_pages = pdf_utils.pdf_page_count(pdf_bytes)
            except Exception as e:
                st.sidebar.error(f"PDF読込失敗: {e}")
                n_pages = 0
            if n_pages > 0:
                st.sidebar.caption(f"全 {n_pages} ページ")
                mode_pdf = st.sidebar.radio(
                    "適用方法",
                    ["現在のページに1ページだけ", "全ページを新規ページとして追加"],
                    key="bg_pdf_mode",
                )
                if mode_pdf == "現在のページに1ページだけ":
                    idx = st.sidebar.number_input(
                        "ページ番号 (1始まり)", 1, n_pages, 1, key="bg_pdf_idx"
                    )
                    if st.sidebar.button("背景に設定", use_container_width=True,
                                         key="set_bg_pdf_one"):
                        try:
                            png = pdf_utils.render_page(pdf_bytes, int(idx) - 1)
                            current = db.get_page(board_key, page_no_now)
                            db.set_background(current["id"], "pdf", png,
                                              {"src": up.name, "pdf_page": int(idx)})
                            st.session_state.rev += 1
                            st.rerun()
                        except Exception as e:
                            st.sidebar.error(f"変換失敗: {e}")
                else:
                    if st.sidebar.button("追加開始", use_container_width=True,
                                         key="set_bg_pdf_all"):
                        try:
                            first_new = None
                            for i, png in enumerate(pdf_utils.render_all_pages(pdf_bytes)):
                                p = db.add_page(board_key)
                                db.set_background(p["id"], "pdf", png,
                                                  {"src": up.name, "pdf_page": i + 1})
                                if first_new is None:
                                    first_new = p["page_no"]
                            if first_new is not None:
                                st.session_state.note_page_no = first_new
                            st.session_state.rev += 1
                            st.rerun()
                        except Exception as e:
                            st.sidebar.error(f"取込失敗: {e}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("エクスポート")
    current_page = db.get_page(board_key, page_no_now)
    if current_page:
        png_bytes = exporter.page_png(current_page)
        st.sidebar.download_button(
            "現ページ PNG ダウンロード",
            data=png_bytes,
            file_name=f"{board_key}_p{page_no_now:02d}.png",
            mime="image/png",
            use_container_width=True,
        )
    all_pages = db.get_all_pages_full(board_key)
    if all_pages:
        try:
            pdf_bytes = exporter.board_pdf(all_pages)
            st.sidebar.download_button(
                "全ページ PDF ダウンロード",
                data=pdf_bytes,
                file_name=f"{board_key}_board.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.sidebar.caption(f"PDF生成失敗: {e}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("共有URL")
    share_link = f"?tab=note&board={board_key}&page={page_no_now}"
    st.sidebar.code(share_link, language="text")
    st.sidebar.caption("このパスを現在のURLに付けると同じページが開きます。")


# ===========================================================================
# Main
# ===========================================================================


st.header(f"第3工場 月予定表 — {year}年{mon}月")

if st.session_state.active_tab == "calendar":
    if mode == "閲覧":
        st.caption("閲覧モード:3秒ごとに自動更新されます。")
        auto_view = st.fragment(run_every="3s")(render_calendar_view)
        auto_view(year, mon, month_key)
    else:
        render_calendar_edit(year, mon, month_key)
else:
    if mode == "閲覧":
        st.caption("閲覧モード:5秒ごとに自動更新されます。")
        auto_view = st.fragment(run_every="5s")(render_note_view)
        auto_view(board_key)
    else:
        render_note_edit(board_key)
