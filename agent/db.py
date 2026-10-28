"""SQLite store. One file, no ORM. Schema is created on first use."""
from __future__ import annotations
import json
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE,
  domain TEXT,
  ats TEXT,              -- greenhouse | lever | ashby | workable | other
  board_token TEXT,
  sector TEXT,           -- climate | ai | design_agency | creative | tech | other
  watch INTEGER DEFAULT 1,
  notes TEXT,
  problem_statement TEXT, -- publicly stated problem (for proposals)
  problem_source_url TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  fingerprint TEXT UNIQUE,   -- sha1(source|external_id) or sha1(url)
  source TEXT NOT NULL,      -- greenhouse | lever | ashby | hn | adzuna | manual | social | ...
  external_id TEXT,
  company TEXT,
  company_id INTEGER,
  title TEXT,
  location TEXT,
  remote INTEGER,
  url TEXT,
  apply_url TEXT,
  description TEXT,
  posted_at TEXT,
  discovered_at TEXT,
  raw TEXT,
  sector TEXT,
  status TEXT DEFAULT 'new', -- new | scored | queued | skipped | applied | closed
  score REAL,
  score_reason TEXT,
  score_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER,            -- nullable for proposals
  company_id INTEGER,
  kind TEXT NOT NULL,        -- ats_web | email | proposal | social_mention | manual
  status TEXT DEFAULT 'draft', -- draft | pending_approval | approved | sent | failed | withdrawn
  needs_approval INTEGER DEFAULT 1,
  resume_pdf TEXT,
  resume_json TEXT,          -- the exact content rendered into the PDF
  answers_json TEXT,         -- form fields we filled: {question: answer}
  cover_text TEXT,
  email_to TEXT,
  email_subject TEXT,
  email_body TEXT,
  diy_ratio REAL,            -- share of content not traceable to master docs (target <= 0.15)
  diy_notes TEXT,            -- what was invented/extrapolated, so the user can check
  created_at TEXT,
  approved_at TEXT,
  sent_at TEXT,
  sent_log TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT, finished_at TEXT,
  summary TEXT
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS verdicts (
  job_id INTEGER PRIMARY KEY,
  verdict TEXT NOT NULL,     -- good | nope: yours, on the job as it was scored
  reason TEXT,               -- the main reason: a scoring dimension's name, 'Other', or 'prepared' (Prepare counts as Good)
  at TEXT,
  score REAL,                -- the score and score_json when you judged it, so a later rescore doesn't change what you judged
  score_json TEXT,
  prev_status TEXT           -- jobs.status before a Nope took it off To do
);
CREATE TABLE IF NOT EXISTS versions (   -- what a score depended on (agent/scoring.py · versions), first seen when
  kind TEXT, hash TEXT, first_at TEXT, content TEXT,
  PRIMARY KEY (kind, hash)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)   # wait for a writer instead of failing
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")      # readers (the dashboard) never block on a long refresh
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
    if "jev_p" not in cols:  # migration: Jev first-pass probability
        con.execute("ALTER TABLE jobs ADD COLUMN jev_p REAL")
    if "kw_score" not in cols:  # migration: free keyword relevance, used to order Claude scoring
        con.execute("ALTER TABLE jobs ADD COLUMN kw_score REAL")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ---- jobs -------------------------------------------------------------
def upsert_job(con: sqlite3.Connection, job: dict) -> tuple[int, bool]:
    """Insert if unseen. Returns (id, inserted)."""
    fp = job.get("fingerprint") or fingerprint(job["source"], job.get("external_id") or job.get("url", ""))
    row = con.execute("SELECT id FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
    if row:
        return row["id"], False
    cur = con.execute(
        """INSERT INTO jobs (fingerprint, source, external_id, company, company_id, title, location, remote,
                 url, apply_url, description, posted_at, discovered_at, raw, sector)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fp, job["source"], job.get("external_id"), job.get("company"), job.get("company_id"),
         job.get("title"), job.get("location"), int(bool(job.get("remote"))), job.get("url"),
         job.get("apply_url"), job.get("description"), job.get("posted_at"), now(),
         json.dumps(job.get("raw"), ensure_ascii=False) if job.get("raw") is not None else None,
         job.get("sector")),
    )
    return cur.lastrowid, True


def role_key(company: str | None, title: str | None) -> str:
    """One role, however many cities it is posted in: company + title, normalised."""
    import re
    return re.sub(r"\W+", " ", f"{company or ''}|{title or ''}".lower()).strip()


def applied_role(con, job: dict) -> int | None:
    """The application already made for this role in any city (not withdrawn), or None."""
    for r in con.execute("SELECT a.id, j.company, j.title FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.status != 'withdrawn' "
                         "AND lower(j.company)=lower(?)", (job.get("company") or "",)).fetchall():
        if role_key(r["company"], r["title"]) == role_key(job.get("company"), job.get("title")):
            return r["id"]
    return None


def jobs_by_status(con, status: str, limit: int = 500) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM jobs WHERE status=? ORDER BY discovered_at DESC LIMIT ?", (status, limit)).fetchall()


def set_score(con, job_id: int, score: float, reason: str, payload: dict, status: str = "scored"):
    con.execute("UPDATE jobs SET score=?, score_reason=?, score_json=?, status=? WHERE id=?",
                (score, reason, json.dumps(payload, ensure_ascii=False), status, job_id))


# ---- applications -----------------------------------------------------
def create_application(con, **fields) -> int:
    fields.setdefault("created_at", now())
    cols = ", ".join(fields)
    qs = ", ".join("?" for _ in fields)
    cur = con.execute(f"INSERT INTO applications ({cols}) VALUES ({qs})", tuple(fields.values()))
    return cur.lastrowid


def update_application(con, app_id: int, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE applications SET {sets} WHERE id=?", (*fields.values(), app_id))


# ---- settings ---------------------------------------------------------
def get_setting(con, k: str, default=None):
    row = con.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return json.loads(row["v"]) if row else default


def set_setting(con, k: str, v):
    con.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
