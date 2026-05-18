"""Factory whiteboard prototype — single-page showcase dashboard.

Reproduces the real magnetic whiteboard observed in the reference photos:
  - Real-time clock, weather, KPI header
  - お知らせ + 安全訓 (prominent, just below KPI)
  - 月間予定カレンダー (drag-and-drop magnet cards + event bands)
  - 当日 / 翌日 daily delivery plans (always editable)
  - 協力会社別 / 公休者ボード / 出勤ヒートマップ
  - 手書きノート (foldable; for annotating PDF/image backgrounds)
  - 共有URL + QR (footer)
PIN-gated. No more view/edit mode toggle — everything is always editable.
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
EVENT_COLOR_LABELS = {"red": "赤", "orange": "橙", "blue": "青",
                      "green": "緑", "gray": "灰"}
SHIFT_LABELS = {"day": "日勤", "night": "夜勤"}
CANVAS_W = 1280
CANVAS_H = 720

st.set_page_config(
    page_title="工場ホワイトボード",
    layout="wide",
    page_icon="🏭",
)
db.init_db()
db.seed_demo_data()

ss = st.session_state
ss.setdefault("rev", 0)
ss.setdefault("note_page_no", 1)


# ---------------------------------------------------------------------------
# Routing — ?view=day opens the read-only mobile daily viewer.
# The ?date=YYYY-MM-DD param selects which day to show (and is reused as the
# 基準日 on the editable dashboard). The QR code points at ?view=day.
# ---------------------------------------------------------------------------


def _parse_iso(s):
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


param_date = _parse_iso(st.query_params.get("date", ""))
view_mode = st.query_params.get("view", "")


def render_mobile_day_view(view_date):
    """Read-only, single-column view of one day's deliveries — for phones."""
    factory_name = db.get_state("factory_name", "第3工場")
    weather = db.get_state("weather", WEATHER_OPTIONS[0])
    temp = db.get_state("temperature", "22")
    mk = f"{view_date.year:04d}-{view_date.month:02d}"
    cards = db.get_cards_by_day(mk, view_date.day)
    holidays = [h for h in db.list_holidays(mk) if h["day"] == view_date.day]
    events = [e for e in db.list_events(mk)
              if e["day"] <= view_date.day < e["day"] + e["span_days"]]
    anns = db.list_announcements(limit=10)

    st.sidebar.title("📱 当日ビュー")
    st.sidebar.caption("読み取り専用 — 当日便の一覧です。")
    nav_date = st.sidebar.date_input("表示日", value=view_date)
    if nav_date != view_date:
        st.query_params["date"] = nav_date.isoformat()
        st.rerun()
    if st.sidebar.button("🖥 編集ビューへ切替", use_container_width=True,
                         type="primary"):
        if "view" in st.query_params:
            del st.query_params["view"]
        st.rerun()

    wd = WEEKDAY_JA[view_date.weekday()]
    st.markdown(
        f"<h2 style='margin:0'>{factory_name}</h2>"
        f"<div style='font-size:22px;font-weight:bold;margin:2px 0'>"
        f"{view_date.strftime('%Y-%m-%d')} ({wd})</div>"
        f"<div style='color:#555'>{weather} / {temp}°C</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    pinned = [a for a in anns if a["pinned"]]
    for a in pinned:
        st.markdown(
            f"<div style='background:#fff8e1;border-left:4px solid #f9a825;"
            f"padding:8px 10px;margin:4px 0;border-radius:0 6px 6px 0;"
            f"font-weight:500'>📌 {a['text']}</div>",
            unsafe_allow_html=True,
        )

    st.subheader(f"🚚 当日便 ({len(cards)} 便)")
    if not cards:
        st.info("本日の便は登録されていません。")
    else:
        by_partner = {}
        for c in cards:
            by_partner.setdefault(c.get("partner") or "自社", []).append(c)
        for partner, items in by_partner.items():
            st.markdown(
                f"<div style='font-weight:600;margin:8px 0 2px'>"
                f"{partner} <span style='color:#888'>{len(items)} 便</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            for c in items:
                bg = db.COLORS.get(c["color"], "#eee")
                time_txt = c.get("time", "")
                line2 = " / ".join(
                    p for p in [c.get("truck"), c.get("person")] if p
                )
                st.markdown(
                    f"<div style='background:{bg};border:1px solid #999;"
                    f"border-radius:6px;padding:8px 12px;margin:4px 0'>"
                    f"<div style='font-size:17px;font-weight:bold'>"
                    f"{(time_txt + ' ') if time_txt else ''}"
                    f"{c.get('destination', '') or '(行先未定)'}</div>"
                    f"<div style='color:#444;font-size:15px'>{line2}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    if events:
        st.subheader("📅 本日の予定")
        for e in events:
            st.markdown(
                f"<div style='background:"
                f"{db.EVENT_COLORS.get(e['color'], '#c0392b')};color:#fff;"
                f"border-radius:6px;padding:8px 12px;margin:4px 0;"
                f"font-weight:600'>{e['title']}"
                f"{(' — ' + e['note']) if e['note'] else ''}</div>",
                unsafe_allow_html=True,
            )

    if holidays:
        st.subheader("🛌 本日の公休")
        for h in holidays:
            st.markdown(
                f"<div style='border-left:4px solid #2196f3;padding:6px 12px;"
                f"margin:4px 0;background:#f0f8ff;font-size:15px'>"
                f"{h['person']} ({SHIFT_LABELS.get(h['shift'], h['shift'])})"
                f"{(' / ' + h['note']) if h['note'] else ''}</div>",
                unsafe_allow_html=True,
            )

    st.markdown(
        "<div style='color:#999;padding-top:16px;text-align:center'>"
        "工場ホワイトボード — 当日ビュー (読み取り専用)</div>",
        unsafe_allow_html=True,
    )


if view_mode == "day":
    render_mobile_day_view(param_date or date.today())
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


st.sidebar.title("🏭 ホワイトボード")

factory_name = st.sidebar.text_input(
    "工場名", value=db.get_state("factory_name", "第3工場")
)
if factory_name != db.get_state("factory_name", "第3工場"):
    db.set_state("factory_name", factory_name)

today = date.today()
base_date = st.sidebar.date_input("基準日 (=当日)", value=param_date or today)
tomorrow = base_date + timedelta(days=1)
year, mon = base_date.year, base_date.month
month_key = f"{year:04d}-{mon:02d}"
ndays = calendar.monthrange(year, mon)[1]

if st.sidebar.button("📱 当日ビューへ切替", use_container_width=True):
    st.query_params["view"] = "day"
    st.query_params["date"] = base_date.isoformat()
    st.rerun()

_w_default = db.get_state("weather", WEATHER_OPTIONS[0])
weather = st.sidebar.selectbox(
    "天気",
    WEATHER_OPTIONS,
    index=WEATHER_OPTIONS.index(_w_default)
    if _w_default in WEATHER_OPTIONS else 0,
)
if weather != db.get_state("weather"):
    db.set_state("weather", weather)
temp = st.sidebar.text_input("気温 (°C)", db.get_state("temperature", "22"))
if temp != db.get_state("temperature"):
    db.set_state("temperature", temp)

st.sidebar.markdown("---")

# --- お知らせ投稿 ----------------------------------------------------------
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

# --- 配車予定 (駒台に追加。日付は駒台 → カレンダーへドラッグで設定) -------
with st.sidebar.expander("🚚 配車予定", expanded=False):
    st.caption(
        "札(配車1便分)を作成して駒台に置きます。"
        " 駒台からカレンダーの日付へドラッグして配置してください。"
    )
    with st.form("add_card_stock_form", clear_on_submit=True):
        c_dest = st.selectbox("行先", [""] + db.tag_labels("destination"))
        c_truck = st.selectbox("車番", [""] + db.tag_labels("truck"))
        c_person = st.selectbox("氏名", [""] + db.tag_labels("person"))
        c_time = st.text_input("出庫時間")
        c_partner = st.selectbox(
            "協力会社", db.tag_labels("partner") or ["自社"]
        )
        c_color = st.selectbox("色", list(db.COLORS.keys()))
        if st.form_submit_button("➕ 駒台に追加",
                                 use_container_width=True, type="primary"):
            if not any([c_dest, c_truck, c_person, c_time]):
                st.warning("行先・車番・氏名・時間 のいずれかを入れてください。")
            else:
                db.add_card_to_stock(
                    c_dest, c_truck, c_person, c_time, c_color, c_partner
                )
                ss.rev += 1
                st.rerun()

    stock_cards_side = db.get_stock_cards()
    if stock_cards_side:
        st.markdown(f"**駒台にある札 ({len(stock_cards_side)} 件)**")
        for c in stock_cards_side:
            label_parts = [c.get("destination"), c.get("truck"), c.get("person")]
            label = " / ".join(p for p in label_parts if p) or "(空札)"
            bg = db.COLORS.get(c["color"], "#eee")
            st.markdown(
                f"<div style='background:{bg};border:1px solid #888;"
                f"border-radius:3px;padding:2px 6px;margin:2px 0;"
                f"'>{label}</div>",
                unsafe_allow_html=True,
            )
            tc = st.columns([3, 1, 1])
            new_time = tc[0].text_input(
                "出庫時間",
                value=c.get("time", ""),
                key=f"stk_time_{c['id']}",
                label_visibility="collapsed",
                placeholder="HH:MM",
            )
            if new_time != (c.get("time") or ""):
                db.update_card(c["id"], time=new_time)
                ss.rev += 1
                st.rerun()
            if tc[1].button("📋", key=f"copy_stock_card_{c['id']}",
                            use_container_width=True, help="コピーして駒台に追加"):
                db.add_card_to_stock(
                    c["destination"], c["truck"], c["person"],
                    c.get("time", ""), c["color"], c.get("partner") or "自社",
                )
                ss.rev += 1
                st.rerun()
            if tc[2].button("✖", key=f"del_stock_card_{c['id']}",
                            use_container_width=True, help="削除"):
                db.delete_card(c["id"])
                ss.rev += 1
                st.rerun()

# --- イベント (駒台に追加。日付はカレンダーへドラッグで設定) --------------
with st.sidebar.expander("📅 月予定イベント", expanded=False):
    st.caption(
        "全社会・休業日・定期点検など、月予定に帯表示するイベント。"
        " 駒台に追加 → カレンダーへドラッグで配置。"
    )
    with st.form("add_event_stock_form", clear_on_submit=True):
        e_title = st.text_input("タイトル",
                                placeholder="全社会 / 夏期休業 / 定期点検")
        e_span = st.number_input("日数", min_value=1, max_value=31, value=1)
        e_color = st.selectbox(
            "色",
            list(EVENT_COLOR_LABELS.keys()),
            format_func=lambda k: EVENT_COLOR_LABELS[k],
        )
        e_note = st.text_input("備考 (任意)")
        if st.form_submit_button("➕ 駒台に追加",
                                 use_container_width=True, type="primary"):
            if not e_title.strip():
                st.warning("タイトルを入れてください。")
            else:
                db.add_event_to_stock(e_title, e_color, e_span, e_note)
                ss.rev += 1
                st.rerun()

    stock_events_side = db.get_stock_events()
    if stock_events_side:
        st.markdown(f"**駒台にあるイベント ({len(stock_events_side)} 件)**")
        for ev in stock_events_side:
            cc = st.columns([6, 1])
            span_txt = (
                f" (×{ev['span_days']}日)" if ev["span_days"] > 1 else ""
            )
            cc[0].markdown(
                f"<div style='background:{db.EVENT_COLORS.get(ev['color'], '#c0392b')};"
                f"color:#fff;border-radius:3px;padding:2px 6px;margin:2px 0;"
                f"font-weight:600'>"
                f"{ev['title']}{span_txt}</div>",
                unsafe_allow_html=True,
            )
            if cc[1].button("✖", key=f"del_stock_ev_{ev['id']}",
                            use_container_width=True):
                db.delete_event(ev["id"])
                ss.rev += 1
                st.rerun()

# --- 公休者管理 (日付あり / フォーム形式) ---------------------------------
with st.sidebar.expander("🛌 公休者管理", expanded=False):
    persons = db.tag_labels("person")
    with st.form("add_holiday_form", clear_on_submit=True):
        st.caption(f"{month_key} の公休を1件ずつ追加します。")
        h_day = st.number_input("日", min_value=1, max_value=ndays,
                                value=min(base_date.day, ndays))
        if persons:
            h_person = st.selectbox("氏名", persons)
        else:
            h_person = None
            st.warning("マスタの氏名が未登録です。")
        h_shift = st.radio(
            "区分", list(SHIFT_LABELS.keys()),
            format_func=lambda k: SHIFT_LABELS[k],
            horizontal=True,
        )
        h_note = st.text_input("備考 (任意)")
        if st.form_submit_button("追加", use_container_width=True,
                                 disabled=not persons):
            db.add_holiday(month_key, h_day, h_person, h_shift, h_note)
            ss.rev += 1
            st.rerun()

    existing = db.list_holidays(month_key)
    if existing:
        st.markdown("**登録済み**")
        for h in existing:
            cc = st.columns([6, 1])
            cc[0].markdown(
                f"<div style='padding:2px 0'>"
                f"{h['day']}日 / {h['person']} ({SHIFT_LABELS.get(h['shift'], h['shift'])})"
                f"{(' / ' + h['note']) if h['note'] else ''}</div>",
                unsafe_allow_html=True,
            )
            if cc[1].button("✖", key=f"del_h_{h['id']}",
                            use_container_width=True):
                db.delete_holiday(h["id"])
                ss.rev += 1
                st.rerun()

# --- マスタ管理 ----------------------------------------------------------
with st.sidebar.expander("📦 マスタ管理", expanded=False):
    st.caption(
        "行先・車番・氏名・協力会社の選択肢を編集します。"
        " 配車予定/公休者のドロップダウンの元になります。"
    )
    for kind, m_label in [
        ("destination", "行先"),
        ("truck", "車番"),
        ("person", "氏名"),
        ("partner", "協力会社"),
    ]:
        st.markdown(f"**{m_label}**")
        rows = [{"label": t["label"], "color": t["color"]}
                for t in db.list_tags(kind)]
        master_df = pd.DataFrame(
            rows if rows else [],
            columns=["label", "color"],
        )
        edited = st.data_editor(
            master_df,
            num_rows="dynamic",
            key=f"master_{kind}",
            column_config={
                "label": st.column_config.TextColumn(m_label, required=True),
                "color": st.column_config.SelectboxColumn(
                    "色", options=list(db.COLORS.keys())
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
        if st.button(f"{m_label} を保存", key=f"save_master_{kind}",
                     use_container_width=True):
            out = edited.to_dict(orient="records") if hasattr(edited, "to_dict") else list(edited)
            db.replace_tags(kind, out)
            ss.rev += 1
            st.rerun()



# ---------------------------------------------------------------------------
# Common data
# ---------------------------------------------------------------------------

def _mk(d):
    return f"{d.year:04d}-{d.month:02d}"


tomorrow_mk = _mk(tomorrow)
cards_today = db.get_cards_by_day(month_key, base_date.day)
cards_tomorrow = db.get_cards_by_day(tomorrow_mk, tomorrow.day)

# 28-day rolling window starting at base_date
window_days = [base_date + timedelta(days=i) for i in range(28)]
window_mks = sorted({_mk(d) for d in window_days})

window_cards_by_mk = {mk: db.get_cards(mk) for mk in window_mks}
window_events_by_mk = {mk: db.list_events(mk) for mk in window_mks}

all_cards_month = db.get_cards(month_key)
all_events_month = db.list_events(month_key)
holidays_month = db.list_holidays(month_key)
announcements = db.list_announcements(limit=10)


# ---------------------------------------------------------------------------
# Header (title + clock + weather)
# ---------------------------------------------------------------------------

st.markdown(
    f"<h1 style='margin:0 0 4px 0'>{factory_name} 電子ホワイトボード</h1>"
    f"<div style='color:#666;margin-bottom:6px'>"
    f"基準日: {base_date.strftime('%Y-%m-%d (')}{WEEKDAY_JA[base_date.weekday()]}"
    f")</div>",
    unsafe_allow_html=True,
)


def _kpi_card(label, value, sub=""):
    return (
        "<div style='border:1px solid #e0e0e0;border-radius:6px;"
        "padding:4px 8px;background:#fff;line-height:1.2'>"
        f"<div style='color:#666'>{label}</div>"
        f"<div style='font-size:22px;font-weight:bold'>{value}</div>"
        f"<div style='color:#888'>{sub}</div></div>"
    )


unique_drivers_today = len({c["person"] for c in cards_today if c["person"]})
unique_trucks_today = len({c["truck"] for c in cards_today if c["truck"]})
partners_today = len({c.get("partner") or "自社" for c in cards_today})
holidays_today = [h for h in holidays_month if h["day"] == base_date.day]
events_today = [e for e in all_events_month
                if e["day"] <= base_date.day < e["day"] + e["span_days"]]



# ---------------------------------------------------------------------------
# 月間予定 (28日ローリング: 2週間 + 2週間)
# ---------------------------------------------------------------------------


def card_text(c):
    """2-line magnet label: line 1 = 行先 / 車番, line 2 = 氏名 / 時間 / 協力会社."""
    line1 = " / ".join(
        p for p in [c.get("destination"), c.get("truck")] if p
    )
    line2_parts = [c.get("person"), c.get("time")]
    if c.get("partner"):
        line2_parts.append(f"({c['partner']})")
    line2 = " ".join(p for p in line2_parts if p)
    if line1 and line2:
        return f"{line1}\n{line2}"
    return line1 or line2 or ""


main_l, main_r = st.columns([9, 3], gap="medium")

with main_l:
    st.subheader("📅 月間予定表")
    st.caption(
        f"基準日 {base_date.month}/{base_date.day} から 28日ローリング "
        "(2週間 + 2週間)。サイドバーから駒台に追加 → 駒台からドラッグで配置。"
        "配置済みの札は日付間ドラッグで移動できます。"
    )

    # Build per-day entries with month key + show_month flag
    prev_mk = None
    days_payload = []
    for d in window_days:
        mk_d = _mk(d)
        show_month = (d.day == 1) or (mk_d != prev_mk)
        days_payload.append({
            "iso": d.isoformat(),
            "year": d.year,
            "month": d.month,
            "day": d.day,
            "month_key": mk_d,
            "weekday": d.weekday(),
            "show_month": show_month,
        })
        prev_mk = mk_d

    # Cards / events placed on calendar (within window)
    window_card_ids = set()
    cards_payload = []
    events_payload = []
    for d in window_days:
        mk_d = _mk(d)
        for c in window_cards_by_mk.get(mk_d, []):
            if c["day"] == d.day and c["id"] not in window_card_ids:
                window_card_ids.add(c["id"])
                cards_payload.append({
                    "id": c["id"], "day": c["day"], "month_key": mk_d,
                    "text": card_text(c) or "(空札)",
                    "color": c["color"],
                })

    added_events = set()
    for mk_d, evs in window_events_by_mk.items():
        for e in evs:
            key = (mk_d, e["id"])
            if key in added_events:
                continue
            added_events.add(key)
            events_payload.append({
                "id": e["id"], "day": e["day"], "month_key": mk_d,
                "title": e["title"], "color": e["color"],
                "span_days": e["span_days"], "note": e["note"],
            })

    # Stock (駒台) items
    stock_cards = db.get_stock_cards()
    stock_events = db.get_stock_events()
    stock_cards_payload = [
        {"id": c["id"], "type": "card",
         "text": card_text(c) or "(空札)",
         "color": c["color"],
         "x": c.get("stock_x") or 0,
         "y": c.get("stock_y") or 0}
        for c in stock_cards
    ]
    stock_events_payload = [
        {"id": e["id"], "type": "event",
         "text": e["title"],
         "color": e["color"],
         "span_days": e["span_days"],
         "note": e["note"],
         "x": e.get("stock_x") or 0,
         "y": e.get("stock_y") or 0}
        for e in stock_events
    ]

    cb_data = {
        "days": days_payload,
        "weekday_names": WEEKDAY_JA,
        "colors": db.COLORS,
        "event_colors": db.EVENT_COLORS,
        "cards": cards_payload,
        "events": events_payload,
        "stock_cards": stock_cards_payload,
        "stock_events": stock_events_payload,
        "today_iso": date.today().isoformat(),
    }
    cb = register_calendar_board()
    layout_result = cb(
        key=f"cal_{base_date.isoformat()}_{ss.rev}",
        data=cb_data,
        height="content",
        on_layout_change=lambda: None,
    )
    layout = layout_result.get("layout") if layout_result else None
    if layout:
        original = {}
        for c in stock_cards:
            original[("card", c["id"])] = (
                "STOCK", 0, 1,
                float(c.get("stock_x") or 0), float(c.get("stock_y") or 0),
            )
        for e in stock_events:
            original[("event", e["id"])] = (
                "STOCK", 0, 1,
                float(e.get("stock_x") or 0), float(e.get("stock_y") or 0),
            )
        for _mk_c, lst in window_cards_by_mk.items():
            for c in lst:
                original[("card", c["id"])] = (_mk_c, c["day"], 0, 0.0, 0.0)
        for _mk_e, evs in window_events_by_mk.items():
            for e in evs:
                original[("event", e["id"])] = (_mk_e, e["day"], 0, 0.0, 0.0)

        for it in layout:
            try:
                cid = int(it["id"])
            except (TypeError, ValueError):
                continue
            typ = it.get("type", "card")
            new_mk = it.get("month_key") or "STOCK"
            new_day = int(it.get("day") or 0)
            new_order = int(it.get("order") or 0)
            new_stock = int(it.get("is_stock") or 0)
            new_x = float(it.get("stock_x") or 0)
            new_y = float(it.get("stock_y") or 0)
            cur = original.get((typ, cid))
            if cur is None:
                continue
            cur_mk, cur_day, cur_stock, cur_x, cur_y = cur
            placement_same = (cur_mk, cur_day, cur_stock) == (
                new_mk, new_day, new_stock
            )
            pos_same = abs(cur_x - new_x) < 1 and abs(cur_y - new_y) < 1
            if placement_same and (not new_stock or pos_same):
                continue
            if typ == "card":
                if new_stock:
                    db.unplace_card(cid, new_x, new_y)
                else:
                    db.place_card(cid, new_mk, new_day, new_order)
            elif typ == "event":
                if new_stock:
                    db.unplace_event(cid, new_x, new_y)
                else:
                    db.place_event(cid, new_mk, new_day)

with main_r:
    # Clock + Weather (compact)
    hcol1, hcol2 = st.columns([2, 1])
    with hcol1:
        register_clock()(key=f"clock_{ss.rev}", data={}, height=90)
    with hcol2:
        st.markdown(
            f"<div style='border:1px solid #ddd;border-radius:6px;"
            f"padding:4px 8px;background:#fafcff;text-align:center'>"
            f"<div style='font-size:30px;line-height:1'>{weather.split()[0]}</div>"
            f"<div style='color:#555'>"
            f"{' '.join(weather.split()[1:])} / {temp}°C</div></div>",
            unsafe_allow_html=True,
        )

    # KPI 2列 × 3段 (narrow column friendly)
    kpi_pairs = [
        [
            _kpi_card("当日 便数", len(cards_today),
                      f"翌日 {len(cards_tomorrow)} 便"),
            _kpi_card("稼働ドライバ", unique_drivers_today,
                      f"マスタ {len(db.tag_labels('person'))} 名"),
        ],
        [
            _kpi_card("稼働車両", unique_trucks_today,
                      f"マスタ {len(db.tag_labels('truck'))} 台"),
            _kpi_card("協力会社", partners_today,
                      " / ".join(db.tag_labels('partner')[:2]) or "—"),
        ],
        [
            _kpi_card("公休 (本日)", len(holidays_today),
                      f"月計 {len(holidays_month)} 名"),
            _kpi_card("イベント (本日)", len(events_today),
                      f"月計 {len(all_events_month)} 件"),
        ],
    ]
    for row in kpi_pairs:
        cols = st.columns(2)
        for col, html in zip(cols, row):
            col.markdown(html, unsafe_allow_html=True)

    # お知らせ
    st.markdown(
        "<div style='font-weight:600;margin:6px 0 2px'>📣 お知らせ</div>",
        unsafe_allow_html=True,
    )
    if not announcements:
        st.markdown(
            "<div style='color:#888'>未登録</div>",
            unsafe_allow_html=True,
        )
    for a in announcements[:3]:
        bg = {"info": "#eef5fb", "warn": "#fff8e1",
              "alert": "#ffebee"}.get(a["level"], "#fafafa")
        border = {"info": "#1976d2", "warn": "#f9a825",
                  "alert": "#c62828"}.get(a["level"], "#999")
        pin = "📌 " if a["pinned"] else ""
        cc = st.columns([10, 1])
        cc[0].markdown(
            f"<div style='background:{bg};border-left:3px solid {border};"
            f"padding:4px 8px;margin:2px 0;border-radius:0 4px 4px 0;"
            f"font-weight:500'>{pin}{a['text']}</div>",
            unsafe_allow_html=True,
        )
        if cc[1].button("✖", key=f"del_ann_{a['id']}",
                        use_container_width=True):
            db.delete_announcement(a["id"])
            ss.rev += 1
            st.rerun()

    # 安全訓 + 共有URL
    safety_col, share_col = st.columns([3, 2])
    with safety_col:
        st.markdown(
            "<div style='font-weight:600;margin:6px 0 2px'>🦺 安全訓</div>"
            "<ol style='padding-left:18px;margin:0;line-height:1.45'>"
            + "".join(f"<li>{r}</li>" for r in SAFETY_RULES)
            + "</ol>",
            unsafe_allow_html=True,
        )
    with share_col:
        st.markdown(
            "<div style='font-weight:600;margin:6px 0 2px'>🔗 共有URL</div>"
            "<div style='color:#888;font-size:12px'>スマホで当日ビューを表示</div>",
            unsafe_allow_html=True,
        )
        try:
            host_full = "https://" + st.context.headers.get("host", "localhost")
        except Exception:
            host_full = "https://localhost"
        full_url = f"{host_full}/?view=day&date={base_date.isoformat()}"
        qr = qrcode.QRCode(box_size=2, border=1)
        qr.add_data(full_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        st.image(buf.getvalue(), width=90)

    # 協力会社別 (当日)
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
            f"<span style='color:#666;'>{len(items)} 便</span>",
            unsafe_allow_html=True,
        )
        if not items:
            st.markdown(
                "<div style='color:#999;margin-bottom:6px'>—</div>",
                unsafe_allow_html=True,
            )
            continue
        body = "".join(
            f"<div style='background:{db.COLORS.get(c['color'], '#eee')};"
            f"border:1px solid #aaa;border-radius:4px;padding:4px 8px;"
            f"margin:2px 0;'>"
            f"{(c.get('time','') + ' ') if c.get('time') else ''}"
            f"{c.get('destination','')} / {c.get('truck','')} / "
            f"{c.get('person','')}</div>"
            for c in items
        )
        st.markdown(body, unsafe_allow_html=True)

    # 公休者ボード
    st.subheader("🛌 公休者ボード")
    if not holidays_month:
        st.caption("今月の公休登録はありません。"
                   " サイドバー「🛌 公休者管理」から登録できます。")
    day_shift = [h for h in holidays_month if h["shift"] == "day"]
    night_shift = [h for h in holidays_month if h["shift"] == "night"]
    st.markdown(f"**日勤公休** ({len(day_shift)}名)")
    for h in day_shift:
        st.markdown(
            f"<div style='border-left:4px solid #2196f3;padding:3px 8px;"
            f"margin:2px 0;background:#f0f8ff'>"
            f"{h['day']}日 {h['person']}"
            f"{(' / ' + h['note']) if h['note'] else ''}</div>",
            unsafe_allow_html=True,
        )
    st.markdown(f"**夜勤公休** ({len(night_shift)}名)")
    for h in night_shift:
        st.markdown(
            f"<div style='border-left:4px solid #7e57c2;padding:3px 8px;"
            f"margin:2px 0;background:#f6f3fa'>"
            f"{h['day']}日 {h['person']}"
            f"{(' / ' + h['note']) if h['note'] else ''}</div>",
            unsafe_allow_html=True,
        )

st.markdown("---")


# ---------------------------------------------------------------------------
# 出勤表 (左) + 手書きノート (右) を左右に並べる
# ---------------------------------------------------------------------------

att_col, note_col = st.columns([1, 1], gap="medium")

with att_col:
    st.subheader("🗓 出勤表 (月間ヒートマップ)")
    persons = db.tag_labels("person")
    hol_set = {(h["day"], h["person"]) for h in holidays_month}
    work_set = set()
    for c in all_cards_month:
        if c.get("person"):
            work_set.add((c["day"], c["person"]))
    if not persons:
        st.caption("マスタに氏名がありません。"
                   " サイドバー「📦 マスタ管理」から登録してください。")
    else:
        header_row = (
            "<tr><th style='background:#f4f4f4'></th>"
            + "".join(
                f"<th style='background:#f4f4f4;'>{d}</th>"
                for d in range(1, ndays + 1)
            )
            + "</tr>"
        )
        body = ""
        for p in persons:
            cells = ""
            for d in range(1, ndays + 1):
                cls = "background:#fff"
                txt = ""
                if (d, p) in hol_set:
                    cls = "background:#ffe0e0"; txt = "休"
                elif (d, p) in work_set:
                    cls = "background:#c8e6c9"; txt = "○"
                cells += (
                    f"<td style='border:1px solid #ddd;width:24px;height:26px;"
                    f"text-align:center;{cls}'>{txt}</td>"
                )
            body += (
                f"<tr><th style='text-align:left;"
                f"padding-right:4px;white-space:nowrap'>{p}</th>{cells}</tr>"
            )
        st.markdown(
            f"<div style='overflow-x:auto'>"
            f"<table style='border-collapse:collapse'>"
            f"{header_row}{body}</table></div>"
            f"<div style='color:#666;margin-top:4px'>"
            f"○=便あり / 休=公休 / 空=未登録</div>",
            unsafe_allow_html=True,
        )

with note_col:
    with st.expander("📓 手書きノート (図面・地図への注釈用、PDF/画像背景対応)",
                     expanded=False):
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

        nav = st.columns([1, 1, 4, 1, 1])
        if nav[0].button("◀", key="nb_prev", disabled=(page_no <= 1),
                         use_container_width=True):
            ss.note_page_no = page_no - 1
            st.rerun()
        nav[1].markdown(
            f"<div style='text-align:center;font-weight:bold;padding-top:6px'>"
            f"P {page_no} / {total_pages}</div>",
            unsafe_allow_html=True,
        )
        if nav[2].button("📃 + 新規ページ", use_container_width=True, key="nb_add"):
            new_p = db.add_page(note_board_key, after_page_no=page_no)
            ss.note_page_no = new_p["page_no"]
            ss.rev += 1
            st.rerun()
        if nav[3].button("✖ 削除", key="nb_del", use_container_width=True,
                         disabled=(total_pages <= 1)):
            db.delete_page(page["id"])
            ss.note_page_no = max(1, page_no - 1)
            ss.rev += 1
            st.rerun()
        if nav[4].button("▶", key="nb_next", disabled=(page_no >= total_pages),
                         use_container_width=True):
            ss.note_page_no = page_no + 1
            st.rerun()

        bg_b64 = None
        if page.get("bg_data") and page.get("bg_type") != "blank":
            bg_b64 = base64.b64encode(page["bg_data"]).decode("ascii")

        with st.expander("🖼 背景 (画像 / PDF)", expanded=False):
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


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    "<div style='color:#888;padding-top:8px;text-align:center'>"
    "工場ホワイトボード ショーケース — "
    f"DB rev {ss.rev} / 最終アクセス {datetime.now().strftime('%H:%M:%S')}"
    "</div>",
    unsafe_allow_html=True,
)
