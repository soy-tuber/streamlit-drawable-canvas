"""SQLite-backed shared store for the factory whiteboard prototype."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "whiteboard.db"

# Magnet-label colors, mirroring the yellow / blue / orange tags on the real board.
COLORS = {
    "yellow": "#ffe680",
    "blue": "#7fb3ff",
    "orange": "#ffb066",
    "white": "#ffffff",
}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


TAG_KINDS = ("destination", "truck", "person", "partner")

SEED_TAGS = {
    "destination": ["大田区古着", "横浜古着", "目黒区", "厚木PET", "愛川PET",
                    "ふじみ衛生", "メグミルクタカナシ", "工場戻り"],
    "truck": ["9号車", "11号車", "15号車", "16号車", "24号車", "25号車",
              "26号車", "28号車", "29号車"],
    "person": ["渡部", "佐藤", "鈴木", "高橋", "田中", "伊藤", "山本"],
    "partner": ["自社", "平島運輸", "光陽物流"],
}


def init_db():
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                month       TEXT    NOT NULL,
                day         INTEGER NOT NULL,
                destination TEXT    DEFAULT '',
                truck       TEXT    DEFAULT '',
                person      TEXT    DEFAULT '',
                time        TEXT    DEFAULT '',
                color       TEXT    DEFAULT 'yellow',
                sort_order  INTEGER DEFAULT 0,
                updated_at  TEXT
            )
            """
        )
        # Lightweight in-place migration: add partner column if missing.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)").fetchall()}
        if "partner" not in cols:
            conn.execute("ALTER TABLE cards ADD COLUMN partner TEXT DEFAULT '自社'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tag_masters (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT    NOT NULL,
                label      TEXT    NOT NULL,
                color      TEXT    DEFAULT 'white',
                sort_order INTEGER DEFAULT 0,
                UNIQUE(kind, label)
            )
            """
        )
        existing = conn.execute("SELECT COUNT(*) FROM tag_masters").fetchone()[0]
        if existing == 0:
            order = 0
            for kind, labels in SEED_TAGS.items():
                for label in labels:
                    conn.execute(
                        "INSERT OR IGNORE INTO tag_masters (kind, label, color, sort_order) "
                        "VALUES (?,?,?,?)",
                        (kind, label, "yellow" if kind == "destination" else "white", order),
                    )
                    order += 1
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memos (
                month      TEXT PRIMARY KEY,
                json_data  TEXT,
                image      BLOB,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                board_key    TEXT    NOT NULL,
                page_no      INTEGER NOT NULL,
                strokes_json TEXT    DEFAULT '[]',
                image_png    BLOB,
                bg_type      TEXT    DEFAULT 'blank',
                bg_data      BLOB,
                bg_meta      TEXT    DEFAULT '{}',
                updated_at   TEXT,
                UNIQUE(board_key, page_no)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pages_board ON pages(board_key, page_no)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS holidays (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                month   TEXT    NOT NULL,
                day     INTEGER NOT NULL,
                person  TEXT    NOT NULL,
                shift   TEXT    DEFAULT 'day',
                note    TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT    NOT NULL,
                level      TEXT    DEFAULT 'info',
                pinned     INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                month     TEXT    NOT NULL,
                day       INTEGER NOT NULL,
                span_days INTEGER DEFAULT 1,
                title     TEXT    NOT NULL,
                color     TEXT    DEFAULT 'red',
                note      TEXT    DEFAULT '',
                created_at TEXT
            )
            """
        )


# --- cards -------------------------------------------------------------------


def get_cards(month):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cards WHERE month=? ORDER BY day, sort_order, id",
            (month,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_card(month, day, destination, truck, person, time, color, partner="自社"):
    with _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE month=? AND day=?", (month, day)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO cards "
            "(month, day, destination, truck, person, time, color, sort_order, partner, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                month,
                day,
                destination,
                truck,
                person,
                time,
                color,
                n,
                partner,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def get_cards_by_day(month, day):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cards WHERE month=? AND day=? ORDER BY sort_order, id",
            (month, day),
        ).fetchall()
    return [dict(r) for r in rows]


def _safe_str(v):
    """Coerce a value (possibly None / NaN / non-str) to a clean string."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and v != v:  # NaN
            return ""
    except Exception:
        pass
    s = str(v)
    return "" if s.lower() in ("nan", "none") else s


def replace_cards_for_day(month, day, rows):
    """Atomically replace all cards for (month, day) with the supplied list.

    Each row may contain: destination, truck, person, time, color, partner.
    """
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("DELETE FROM cards WHERE month=? AND day=?", (month, day))
        for i, r in enumerate(rows):
            dest = _safe_str(r.get("destination")).strip()
            truck = _safe_str(r.get("truck")).strip()
            person = _safe_str(r.get("person")).strip()
            time_v = _safe_str(r.get("time")).strip()
            partner = _safe_str(r.get("partner")).strip() or "自社"
            color = _safe_str(r.get("color")) or "yellow"
            # Drop fully empty rows
            if not any([dest, truck, person, time_v]):
                continue
            conn.execute(
                "INSERT INTO cards "
                "(month, day, destination, truck, person, time, color, sort_order, partner, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    month,
                    day,
                    dest,
                    truck,
                    person,
                    time_v,
                    color,
                    i,
                    partner,
                    ts,
                ),
            )


def update_card(card_id, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
    assignments = ", ".join(f"{k}=?" for k in fields)
    with _conn() as conn:
        conn.execute(
            f"UPDATE cards SET {assignments} WHERE id=?",
            (*fields.values(), card_id),
        )


def delete_card(card_id):
    with _conn() as conn:
        conn.execute("DELETE FROM cards WHERE id=?", (card_id,))


def set_positions(positions):
    """positions: iterable of (card_id, day, sort_order)."""
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        for card_id, day, order in positions:
            conn.execute(
                "UPDATE cards SET day=?, sort_order=?, updated_at=? WHERE id=?",
                (day, order, ts, card_id),
            )


# --- legacy single-memo (kept for backward compatibility) --------------------


def get_memo(month):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM memos WHERE month=?", (month,)).fetchone()
    return dict(row) if row else None


def save_memo(month, json_data, image):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO memos (month, json_data, image, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(month) DO UPDATE SET "
            "json_data=excluded.json_data, image=excluded.image, updated_at=excluded.updated_at",
            (month, json_data, image, datetime.now().isoformat(timespec="seconds")),
        )


# --- multi-page handwriting notes -------------------------------------------


def list_pages(board_key):
    """Return [{id, page_no, bg_type, updated_at, has_image}] for the given board."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, page_no, bg_type, updated_at, "
            "(image_png IS NOT NULL) AS has_image "
            "FROM pages WHERE board_key=? ORDER BY page_no",
            (board_key,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_page(board_key, page_no):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM pages WHERE board_key=? AND page_no=?",
            (board_key, page_no),
        ).fetchone()
    return dict(row) if row else None


def get_page_by_id(page_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    return dict(row) if row else None


def ensure_page(board_key, page_no):
    """Create the page if missing; return its row dict."""
    page = get_page(board_key, page_no)
    if page:
        return page
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO pages (board_key, page_no, strokes_json, bg_type, bg_meta, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (board_key, page_no, "[]", "blank", "{}", ts),
        )
    return get_page(board_key, page_no)


def save_strokes(page_id, strokes_json, image_png):
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute(
            "UPDATE pages SET strokes_json=?, image_png=?, updated_at=? WHERE id=?",
            (strokes_json, image_png, ts, page_id),
        )


def set_background(page_id, bg_type, bg_data, bg_meta):
    if isinstance(bg_meta, dict):
        bg_meta = json.dumps(bg_meta)
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute(
            "UPDATE pages SET bg_type=?, bg_data=?, bg_meta=?, updated_at=? WHERE id=?",
            (bg_type, bg_data, bg_meta, ts, page_id),
        )


def clear_background(page_id):
    set_background(page_id, "blank", None, "{}")


def delete_page(page_id):
    """Delete the page and renumber the rest of the board contiguously."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT board_key, page_no FROM pages WHERE id=?", (page_id,)
        ).fetchone()
        if not row:
            return
        board_key, page_no = row["board_key"], row["page_no"]
        conn.execute("DELETE FROM pages WHERE id=?", (page_id,))
        conn.execute(
            "UPDATE pages SET page_no=page_no-1 WHERE board_key=? AND page_no>?",
            (board_key, page_no),
        )


def add_page(board_key, after_page_no=None):
    """Append a new blank page (or insert after the given index). Returns page row."""
    with _conn() as conn:
        existing = conn.execute(
            "SELECT MAX(page_no) FROM pages WHERE board_key=?", (board_key,)
        ).fetchone()[0]
        if existing is None:
            new_no = 1
        elif after_page_no is None or after_page_no >= existing:
            new_no = existing + 1
        else:
            conn.execute(
                "UPDATE pages SET page_no=page_no+1 "
                "WHERE board_key=? AND page_no>? ",
                (board_key, after_page_no),
            )
            new_no = after_page_no + 1
        ts = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO pages (board_key, page_no, strokes_json, bg_type, bg_meta, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (board_key, new_no, "[]", "blank", "{}", ts),
        )
    return get_page(board_key, new_no)


def count_pages(board_key):
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM pages WHERE board_key=?", (board_key,)
        ).fetchone()[0]


def get_all_pages_full(board_key):
    """Return every page (full row including blobs) for export."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pages WHERE board_key=? ORDER BY page_no",
            (board_key,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- tag masters ------------------------------------------------------------


def list_tags(kind=None):
    sql = "SELECT * FROM tag_masters"
    params = ()
    if kind:
        sql += " WHERE kind=?"
        params = (kind,)
    sql += " ORDER BY kind, sort_order, label"
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def tag_labels(kind):
    return [t["label"] for t in list_tags(kind)]


def upsert_tag(kind, label, color="white", sort_order=None):
    label = (label or "").strip()
    if not label or kind not in TAG_KINDS:
        return
    with _conn() as conn:
        if sort_order is None:
            sort_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order)+1, 0) FROM tag_masters WHERE kind=?",
                (kind,),
            ).fetchone()[0]
        conn.execute(
            "INSERT INTO tag_masters (kind, label, color, sort_order) VALUES (?,?,?,?) "
            "ON CONFLICT(kind, label) DO UPDATE SET color=excluded.color, "
            "sort_order=excluded.sort_order",
            (kind, label, color, sort_order),
        )


def delete_tag(tag_id):
    with _conn() as conn:
        conn.execute("DELETE FROM tag_masters WHERE id=?", (tag_id,))


def replace_tags(kind, rows):
    """Atomically replace all tag_masters rows for a kind."""
    with _conn() as conn:
        conn.execute("DELETE FROM tag_masters WHERE kind=?", (kind,))
        for i, r in enumerate(rows):
            label = _safe_str(r.get("label")).strip()
            if not label:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO tag_masters (kind, label, color, sort_order) "
                "VALUES (?,?,?,?)",
                (kind, label, _safe_str(r.get("color")) or "white", i),
            )


# --- holidays / announcements / state --------------------------------------


def list_holidays(month):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays WHERE month=? ORDER BY day, shift, id", (month,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_holiday(month, day, person, shift="day", note=""):
    person = _safe_str(person).strip()
    if not person:
        return
    try:
        day = int(day)
    except (TypeError, ValueError):
        day = 1
    with _conn() as conn:
        conn.execute(
            "INSERT INTO holidays (month, day, person, shift, note) VALUES (?,?,?,?,?)",
            (month, day, person, _safe_str(shift) or "day", _safe_str(note).strip()),
        )


def delete_holiday(holiday_id):
    with _conn() as conn:
        conn.execute("DELETE FROM holidays WHERE id=?", (holiday_id,))


def replace_holidays(month, rows):
    with _conn() as conn:
        conn.execute("DELETE FROM holidays WHERE month=?", (month,))
        for r in rows:
            person = _safe_str(r.get("person")).strip()
            if not person:
                continue
            try:
                day_val = int(r.get("day") or 1)
            except (TypeError, ValueError):
                day_val = 1
            conn.execute(
                "INSERT INTO holidays (month, day, person, shift, note) VALUES (?,?,?,?,?)",
                (
                    month,
                    day_val,
                    person,
                    _safe_str(r.get("shift")) or "day",
                    _safe_str(r.get("note")).strip(),
                ),
            )


def list_announcements(limit=20):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM announcements ORDER BY pinned DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_announcement(text, level="info", pinned=False):
    text = (text or "").strip()
    if not text:
        return
    with _conn() as conn:
        conn.execute(
            "INSERT INTO announcements (text, level, pinned, created_at) VALUES (?,?,?,?)",
            (text, level, 1 if pinned else 0, datetime.now().isoformat(timespec="seconds")),
        )


def delete_announcement(ann_id):
    with _conn() as conn:
        conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))


# --- events ----------------------------------------------------------------


EVENT_COLORS = {
    "red":    "#ff4d4d",
    "orange": "#ff9900",
    "blue":   "#1976d2",
    "green":  "#43a047",
    "gray":   "#808080",
}


def list_events(month):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE month=? ORDER BY day, id", (month,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_event(month, day, title, color="red", span_days=1, note=""):
    title = _safe_str(title).strip()
    if not title:
        return
    try:
        day = int(day)
    except (TypeError, ValueError):
        day = 1
    try:
        span_days = max(1, int(span_days))
    except (TypeError, ValueError):
        span_days = 1
    with _conn() as conn:
        conn.execute(
            "INSERT INTO events (month, day, span_days, title, color, note, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                month, day, span_days, title,
                _safe_str(color) or "red",
                _safe_str(note).strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def delete_event(event_id):
    with _conn() as conn:
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))


# --- dashboard state -------------------------------------------------------


def get_state(key, default=None):
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM dashboard_state WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_state(key, value):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO dashboard_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
