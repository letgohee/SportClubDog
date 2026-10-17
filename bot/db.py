import sqlite3
from pathlib import Path

PAYMENT_LABELS = {"check": "🧾 Чек", "cash": "💵 Готівка"}


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # NOCASE у SQLite працює лише з латиницею, тому порівнюємо імена через casefold
        self.conn.create_function("casefold", 1, lambda s: s.casefold() if s else s, deterministic=True)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id   INTEGER NOT NULL,
                client     TEXT    NOT NULL,
                payment    TEXT    NOT NULL CHECK (payment IN ('check', 'cash')),
                date       TEXT    NOT NULL,  -- YYYY-MM-DD
                time       TEXT    NOT NULL,  -- HH:MM
                created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_owner_date ON sessions (owner_id, date)"
        )
        self.conn.commit()

    def add(self, owner_id: int, client: str, payment: str, date: str, time: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (owner_id, client, payment, date, time) VALUES (?, ?, ?, ?, ?)",
            (owner_id, client, payment, date, time),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete(self, owner_id: int, session_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM sessions WHERE id = ? AND owner_id = ?", (session_id, owner_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get(self, owner_id: int, session_id: int):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND owner_id = ?", (session_id, owner_id)
        ).fetchone()

    def by_date(self, owner_id: int, date: str):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE owner_id = ? AND date = ? ORDER BY time",
            (owner_id, date),
        ).fetchall()

    def by_month(self, owner_id: int, year: int, month: int):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE owner_id = ? AND date LIKE ? ORDER BY date, time",
            (owner_id, f"{year:04d}-{month:02d}-%"),
        ).fetchall()

    def days_with_sessions(self, owner_id: int, year: int, month: int) -> set[int]:
        rows = self.conn.execute(
            "SELECT DISTINCT date FROM sessions WHERE owner_id = ? AND date LIKE ?",
            (owner_id, f"{year:04d}-{month:02d}-%"),
        ).fetchall()
        return {int(r["date"][8:10]) for r in rows}

    def recent_clients(self, owner_id: int, limit: int = 8) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT client FROM sessions WHERE owner_id = ?
            GROUP BY client ORDER BY MAX(id) DESC LIMIT ?
            """,
            (owner_id, limit),
        ).fetchall()
        return [r["client"] for r in rows]

    def client_history(self, owner_id: int, client: str):
        return self.conn.execute(
            """
            SELECT * FROM sessions WHERE owner_id = ? AND casefold(client) = ?
            ORDER BY date DESC, time DESC
            """,
            (owner_id, client.casefold()),
        ).fetchall()
