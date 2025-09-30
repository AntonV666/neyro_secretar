# app/storage.py
import sqlite3
from pathlib import Path

class Storage:
    def __init__(self, path: str = "sqlite.db"):
        self.db_path = Path(path)
        self.conn = sqlite3.connect(self.db_path)
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        self.conn.commit()

    def add_note(self, text: str):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO notes (text) VALUES (?)", (text,))
        self.conn.commit()

    def list_notes(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT text FROM notes ORDER BY created DESC LIMIT 20")
        return [row[0] for row in cur.fetchall()]
