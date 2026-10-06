import sqlite3
import threading
import time

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


class ConversationStore:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "channel_id INTEGER NOT NULL, ts REAL NOT NULL, "
            "role TEXT NOT NULL, content TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id, id)"
        )
        self._db.commit()

    def append(self, channel_id: int, role: str, content: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO messages(channel_id, ts, role, content) VALUES (?, ?, ?, ?)",
                (channel_id, time.time(), role, content),
            )
            self._db.commit()

    def window(self, channel_id: int, budget_tokens: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM messages WHERE channel_id = ? ORDER BY id DESC",
                (channel_id,),
            ).fetchall()
        selected = []
        used = 0
        for role, content in rows:
            used += estimate_tokens(content)
            if used > budget_tokens:
                break
            selected.append({"role": role, "content": content})
        selected.reverse()
        return selected

    def reset(self, channel_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
            self._db.commit()
