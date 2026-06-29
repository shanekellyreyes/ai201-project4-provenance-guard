import sqlite3, os
from datetime import datetime, timezone

DB_PATH = os.environ.get("PROVENANCE_DB", "provenance.db")

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS submissions (
            content_id TEXT PRIMARY KEY,
            creator_id TEXT, text TEXT, attribution TEXT,
            confidence REAL, llm_score REAL, stylo_score REAL,
            status TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT, creator_id TEXT, timestamp TEXT,
            event_type TEXT, attribution TEXT, confidence REAL,
            llm_score REAL, stylo_score REAL, status TEXT,
            appeal_reasoning TEXT)""")

def _now():
    return datetime.now(timezone.utc).isoformat()

def save_submission(r):
    with _conn() as c:
        c.execute("""INSERT OR REPLACE INTO submissions
            (content_id, creator_id, text, attribution, confidence,
             llm_score, stylo_score, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (r["content_id"], r["creator_id"], r["text"], r["attribution"],
             r["confidence"], r["llm_score"], r["stylo_score"],
             r["status"], r["created_at"]))

def log_event(e):
    with _conn() as c:
        c.execute("""INSERT INTO audit_log
            (content_id, creator_id, timestamp, event_type, attribution,
             confidence, llm_score, stylo_score, status, appeal_reasoning)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (e.get("content_id"), e.get("creator_id"), _now(),
             e.get("event_type"), e.get("attribution"), e.get("confidence"),
             e.get("llm_score"), e.get("stylo_score"), e.get("status"),
             e.get("appeal_reasoning")))

def get_submission(content_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM submissions WHERE content_id=?",
                        (content_id,)).fetchone()
        return dict(row) if row else None

def update_status(content_id, status):
    with _conn() as c:
        c.execute("UPDATE submissions SET status=? WHERE content_id=?",
                  (status, content_id))

def get_log(limit=50):
    with _conn() as c:
        rows = c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
        return [dict(r) for r in rows]
