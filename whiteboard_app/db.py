"""SQLite-backed shared store for the factory whiteboard prototype."""

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
