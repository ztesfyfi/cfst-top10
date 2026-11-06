import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('builtin','file')),
 path TEXT,
 enabled INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

class Database:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "cfst.sqlite3"
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def list_sources(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM sources ORDER BY kind, created_at"
            ).fetchall()]

    def add_file_source(self, source_id, name, path):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,kind,path,enabled) VALUES(?,?,'file',?,1)",
                (source_id, name, path),
            )

    def set_enabled(self, source_id, enabled):
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE sources SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND kind='file'",
                (int(enabled), source_id),
            )
            return cur.rowcount == 1

    def delete_file_source(self, source_id):
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM sources WHERE id=? AND kind='file'", (source_id,))
            return cur.rowcount == 1
