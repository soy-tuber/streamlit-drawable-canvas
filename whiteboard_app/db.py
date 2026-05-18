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


# --- cards -------------------------------------------------------------------


def get_cards(month):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cards WHERE month=? ORDER BY day, sort_order, id",
            (month,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_card(month, day, destination, truck, person, time, color):
    with _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE month=? AND day=?", (month, day)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO cards "
            "(month, day, destination, truck, person, time, color, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                month,
                day,
                destination,
                truck,
                person,
                time,
                color,
                n,
                datetime.now().isoformat(timespec="seconds"),
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
