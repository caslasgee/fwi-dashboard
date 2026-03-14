"""SQLite TTL cache used by service wrappers."""
from __future__ import annotations
import sqlite3, pickle, time
from pathlib import Path
from typing import Any, Optional


class TTLCache:
    def __init__(self, db_path: str = ".cache/fire_risk_cache.sqlite"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as c:
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value BLOB NOT NULL, exp INTEGER)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_exp ON cache(exp)")

    def get(self, key: str) -> Optional[Any]:
        now = int(time.time())
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("SELECT value, exp FROM cache WHERE key=?", (key,)).fetchone()
            if not row:
                return None
            blob, exp = row
            if exp is not None and exp < now:
                c.execute("DELETE FROM cache WHERE key=?", (key,))
                return None
            try:
                return pickle.loads(blob)
            except Exception:
                c.execute("DELETE FROM cache WHERE key=?", (key,))
                return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        exp = int(time.time()) + int(ttl_seconds) if ttl_seconds is not None else None
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT OR REPLACE INTO cache(key,value,exp) VALUES(?,?,?)", (key, blob, exp))

    def purge_expired(self) -> None:
        now = int(time.time())
        with sqlite3.connect(self.db_path) as c:
            c.execute("DELETE FROM cache WHERE exp IS NOT NULL AND exp < ?", (now,))

    def make_key(self, prefix: str, **kwargs) -> str:
        ordered = "|".join(f"{k}={kwargs[k]}" for k in sorted(kwargs))
        return f"{prefix}|{ordered}"


cache = TTLCache()
