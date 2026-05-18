"""Factory whiteboard prototype — single-page showcase dashboard.

Reproduces the real magnetic whiteboard in one densely-packed Streamlit page:
  - Real-time analog/digital clock, date, weather, KPI header
  - Monthly schedule calendar with magnet-style drag-and-drop cards
  - Today / Tomorrow daily delivery plans as editable tables
  - Tag stock chips (行先 / 車番 / 氏名 / 協力会社) backed by master tables
  - Partner-company breakdown, holiday board, monthly attendance heatmap
  - Multi-page handwriting note (pressure-aware) with PDF/image backgrounds
  - Announcements feed, safety rules, share URL + QR
"""

import base64
import calendar
import io
from datetime import date, datetime, timedelta

import pandas as pd
import qrcode
import streamlit as st

import db
import export as exporter
import pdf_utils
from calendar_component import register_calendar_board
from clock_component import register_clock
from whiteboard_canvas import register_whiteboard_canvas

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]
COLOR_LABELS = {"yellow": "黄", "blue": "青", "orange": "橙", "white": "白"}
WEATHER_OPTIONS = ["☀ 晴れ", "⛅ 晴時々曇", "☁ 曇り", "🌧 雨", "⛈ 雷雨",
                   "❄ 雪", "🌫 霧"]
SAFETY_RULES = [
    "作業前にKY (危険予知) を実施",
    "ヘルメット・安全靴の着用必須",
    "フォークリフト周辺は立入禁止 — 声掛けで合図",
    "異常を発見したら即時通報、勝手な復旧は禁止",
    "6S (整理・整頓・清掃・清潔・躾・作法) を徹底",
]
CANVAS_W = 1280
CANVAS_H = 720

st.set_page_config(
    page_title="工場ホワイトボード Showcase",
    layout="wide",
    page_icon="🏭",
)
db.init_db()

ss = st.session_state
ss.setdefault("rev", 0)
ss.setdefault("note_page_no", 1)
ss.setdefault("authed", False)
ss.setdefault("pin_fails", 0)


def _expected_pin() -> str:
    """PIN resolution order: st.secrets > dashboard_state > default '2318'."""
    try:
        if "PIN_CODE" in st.secrets:
            return str(st.secrets["PIN_CODE"]).strip()
    except Exception:
        pass
    return (db.get_state("pin_code") or "2318").strip()


if not ss.authed:
    st.markdown(
        "<div style='max-width:360px;margin:60px auto;text-align:center'>"
        "<div style='font-size:64px'>🔒</div>"
        "<h2 style='margin:4px 0'>工場ホワイトボード</h2>"
        "<div style='color:#666;margin-bottom:18px'>PINを入力してください</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    _l, _c, _r = st.columns([1, 2, 1])
    with _c:
        with st.form("pin_form", clear_on_submit=True):
            pin_input = st.text_input(
                "PIN", type="password", max_chars=12,
                placeholder="••••", label_visibility="collapsed",
            )
            ok = st.form_submit_button("入室", use_container_width=True,
                                       type="primary")
        if ok:
            if pin_input.strip() == _expected_pin():
                ss.authed = True
                ss.pin_fails = 0
                st.rerun()
            else:
                ss.pin_fails += 1
                st.error(f"PINが違います (試行 {ss.pin_fails} 回)")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🏭 ホワイトボード")
mode = st.sidebar.radio(
    "モード", ["閲覧", "編集"], horizontal=True, key="mode_radio"
)
factory_name = st.sidebar.text_input(
    "工場名", value=db.get_state("factory_name", "第3工場")
)
if factory_name != db.get_state("factory_name", "第3工場"):
    db.set_state("factory_name", factory_name)

today = date.today()
base_date = st.sidebar.date_input("基準日(=当日)", value=today)
tomorrow = base_date + timedelta(days=1)
year, mon = base_date.year, base_date.month
month_key = f"{year:04d}-{mon:02d}"
ndays = calendar.monthrange(year, mon)[1]

weather = st.sidebar.selectbox(
    "天気",
    WEATHER_OPTIONS,
    index=WEATHER_OPTIONS.index(db.get_state("weather", WEATHER_OPTIONS[0]))
    if db.get_state("weather", WEATHER_OPTIONS[0]) in WEATHER_OPTIONS
    else 0,
)
if weather != db.get_state("weather"):
    db.set_state("weather", weather)
temp = st.sidebar.text_input("気温(°C)", db.get_state("temperature", "22"))
if temp != db.get_state("temperature"):
    db.set_state("temperature", temp)

with st.sidebar.expander("📦 マスタ管理", expanded=False):
    st.caption(
        "行先・車番・氏名・協力会社の選択肢(=マスタ)を編集します。"
        " ここで登録した文字列が、当日/翌日表のドロップダウンと"
        " カレンダーの札の構成要素になります。"
    )
    for kind, label in [
        ("destination", "行先"),
        ("truck", "車番"),
        ("person", "氏名"),
        ("partner", "協力会社"),
    ]:
        st.markdown(f"**{label}**")
        rows = [{"label": t["label"], "color": t["color"]} for t in db.list_tags(kind)]
        edited = st.data_editor(
            rows,
            num_rows="dynamic",
            key=f"master_{kind}",
            column_config={
                "label": st.column_config.TextColumn(label, required=True),
                "color": st.column_config.SelectboxColumn(
                    "色", options=list(db.COLORS.keys())
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
        if st.button(f"{label}を保存", key=f"save_master_{kind}",
                     use_container_width=True):
            db.replace_tags(kind, edited)
            ss.rev += 1
            st.rerun()

with st.sidebar.expander("🛌 公休者管理", expanded=False):
    holiday_rows = db.list_holidays(month_key)
    h_df = [
        {"day": r["day"], "person": r["person"], "shift": r["shift"],
         "note": r["note"]}
        for r in holiday_rows
    ]
    h_edit = st.data_editor(
        h_df,
        num_rows="dynamic",
        key="holiday_editor",
        column_config={
            "day": st.column_config.NumberColumn("日", min_value=1, max_value=31),
            "person": st.column_config.SelectboxColumn(
                "氏名", options=db.tag_labels("person"),
            ),
            "shift": st.column_config.SelectboxColumn(
                "区分", options=["day", "night"]
            ),
            "note": st.column_config.TextColumn("備考"),
        },
        use_container_width=True, hide_index=True,
    )
    if st.button("公休を保存", use_container_width=True, key="save_holidays"):
        db.replace_holidays(month_key, h_edit)
        ss.rev += 1
        st.rerun()

with st.sidebar.expander("📣 お知らせ投稿", expanded=False):
    with st.form("ann_form", clear_on_submit=True):
        new_ann = st.text_area("お知らせ本文", "")
        ac1, ac2 = st.columns(2)
        ann_level = ac1.selectbox("種別", ["info", "warn", "alert"])
        ann_pin = ac2.checkbox("ピン留め")
        if st.form_submit_button("投稿", use_container_width=True):
            db.add_announcement(new_ann, ann_level, ann_pin)
            ss.rev += 1
            st.rerun()

with st.sidebar.expander("🔐 セキュリティ", expanded=False):
    st.caption(
        "PIN は st.secrets > DB > デフォルト'2318' の順で解決されます。"
        " Streamlit Cloud では Settings → Secrets に "
        "`PIN_CODE = \"xxxx\"` を設定すると DB より優先されます。"
    )
    with st.form("pin_change_form", clear_on_submit=True):
        new_pin = st.text_input("新しいPIN", type="password", max_chars=12)
        confirm = st.text_input("確認", type="password", max_chars=12)
        if st.form_submit_button("PINを変更", use_container_width=True):
            new_pin = (new_pin or "").strip()
            if not new_pin:
                st.warning("空のPINは設定できません")
            elif new_pin != (confirm or "").strip():
                st.warning("確認用PINが一致しません")
            else:
                db.set_state("pin_code", new_pin)
                st.success("PINを更新しました。次回ログインから有効です。")

if st.sidebar.button("🚪 ログアウト", use_container_width=True):
    ss.authed = False
    st.rerun()

# ---------------------------------------------------------------------------
# Header (title + clock + weather + KPI)
# ---------------------------------------------------------------------------

st.markdown(
    f"<h1 style='margin-bottom:0'>{factory_name} 電子ホワイトボード</h1>"
    f"<div style='color:#666;margin-bottom:8px'>"
    f"基準日: {base_date.strftime('%Y-%m-%d (')}{WEEKDAY_JA[base_date.weekday()]}"
    f")  /  モード: <b>{mode}</b></div>",
    unsafe_allow_html=True,
)

hcol1, hcol2 = st.columns([2, 1])
with hcol1:
    register_clock()(key=f"clock_{ss.rev}", data={}, height=110)
with hcol2:
    st.markdown(
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px 14px;"
        f"background:#fafcff;text-align:center'>"
        f"<div style='font-size:42px;line-height:1'>{weather.split()[0]}</div>"
        f"<div style='font-size:14px;color:#555'>{' '.join(weather.split()[1:])} / {temp}°C</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _kpi_card(label, value, sub=""):
    return (
        "<div style='border:1px solid #e0e0e0;border-radius:8px;padding:10px 12px;"
        "background:#fff'>"
        f"<div style='font-size:12px;color:#666'>{label}</div>"
        f"<div style='font-size:24px;font-weight:bold'>{value}</div>"
        f"<div style='font-size:11px;color:#888'>{sub}</div>"
        "</div>"
    )


cards_today = db.get_cards_by_day(month_key, base_date.day)
cards_tomorrow = db.get_cards_by_day(month_key, tomorrow.day) if tomorrow.month == mon else []
all_cards_month = db.get_cards(month_key)
unique_drivers_today = len({c["person"] for c in cards_today if c["person"]})
unique_trucks_today = len({c["truck"] for c in cards_today if c["truck"]})
partners_today = len({c["partner"] for c in cards_today if c["partner"]})
holidays_today = [h for h in db.list_holidays(month_key) if h["day"] == base_date.day]
announcements = db.list_announcements(limit=10)

kpi_cols = st.columns(6)
kpis = [
    _kpi_card("当日 便数", len(cards_today), f"翌日 {len(cards_tomorrow)} 便"),
    _kpi_card("稼働ドライバ", unique_drivers_today,
              f"マスタ {len(db.tag_labels('person'))} 名"),
    _kpi_card("稼働車両", unique_trucks_today,
              f"マスタ {len(db.tag_labels('truck'))} 台"),
    _kpi_card("協力会社", partners_today,
              " / ".join(db.tag_labels('partner')[:3]) or "—"),
    _kpi_card("公休 (本日)", len(holidays_today),
              f"月計 {len(db.list_holidays(month_key))} 名"),
    _kpi_card("お知らせ", len(announcements),
              "ピン留め " + str(sum(1 for a in announcements if a['pinned']))),
]
for col, html in zip(kpi_cols, kpis):
    col.markdown(html, unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Main board row: 月予定 + 当日 + 翌日
# ---------------------------------------------------------------------------

st.subheader("📅 メインボード")
main_l, main_c, main_r = st.columns([5, 3, 3])


def card_text(c):
    parts = [c.get("destination"), c.get("truck"), c.get("person"), c.get("time")]
    return " ".join(p for p in parts if p)


# ---- 月間予定 ----
with main_l:
    st.markdown("##### 月間予定表")
    cb_data = {
        "year": year, "month": mon,
        "ndays": ndays,
        "first_weekday": calendar.weekday(year, mon, 1),
        "weekday_names": WEEKDAY_JA,
        "colors": db.COLORS,
        "cards": [
            {"id": c["id"], "day": c["day"],
             "text": card_text(c) or "(空札)",
             "color": c["color"]}
            for c in all_cards_month
        ],
    }
    cb = register_calendar_board()
    layout_result = cb(
        key=f"cal_{month_key}_{ss.rev}",
        data=cb_data,
        height="content",
        on_layout_change=lambda: None,
    )
    layout = layout_result.get("layout") if layout_result else None
    if layout and mode == "編集":
        current = {c["id"]: (c["day"], c["sort_order"]) for c in all_cards_month}
        changed = [
            (int(it["id"]), int(it["day"]), int(it["order"]))
            for it in layout
            if current.get(int(it["id"])) != (int(it["day"]), int(it["order"]))
        ]
        if changed:
            db.set_positions(changed)

# ---- 当日 / 翌日 ----


def render_day_editor(label, day_int, key_suffix):
    rows = db.get_cards_by_day(month_key, day_int)
    df = pd.DataFrame(
        [
            {
                "destination": r["destination"],
                "truck": r["truck"],
                "person": r["person"],
                "time": r["time"],
                "partner": r.get("partner") or "自社",
                "color": r["color"],
            }
            for r in rows
        ],
        columns=["destination", "truck", "person", "time", "partner", "color"],
    )
    st.markdown(f"##### {label}")
    st.caption(f"{day_int}日 / {len(rows)} 便")
    edited = st.data_editor(
        df,
        num_rows="dynamic" if mode == "編集" else "fixed",
        disabled=(mode != "編集"),
        key=f"daily_{key_suffix}_{ss.rev}",
        column_config={
            "destination": st.column_config.SelectboxColumn(
                "行先", options=db.tag_labels("destination")
            ),
            "truck": st.column_config.SelectboxColumn(
                "車番", options=db.tag_labels("truck")
            ),
            "person": st.column_config.SelectboxColumn(
                "氏名", options=db.tag_labels("person")
            ),
            "time": st.column_config.TextColumn("出庫"),
            "partner": st.column_config.SelectboxColumn(
                "協力", options=db.tag_labels("partner")
            ),
            "color": st.column_config.SelectboxColumn(
                "色", options=list(db.COLORS.keys())
            ),
        },
        use_container_width=True,
        hide_index=True,
    )
    if mode == "編集" and st.button(
        f"💾 {label} 保存", key=f"save_{key_suffix}",
        use_container_width=True,
    ):
        db.replace_cards_for_day(month_key, day_int, edited.to_dict(orient="records"))
        ss.rev += 1
        st.rerun()


with main_c:
    render_day_editor(f"当日 {base_date.month}/{base_date.day} "
                      f"({WEEKDAY_JA[base_date.weekday()]})",
                      base_date.day, "today")

with main_r:
    if tomorrow.month == mon:
        render_day_editor(f"翌日 {tomorrow.month}/{tomorrow.day} "
                          f"({WEEKDAY_JA[tomorrow.weekday()]})",
                          tomorrow.day, "tomorrow")
    else:
        st.markdown(f"##### 翌日 {tomorrow.month}/{tomorrow.day} (翌月)")
        st.caption("翌月のため当画面では編集対象外です。月選択で翌月へ移動してください。")

st.markdown("---")

# ---------------------------------------------------------------------------
# 協力会社別 + 公休 + 出勤表
# ---------------------------------------------------------------------------

pa_col, hd_col, at_col = st.columns([3, 2, 4])

with pa_col:
    st.subheader("🤝 協力会社別 (当日)")
    by_partner = {}
    for c in cards_today:
        by_partner.setdefault(c.get("partner") or "自社", []).append(c)
    if not by_partner:
        st.caption("本日の便はまだ登録されていません。")
    for partner in db.tag_labels("partner"):
        items = by_partner.get(partner, [])
        st.markdown(
            f"**{partner}** "
            f"<span style='color:#666;font-size:12px'>{len(items)} 便</span>",
            unsafe_allow_html=True,
        )
        if not items:
            st.markdown(
                "<div style='color:#999;font-size:12px;margin-bottom:6px'>—</div>",
                unsafe_allow_html=True,
            )
            continue
        body = "".join(
            f"<div style='background:{db.COLORS.get(c['color'], '#eee')};"
            f"border:1px solid #aaa;border-radius:4px;padding:4px 8px;margin:2px 0;"
            f"font-size:12px'>"
            f"{c.get('time','') and (c['time']+' ')}"
            f"{c.get('destination','')} / {c.get('truck','')} / {c.get('person','')}"
            f"</div>"
            for c in items
        )
        st.markdown(body, unsafe_allow_html=True)

with hd_col:
    st.subheader("🛌 公休者ボード")
    hol = db.list_holidays(month_key)
    if not hol:
        st.caption("今月の公休登録はありません。")
    day_shift = [h for h in hol if h["shift"] == "day"]
    night_shift = [h for h in hol if h["shift"] == "night"]
    st.markdown(f"**日勤公休** ({len(day_shift)}名)")
    for h in day_shift:
        st.markdown(
            f"<div style='border-left:4px solid #2196f3;padding:3px 8px;margin:2px 0;"
            f"background:#f0f8ff'>"
            f"{h['day']}日 {h['person']}"
            f"{(' / ' + h['note']) if h['note'] else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.markdown(f"**夜勤公休** ({len(night_shift)}名)")
    for h in night_shift:
        st.markdown(
            f"<div style='border-left:4px solid #7e57c2;padding:3px 8px;margin:2px 0;"
            f"background:#f6f3fa'>"
            f"{h['day']}日 {h['person']}"
            f"{(' / ' + h['note']) if h['note'] else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )

with at_col:
    st.subheader("🗓 出勤表 (月間ヒートマップ)")
    persons = db.tag_labels("person")
    hol_set = {(h["day"], h["person"]) for h in db.list_holidays(month_key)}
    work_set = set()
    for c in all_cards_month:
        if c.get("person"):
            work_set.add((c["day"], c["person"]))
    if not persons:
        st.caption("マスタに氏名がありません。サイドバーから登録してください。")
    else:
        header_row = "<tr><th style='background:#f4f4f4'></th>" + "".join(
            f"<th style='background:#f4f4f4;font-size:11px'>{d}</th>"
            for d in range(1, ndays + 1)
        ) + "</tr>"
        body = ""
        for p in persons:
            cells = ""
            for d in range(1, ndays + 1):
                cls = ""
                txt = ""
                if (d, p) in hol_set:
                    cls = "background:#ffe0e0"
                    txt = "休"
                elif (d, p) in work_set:
                    cls = "background:#c8e6c9"
                    txt = "○"
                else:
                    cls = "background:#fff"
                cells += (
                    f"<td style='border:1px solid #ddd;width:18px;height:20px;"
                    f"text-align:center;font-size:10px;{cls}'>{txt}</td>"
                )
            body += (
                f"<tr><th style='font-size:11px;text-align:left;padding-right:4px;"
                f"white-space:nowrap'>{p}</th>{cells}</tr>"
            )
        st.markdown(
            f"<div style='overflow-x:auto'>"
            f"<table style='border-collapse:collapse'>{header_row}{body}</table>"
            f"</div>"
            f"<div style='font-size:11px;color:#666;margin-top:4px'>"
            f"○=便あり / 休=公休 / 空=未登録</div>",
            unsafe_allow_html=True,
        )

st.markdown("---")

# ---------------------------------------------------------------------------
# 手書きノート
# ---------------------------------------------------------------------------

st.subheader("✏ 手書きノート")
note_board_key = f"note_{month_key}"


def _clamp(no):
    total = db.count_pages(note_board_key)
    if total == 0:
        db.ensure_page(note_board_key, 1)
        return 1
    return max(1, min(no, total))


page_no = _clamp(ss.note_page_no)
ss.note_page_no = page_no
total_pages = db.count_pages(note_board_key)
page = db.ensure_page(note_board_key, page_no)

note_nav = st.columns([1, 1, 4, 1, 1, 2])
if note_nav[0].button("◀", key="nb_prev", disabled=(page_no <= 1),
                      use_container_width=True):
    ss.note_page_no = page_no - 1
    st.rerun()
note_nav[1].markdown(
    f"<div style='text-align:center;font-weight:bold;padding-top:6px'>"
    f"P {page_no} / {total_pages}</div>",
    unsafe_allow_html=True,
)
if note_nav[2].button("📃 + 新規ページ", use_container_width=True,
                       disabled=(mode != "編集")):
    new_p = db.add_page(note_board_key, after_page_no=page_no)
    ss.note_page_no = new_p["page_no"]
    ss.rev += 1
    st.rerun()
if note_nav[3].button("✖ 削除", key="nb_del", use_container_width=True,
                       disabled=(mode != "編集" or total_pages <= 1)):
    db.delete_page(page["id"])
    ss.note_page_no = max(1, page_no - 1)
    ss.rev += 1
    st.rerun()
if note_nav[4].button("▶", key="nb_next", disabled=(page_no >= total_pages),
                      use_container_width=True):
    ss.note_page_no = page_no + 1
    st.rerun()


bg_b64 = None
if page.get("bg_data") and page.get("bg_type") != "blank":
    bg_b64 = base64.b64encode(page["bg_data"]).decode("ascii")

if mode == "編集":
    bg_exp = st.expander("🖼 背景 (画像 / PDF)")
    with bg_exp:
        bg_kind = st.radio("背景", ["変更しない", "なし", "画像", "PDF"],
                           horizontal=True, key="bg_kind")
        if bg_kind == "なし" and st.button("背景を消す", key="bg_clear"):
            db.clear_background(page["id"])
            ss.rev += 1
            st.rerun()
        elif bg_kind == "画像":
            up = st.file_uploader("画像を選択",
                                  type=["png", "jpg", "jpeg", "webp"],
                                  key="bg_img")
            if up and st.button("背景に設定", key="bg_img_apply"):
                db.set_background(page["id"], "image", up.read(),
                                  {"name": up.name})
                ss.rev += 1
                st.rerun()
        elif bg_kind == "PDF":
            up = st.file_uploader("PDFを選択", type=["pdf"], key="bg_pdf")
            if up:
                pdf_bytes = up.read()
                try:
                    n = pdf_utils.pdf_page_count(pdf_bytes)
                except Exception as e:
                    st.error(f"PDF読込失敗: {e}")
                    n = 0
                if n > 0:
                    way = st.radio("適用",
                                   ["現ページのみ", "全ページ追加"],
                                   horizontal=True, key="bg_pdf_way")
                    if way == "現ページのみ":
                        idx = st.number_input("ページ (1始まり)", 1, n, 1,
                                              key="bg_pdf_idx")
                        if st.button("適用", key="bg_pdf_one"):
                            png = pdf_utils.render_page(pdf_bytes, int(idx) - 1)
                            db.set_background(page["id"], "pdf", png,
                                              {"src": up.name,
                                               "pdf_page": int(idx)})
                            ss.rev += 1
                            st.rerun()
                    else:
                        if st.button("一括追加", key="bg_pdf_all"):
                            first_new = None
                            for i, png in enumerate(
                                pdf_utils.render_all_pages(pdf_bytes)
                            ):
                                p = db.add_page(note_board_key)
                                db.set_background(p["id"], "pdf", png,
                                                  {"src": up.name,
                                                   "pdf_page": i + 1})
                                if first_new is None:
                                    first_new = p["page_no"]
                            if first_new is not None:
                                ss.note_page_no = first_new
                            ss.rev += 1
                            st.rerun()

if mode == "編集":
    component = register_whiteboard_canvas()
    payload = component(
        key=f"wb_{page['id']}_{ss.rev}",
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
            sj = done.get("strokes_json") or "[]"
            try:
                img_bytes = (
                    base64.b64decode(done["image_png_b64"])
                    if done.get("image_png_b64") else None
                )
            except Exception:
                img_bytes = None
            db.save_strokes(page["id"], sj, img_bytes)
else:
    if page.get("image_png"):
        st.image(page["image_png"], use_container_width=True)
    elif page.get("bg_data"):
        st.image(page["bg_data"], use_container_width=True)
    else:
        st.caption("(空白ページ)")

# Export
exp_cols = st.columns([1, 1, 6])
all_pages_full = db.get_all_pages_full(note_board_key)
if page:
    exp_cols[0].download_button(
        "🖼 現ページPNG",
        data=exporter.page_png(page),
        file_name=f"{note_board_key}_p{page_no:02d}.png",
        mime="image/png", use_container_width=True,
    )
if all_pages_full:
    try:
        exp_cols[1].download_button(
            "📄 全ページPDF",
            data=exporter.board_pdf(all_pages_full),
            file_name=f"{note_board_key}.pdf",
            mime="application/pdf", use_container_width=True,
        )
    except Exception as e:
        exp_cols[1].caption(f"PDF生成失敗: {e}")

# Thumbnails
if all_pages_full:
    st.markdown("###### ページサムネ")
    cols_per = 8
    for i in range(0, len(all_pages_full), cols_per):
        cols = st.columns(cols_per)
        for col, p in zip(cols, all_pages_full[i : i + cols_per]):
            with col:
                thumb = p.get("image_png") or p.get("bg_data")
                if thumb:
                    st.image(thumb, use_container_width=True)
                else:
                    st.markdown(
                        "<div style='aspect-ratio:1.6;background:#fafafa;"
                        "border:1px solid #ddd;border-radius:4px'></div>",
                        unsafe_allow_html=True,
                    )
                cur = p["page_no"] == page_no
                if st.button(
                    f"{'●' if cur else ''} P{p['page_no']}",
                    key=f"thumb_{p['id']}",
                    use_container_width=True,
                    disabled=cur,
                ):
                    ss.note_page_no = p["page_no"]
                    st.rerun()

st.markdown("---")

# ---------------------------------------------------------------------------
# Footer: announcements + safety + share QR
# ---------------------------------------------------------------------------

f1, f2, f3 = st.columns([4, 3, 2])

with f1:
    st.subheader("📣 お知らせ")
    if not announcements:
        st.caption("お知らせはありません。")
    for a in announcements:
        bg = {
            "info": "#eef5fb",
            "warn": "#fff8e1",
            "alert": "#ffebee",
        }.get(a["level"], "#fafafa")
        border = {
            "info": "#1976d2",
            "warn": "#f9a825",
            "alert": "#c62828",
        }.get(a["level"], "#999")
        pin = "📌 " if a["pinned"] else ""
        ts = a.get("created_at", "")
        cols = st.columns([10, 1])
        cols[0].markdown(
            f"<div style='background:{bg};border-left:4px solid {border};"
            f"padding:6px 10px;margin:4px 0;border-radius:0 4px 4px 0'>"
            f"<div style='font-size:13px;font-weight:500'>{pin}{a['text']}</div>"
            f"<div style='font-size:10px;color:#777'>{ts}</div></div>",
            unsafe_allow_html=True,
        )
        if mode == "編集" and cols[1].button(
            "✖", key=f"del_ann_{a['id']}", use_container_width=True
        ):
            db.delete_announcement(a["id"])
            ss.rev += 1
            st.rerun()

with f2:
    st.subheader("🦺 安全訓")
    st.markdown(
        "<ol style='padding-left:18px;line-height:1.6'>"
        + "".join(f"<li>{r}</li>" for r in SAFETY_RULES)
        + "</ol>",
        unsafe_allow_html=True,
    )

with f3:
    st.subheader("🔗 共有")
    share_url = (
        f"{st.context.headers.get('host', 'localhost')}"
        f"?factory={factory_name}&date={base_date.isoformat()}"
    )
    try:
        host_full = "https://" + st.context.headers.get("host", "localhost")
    except Exception:
        host_full = "https://localhost"
    full_url = f"{host_full}/?date={base_date.isoformat()}"
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(full_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    st.image(buf.getvalue(), use_container_width=True)
    st.code(full_url, language="text")

st.markdown(
    "<div style='text-align:center;color:#999;font-size:11px;margin-top:24px'>"
    "工場ホワイトボード ショーケース — "
    f"DB rev {ss.rev} / 最終アクセス {datetime.now().strftime('%H:%M:%S')}"
    "</div>",
    unsafe_allow_html=True,
)
