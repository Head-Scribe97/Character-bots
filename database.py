import sqlite3
from contextlib import contextmanager

DB_PATH = "/data/characters.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                avatar_url TEXT,
                personality TEXT,
                backstory TEXT,
                speech_style TEXT,
                boundaries TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                welcome_enabled INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


def list_characters(active_only: bool = False):
    with get_conn() as conn:
        query = "SELECT * FROM characters ORDER BY name"
        if active_only:
            query = "SELECT * FROM characters WHERE active = 1 ORDER BY name"
        return [dict(row) for row in conn.execute(query).fetchall()]


def get_character(character_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        return dict(row) if row else None


def get_character_by_name(name: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        return dict(row) if row else None


def create_character(data: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO characters
                (name, avatar_url, personality, backstory, speech_style,
                 boundaries, active, welcome_enabled)
            VALUES
                (:name, :avatar_url, :personality, :backstory, :speech_style,
                 :boundaries, :active, :welcome_enabled)
            """,
            data,
        )


def update_character(character_id: int, data: dict):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE characters SET
                name=:name, avatar_url=:avatar_url, personality=:personality,
                backstory=:backstory, speech_style=:speech_style,
                boundaries=:boundaries, active=:active,
                welcome_enabled=:welcome_enabled
            WHERE id=:id
            """,
            {**data, "id": character_id},
        )


def delete_character(character_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))


def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
