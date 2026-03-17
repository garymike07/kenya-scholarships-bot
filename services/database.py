import sqlite3
import os
import time
import logging
import httpx
from config import DB_PATH, CONVEX_SITE_URL

log = logging.getLogger(__name__)

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

_sub_cache: dict[str, dict] = {}
_SUB_CACHE_TTL = 300


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
            uid TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT,
            description TEXT,
            summary TEXT,
            category TEXT,
            amount TEXT,
            deadline TEXT,
            eligibility TEXT DEFAULT '',
            host_country TEXT DEFAULT '',
            level TEXT DEFAULT '',
            benefits TEXT DEFAULT '',
            posted_at REAL,
            sent_to_channel INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            is_premium INTEGER DEFAULT 0,
            premium_until REAL DEFAULT 0,
            joined_at REAL,
            daily_count INTEGER DEFAULT 0,
            last_reset_date TEXT
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_type TEXT NOT NULL,
            access_code TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            expires_at REAL DEFAULT 0,
            activated_at REAL,
            source TEXT DEFAULT 'convex',
            UNIQUE(user_id, service_type)
        );

        CREATE INDEX IF NOT EXISTS idx_opp_category ON opportunities(category);
        CREATE INDEX IF NOT EXISTS idx_opp_sent ON opportunities(sent_to_channel);
        CREATE INDEX IF NOT EXISTS idx_opp_url ON opportunities(url);
        CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sub_code ON subscriptions(access_code);

        CREATE TABLE IF NOT EXISTS scraped_pages (
            page_hash TEXT PRIMARY KEY,
            source TEXT,
            url TEXT,
            scraped_at REAL,
            item_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS known_urls (
            url_hash TEXT PRIMARY KEY,
            added_at REAL
        );
    """)
    for col in ("eligibility", "host_country", "level", "benefits"):
        try:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass
    conn.commit()
    conn.close()


# ─── SUBSCRIPTION / ACCESS CONTROL ───

def validate_access_code_remote(code: str) -> dict | None:
    if not CONVEX_SITE_URL:
        return None
    cache_key = f"code:{code}"
    cached = _sub_cache.get(cache_key)
    if cached and cached["_ts"] > time.time() - _SUB_CACHE_TTL:
        return cached

    try:
        resp = httpx.get(
            f"{CONVEX_SITE_URL}/api/telegram/validate",
            params={"code": code},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                data["_ts"] = time.time()
                _sub_cache[cache_key] = data
                return data
    except Exception as e:
        log.warning("Convex validation failed for code %s: %s", code[:12], e)
    return None


def activate_subscription(user_id: int, service_type: str, access_code: str, expires_at: float):
    conn = get_conn()
    conn.execute("""
        INSERT INTO subscriptions (user_id, service_type, access_code, status, expires_at, activated_at, source)
        VALUES (?, ?, ?, 'active', ?, ?, 'convex')
        ON CONFLICT(user_id, service_type) DO UPDATE SET
            access_code = excluded.access_code,
            status = 'active',
            expires_at = excluded.expires_at,
            activated_at = excluded.activated_at
    """, (user_id, service_type, access_code, expires_at, time.time()))
    conn.commit()
    conn.close()
    _sub_cache.pop(f"user:{user_id}:{service_type}", None)


def has_active_subscription(user_id: int, service_type: str) -> bool:
    cache_key = f"user:{user_id}:{service_type}"
    cached = _sub_cache.get(cache_key)
    if cached and cached["_ts"] > time.time() - _SUB_CACHE_TTL:
        return cached["active"]

    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND service_type = ? AND status = 'active'",
        (user_id, service_type)
    ).fetchone()
    conn.close()

    active = False
    if row:
        if row["expires_at"] == 0 or row["expires_at"] > time.time():
            active = True
        else:
            _expire_subscription(user_id, service_type)

    _sub_cache[cache_key] = {"active": active, "_ts": time.time()}
    return active


def get_user_subscriptions(user_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active'",
        (user_id,)
    ).fetchall()
    conn.close()
    now = time.time()
    result = []
    for r in rows:
        d = dict(r)
        if d["expires_at"] > 0 and d["expires_at"] <= now:
            _expire_subscription(user_id, d["service_type"])
            continue
        result.append(d)
    return result


def _expire_subscription(user_id: int, service_type: str):
    conn = get_conn()
    conn.execute(
        "UPDATE subscriptions SET status = 'expired' WHERE user_id = ? AND service_type = ?",
        (user_id, service_type)
    )
    conn.commit()
    conn.close()
    _sub_cache.pop(f"user:{user_id}:{service_type}", None)


def opportunity_exists(uid: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM opportunities WHERE uid = ?", (uid,)).fetchone()
    conn.close()
    return row is not None


def save_opportunity(opp_dict: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO opportunities
        (uid, title, url, source, description, summary, category, amount, deadline,
         eligibility, host_country, level, benefits, posted_at)
        VALUES (:uid, :title, :url, :source, :description, :summary, :category,
                :amount, :deadline, :eligibility, :host_country, :level, :benefits, :posted_at)
    """, opp_dict)
    conn.commit()
    conn.close()


def get_unsent_opportunities(limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE sent_to_channel = 0 ORDER BY posted_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_sent(uid: str):
    conn = get_conn()
    conn.execute("UPDATE opportunities SET sent_to_channel = 1 WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()


def register_user(user_id: int, username: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO users (user_id, username, joined_at, daily_count, last_reset_date)
        VALUES (?, ?, ?, 0, date('now'))
    """, (user_id, username, time.time()))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def increment_daily_count(user_id: int) -> int:
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return 0
    today = conn.execute("SELECT date('now')").fetchone()[0]
    if user["last_reset_date"] != today:
        conn.execute("UPDATE users SET daily_count = 1, last_reset_date = ? WHERE user_id = ?", (today, user_id))
        conn.commit()
        conn.close()
        return 1
    new_count = user["daily_count"] + 1
    conn.execute("UPDATE users SET daily_count = ? WHERE user_id = ?", (new_count, user_id))
    conn.commit()
    conn.close()
    return new_count


def set_premium(user_id: int, until: float):
    conn = get_conn()
    conn.execute("UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?", (until, user_id))
    conn.commit()
    conn.close()


def is_premium(user_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return False
    return row["is_premium"] == 1 and row["premium_until"] > time.time()


def get_user_count() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    conn.close()
    return row[0]


def get_opportunities_by_category(category: str, limit: int = 5) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE category = ? ORDER BY posted_at DESC LIMIT ?",
        (category, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── DEDUP: zero-memory knowledge base stored in SQLite ───

import hashlib


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def url_already_known(url: str) -> bool:
    h = _hash(url)
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM known_urls WHERE url_hash = ?", (h,)).fetchone()
    conn.close()
    return row is not None


def mark_url_known(url: str):
    h = _hash(url)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO known_urls (url_hash, added_at) VALUES (?, ?)", (h, time.time()))
    conn.commit()
    conn.close()


def bulk_check_urls(urls: list[str]) -> set[str]:
    """Return set of URLs that are already known. Single DB query."""
    if not urls:
        return set()
    hashes = {_hash(u): u for u in urls}
    conn = get_conn()
    placeholders = ",".join("?" * len(hashes))
    rows = conn.execute(
        f"SELECT url_hash FROM known_urls WHERE url_hash IN ({placeholders})",
        list(hashes.keys())
    ).fetchall()
    conn.close()
    known_hashes = {r[0] for r in rows}
    return {hashes[h] for h in known_hashes if h in hashes}


def bulk_mark_urls(urls: list[str]):
    if not urls:
        return
    now = time.time()
    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO known_urls (url_hash, added_at) VALUES (?, ?)",
        [(_hash(u), now) for u in urls]
    )
    conn.commit()
    conn.close()


def page_already_scraped(source: str, page_url: str, max_age_hours: int = 1) -> bool:
    h = _hash(f"{source}:{page_url}")
    conn = get_conn()
    row = conn.execute("SELECT scraped_at FROM scraped_pages WHERE page_hash = ?", (h,)).fetchone()
    conn.close()
    if not row:
        return False
    return (time.time() - row[0]) < (max_age_hours * 3600)


def mark_page_scraped(source: str, page_url: str, item_count: int = 0):
    h = _hash(f"{source}:{page_url}")
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO scraped_pages (page_hash, source, url, scraped_at, item_count) VALUES (?, ?, ?, ?, ?)",
        (h, source, page_url, time.time(), item_count)
    )
    conn.commit()
    conn.close()


def cleanup_old_page_records(max_age_hours: int = 24):
    cutoff = time.time() - (max_age_hours * 3600)
    conn = get_conn()
    conn.execute("DELETE FROM scraped_pages WHERE scraped_at < ?", (cutoff,))
    conn.commit()
    conn.close()
