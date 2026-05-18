"""Mobile day viewer — read-only single-day view reached via ?view=day.

Same app.py / same deployment as the dashboard: the dashboard's 📱 button and
the share QR both route here by setting the ``view`` query parameter. Shows
only the selected day's delivery plan, holidays, notices and safety rules,
optionally translated for non-Japanese-speaking workers.
"""

from datetime import date

import streamlit as st

import db
import translate
from constants import SAFETY_RULES, WEEKDAY_JA

_CSS = """
<style>
.mv-h1 { font-size: 22px; font-weight: bold; margin: 0; }
.mv-sub { color: #666; font-size: 14px; margin-bottom: 8px; }
.mv-weather { font-size: 15px; color: #444; }
.mv-sec { font-size: 17px; font-weight: bold; margin: 14px 0 6px; }
.mv-card {
    border: 1px solid #999; border-radius: 6px;
    padding: 8px 10px; margin: 5px 0; font-size: 15px; line-height: 1.4;
}
.mv-card .t { font-weight: bold; }
.mv-hol {
    border-left: 4px solid #2196f3; background: #f0f8ff;
    padding: 5px 10px; margin: 4px 0; font-size: 14px;
}
.mv-ann {
    padding: 8px 12px; margin: 5px 0; border-radius: 0 6px 6px 0;
    font-size: 15px; line-height: 1.45;
}
.mv-empty { color: #999; font-size: 14px; }
</style>
"""

_ANN_BG = {"info": "#eef5fb", "warn": "#fff8e1", "alert": "#ffebee"}
_ANN_BORDER = {"info": "#1976d2", "warn": "#f9a825", "alert": "#c62828"}


def _parse_date(raw):
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def render(query_params):
    """Render the read-only mobile day view. Caller must st.stop() afterwards."""
    st.markdown(_CSS, unsafe_allow_html=True)

    if st.button("🖥 PC表示に戻る", use_container_width=True):
        try:
            del st.query_params["view"]
        except KeyError:
            pass
        st.rerun()

    d = _parse_date(query_params.get("date"))
    month_key = f"{d.year:04d}-{d.month:02d}"

    # --- language selector --------------------------------------------------
    lang_codes = ["ja"] + translate.enabled_langs()
    labels = {"ja": "日本語", **translate.LANGUAGES}
    cur = query_params.get("lang", "ja")
    if cur not in lang_codes:
        cur = "ja"
    chosen = st.selectbox(
        "言語 / Language", lang_codes, index=lang_codes.index(cur),
        format_func=lambda c: labels.get(c, c),
    )
    if chosen != cur:
        st.query_params["lang"] = chosen
        st.rerun()
    lang = chosen

    # --- header -------------------------------------------------------------
    factory_name = db.get_state("factory_name", "第3工場")
    weather = db.get_state("weather", "")
    temp = db.get_state("temperature", "")
    st.markdown(
        f"<div class='mv-h1'>{factory_name} 当日便</div>"
        f"<div class='mv-sub'>{d.isoformat()} "
        f"({WEEKDAY_JA[d.weekday()]})</div>"
        + (
            f"<div class='mv-weather'>{weather} / {temp}°C</div>"
            if weather else ""
        ),
        unsafe_allow_html=True,
    )

    # --- delivery runs ------------------------------------------------------
    st.markdown("<div class='mv-sec'>🚚 当日の便</div>", unsafe_allow_html=True)
    cards = db.get_cards_by_day(month_key, d.day)
    if not cards:
        st.markdown(
            "<div class='mv-empty'>登録された便はありません</div>",
            unsafe_allow_html=True,
        )
    for c in cards:
        bg = db.COLORS.get(c["color"], "#eeeeee")
        time_txt = f"{c['time']} " if c.get("time") else ""
        partner = c.get("partner") or "自社"
        st.markdown(
            f"<div class='mv-card' style='background:{bg}'>"
            f"<span class='t'>{time_txt}{c.get('destination','')}</span><br>"
            f"{c.get('truck','')} / {c.get('person','')} "
            f"<span style='color:#555'>({partner})</span></div>",
            unsafe_allow_html=True,
        )

    # --- holidays -----------------------------------------------------------
    holidays = [h for h in db.list_holidays(month_key) if h["day"] == d.day]
    if holidays:
        st.markdown(
            "<div class='mv-sec'>🛌 本日の公休</div>", unsafe_allow_html=True
        )
        for h in holidays:
            note = f" / {h['note']}" if h["note"] else ""
            st.markdown(
                f"<div class='mv-hol'>{h['person']}{note}</div>",
                unsafe_allow_html=True,
            )

    # --- announcements ------------------------------------------------------
    announcements = db.list_announcements(limit=10)
    if announcements:
        st.markdown(
            "<div class='mv-sec'>📣 お知らせ</div>", unsafe_allow_html=True
        )
        texts = translate.translate_batch(
            [a["text"] for a in announcements], lang
        )
        for a, text in zip(announcements, texts):
            bg = _ANN_BG.get(a["level"], "#fafafa")
            border = _ANN_BORDER.get(a["level"], "#999")
            pin = "📌 " if a["pinned"] else ""
            st.markdown(
                f"<div class='mv-ann' style='background:{bg};"
                f"border-left:4px solid {border}'>{pin}{text}</div>",
                unsafe_allow_html=True,
            )

    # --- safety rules -------------------------------------------------------
    st.markdown("<div class='mv-sec'>🦺 安全訓</div>", unsafe_allow_html=True)
    rules = translate.translate_batch(SAFETY_RULES, lang)
    st.markdown(
        "<ol style='padding-left:20px;line-height:1.7;font-size:15px'>"
        + "".join(f"<li>{r}</li>" for r in rules)
        + "</ol>",
        unsafe_allow_html=True,
    )
