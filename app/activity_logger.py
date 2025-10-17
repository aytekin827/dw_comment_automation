
import datetime
import os
import sqlite3
import time
import traceback
from contextlib import contextmanager
from typing import Dict, Iterable

# You can override DB path with env var: ACTION_LOG_DB
DB_PATH = os.getenv("ACTION_LOG_DB", "action_logs.sqlite3")


def init_db():
    """Create the SQLite schema if it does not exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp_utc TEXT NOT NULL,
              post_url TEXT NOT NULL,
              action_type TEXT NOT NULL CHECK (action_type IN ('comment','like')),
              attempt_no INTEGER NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('success','error')),
              error_type TEXT,
              error_message TEXT,
              elapsed_ms INTEGER,
              selector_used TEXT,
              -- LLM metadata (for comment generation)
              model TEXT,
              response_id TEXT,
              prompt_chars INTEGER,
              comment_chars INTEGER,
              comment_text TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_actions_unique
            ON actions(post_url, action_type, timestamp_utc)
            """
        )


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@contextmanager
def log_action(post_url: str, action_type: str, attempt_no: int = 1, selector_used: str | None = None):
    """
    Usage:
        with log_action(post_url=url, action_type="comment", attempt_no=1, selector_used="textarea.selector") as meta:
            # do work
            meta["model"] = "gpt-4o-mini"   # optional metadata (will be saved with the row)
            ...
    On exception -> status=error; otherwise -> success
    """
    start = time.time()
    meta = {
        "post_url": post_url,
        "action_type": action_type,
        "attempt_no": attempt_no,
        "selector_used": selector_used,
    }
    error: Exception | None = None
    try:
        yield meta
    except Exception as e:  # bubble up after recording
        error = e
        raise
    finally:
        elapsed_ms = int((time.time() - start) * 1000)
        status = "success" if error is None else "error"
        err_type = error.__class__.__name__ if error else None
        err_msg = "".join(traceback.format_exception_only(type(error), error)).strip() if error else None

        _insert_action(
            timestamp_utc=_utc_now_iso(),
            elapsed_ms=elapsed_ms,
            status=status,
            error_type=err_type,
            error_message=err_msg,
            **meta,
        )


def _insert_action(
    timestamp_utc: str,
    post_url: str,
    action_type: str,
    attempt_no: int,
    status: str,
    elapsed_ms: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    selector_used: str | None = None,
    model: str | None = None,
    response_id: str | None = None,
    prompt_chars: int | None = None,
    comment_chars: int | None = None,
    comment_text: str | None = None,
    ):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO actions
            (timestamp_utc, post_url, action_type, attempt_no, status,
             error_type, error_message, elapsed_ms, selector_used,
             model, response_id, prompt_chars, comment_chars, comment_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp_utc,
                post_url,
                action_type,
                attempt_no,
                status,
                error_type,
                error_message,
                elapsed_ms,
                selector_used,
                model,
                response_id,
                prompt_chars,
                comment_chars,
                comment_text,
            ),
        )


# --------------------------- Query helpers ---------------------------

def fetch_action_status(urls: Iterable[str] | None = None) -> Dict[str, Dict[str, bool]]:
    """
    Returns a dict:
      { post_url: {"comment": True/False, "like": True/False} }
    considering only rows with status='success'.
    If urls is None, returns for all known URLs.
    """
    q = """
        SELECT post_url, action_type, MAX(status='success') as ok
        FROM actions
        {where}
        GROUP BY post_url, action_type
    """
    where = ""
    params: list = []
    if urls:
        placeholders = ",".join("?" for _ in urls)
        where = f"WHERE post_url IN ({placeholders})"
        params = list(urls)

    out: Dict[str, Dict[str, bool]] = {}
    with sqlite3.connect(DB_PATH) as conn:
        for row in conn.execute(q.format(where=where), params):
            url, action, okflag = row
            d = out.setdefault(url, {"comment": False, "like": False})
            if okflag:
                d[action] = True
    return out


def is_fully_processed(post_url: str) -> bool:
    """True if both comment and like have a success record for this URL."""
    st = fetch_action_status([post_url]).get(post_url, {})
    return bool(st.get("comment") and st.get("like"))


def filter_unprocessed(urls: Iterable[str]) -> list[str]:
    """Return URLs that still need at least one of (comment, like)."""
    status = fetch_action_status(urls)
    result = []
    for u in urls:
        s = status.get(u, {"comment": False, "like": False})
        if not (s.get("comment") and s.get("like")):
            result.append(u)
    return result


def get_db_path() -> str:
    return DB_PATH
