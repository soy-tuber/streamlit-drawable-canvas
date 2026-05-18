"""Factory whiteboard prototype.

A digital version of the factory monthly-schedule whiteboard:
- Edit mode  : drag magnet-style cards between days (for the touchscreen board).
- View mode  : read-only calendar, auto-refreshing (for phones / iPads).
Both modes share one SQLite file, so edits propagate between devices.
"""

import calendar

import streamlit as st

import db

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]
COLOR_LABELS = {"yellow": "黄", "blue": "青", "orange": "橙", "white": "白"}

st.set_page_config(page_title="工場ホワイトボード", layout="wide")
db.init_db()

if "rev" not in st.session_state:
    st.session_state.rev = 0


def card_text(card):
    parts = [card["destination"], card["truck"], card["person"], card["time"]]
    return " ".join(p for p in parts if p)


def card_label(card):
    """Unique, human-readable label used by the drag widget and edit picker."""
    return f"[{COLOR_LABELS.get(card['color'], '?')}] {card_text(card) or '(空札)'} ⟨{card['id']}⟩"


def render_view(year, mon, month_key):
    cards = db.get_cards(month_key)
    by_day = {}
    for card in cards:
        by_day.setdefault(card["day"], []).append(card)

    ndays = calendar.monthrange(year, mon)[1]
    first_wd = calendar.weekday(year, mon, 1)  # 0 = Monday

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


def render_edit(year, mon, month_key):
    try:
        from streamlit_sortables import sort_items
    except ImportError:
        st.error("streamlit-sortables が未インストールです: pip install -r requirements.txt")
        return

    ndays = calendar.monthrange(year, mon)[1]
    cards = db.get_cards(month_key)

    by_day = {d: [] for d in range(1, ndays + 1)}
    for card in cards:
        by_day.get(card["day"], []).append(card)

    label_to_id = {}
    containers = []
    for day in range(1, ndays + 1):
        wd = calendar.weekday(year, mon, day)
        items = []
        for card in by_day[day]:
            lbl = card_label(card)
            label_to_id[lbl] = card["id"]
            items.append(lbl)
        containers.append({"header": f"{day}日 ({WEEKDAY_JA[wd]})", "items": items})

    st.caption("札をドラッグして日付の間を移動できます。")
    result = sort_items(
        containers,
        multi_containers=True,
        direction="vertical",
        key=f"sort_{month_key}_{st.session_state.rev}",
    )

    current = {c["id"]: (c["day"], c["sort_order"]) for c in cards}
    changes = []
    for idx, container in enumerate(result):
        day = idx + 1
        items = container["items"] if isinstance(container, dict) else container
        for order, lbl in enumerate(items):
            card_id = label_to_id.get(lbl)
            if card_id is None:
                continue
            if current.get(card_id) != (day, order):
                changes.append((card_id, day, order))
    if changes:
        db.set_positions(changes)
        st.session_state.rev += 1
        st.rerun()

    with st.expander("札を編集・削除"):
        if not cards:
            st.info("札がありません。サイドバーの「札を追加」から登録してください。")
            return
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


# --- Sidebar -----------------------------------------------------------------
st.sidebar.title("工場ホワイトボード")
mode = st.sidebar.radio("モード", ["閲覧", "編集"], horizontal=True)
year = st.sidebar.selectbox("年", list(range(2024, 2031)), index=2)
mon = st.sidebar.selectbox("月", list(range(1, 13)), index=4)
month_key = f"{year:04d}-{mon:02d}"
ndays = calendar.monthrange(year, mon)[1]

if mode == "編集":
    with st.sidebar.form("add_card", clear_on_submit=True):
        st.subheader("札を追加")
        a_dest = st.text_input("行先")
        a_truck = st.text_input("車番")
        a_person = st.text_input("氏名")
        a_time = st.text_input("出庫時間")
        a_color = st.selectbox(
            "色", list(COLOR_LABELS), format_func=lambda k: COLOR_LABELS[k]
        )
        a_day = st.selectbox("日", list(range(1, ndays + 1)))
        if st.form_submit_button("追加", use_container_width=True):
            db.add_card(month_key, a_day, a_dest, a_truck, a_person, a_time, a_color)
            st.session_state.rev += 1
            st.rerun()

# --- Main --------------------------------------------------------------------
st.header(f"第3工場 月予定表 — {year}年{mon}月")

if mode == "閲覧":
    st.caption("閲覧モード:3秒ごとに自動更新されます。")
    auto_view = st.fragment(run_every="3s")(render_view)
    auto_view(year, mon, month_key)
else:
    render_edit(year, mon, month_key)
