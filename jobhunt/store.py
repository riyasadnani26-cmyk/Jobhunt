"""SQLite store: dedupes jobs across sources and days, tracks pipeline status."""
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .models import Contact, Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    found_on TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT, company TEXT, location TEXT,
    url TEXT, apply_url TEXT, easy_apply INTEGER,
    description TEXT, posted TEXT, company_domain TEXT,
    match_score INTEGER, matched_keywords TEXT, missing_keywords TEXT,
    resume_path TEXT, ats_score INTEGER, ats_before INTEGER,
    status TEXT DEFAULT 'new',
    extra TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    job_key TEXT, name TEXT, title TEXT, company TEXT,
    email TEXT, linkedin_url TEXT, confidence INTEGER, source TEXT,
    draft_id TEXT,
    PRIMARY KEY (job_key, name)
);
CREATE TABLE IF NOT EXISTS usage (
    day TEXT, counter TEXT, n INTEGER,
    PRIMARY KEY (day, counter)
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        try:  # databases created before ats_before existed
            self.db.execute("ALTER TABLE jobs ADD COLUMN ats_before INTEGER")
        except sqlite3.OperationalError:
            pass

    # --- daily counters (used to enforce per-day limits) ---
    def used(self, counter: str) -> int:
        row = self.db.execute(
            "SELECT n FROM usage WHERE day=? AND counter=?", (date.today().isoformat(), counter)
        ).fetchone()
        return row["n"] if row else 0

    def bump(self, counter: str, by: int = 1) -> None:
        self.db.execute(
            "INSERT INTO usage(day, counter, n) VALUES(?,?,?) "
            "ON CONFLICT(day, counter) DO UPDATE SET n = n + excluded.n",
            (date.today().isoformat(), counter, by),
        )
        self.db.commit()

    # --- jobs ---
    def has_job(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone() is not None

    def add_job(self, job: Job) -> bool:
        """Insert a job; returns False if it was already known."""
        if self.has_job(job.key):
            return False
        d = asdict(job)
        self.db.execute(
            "INSERT INTO jobs(key, found_on, source, title, company, location, url, apply_url,"
            " easy_apply, description, posted, company_domain, extra)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job.key, date.today().isoformat(), d["source"], d["title"], d["company"],
             d["location"], d["url"], d["apply_url"], int(d["easy_apply"]), d["description"],
             d["posted"], d["company_domain"], json.dumps(d["extra"])),
        )
        self.db.commit()
        self.bump("jobs")
        return True

    def update_job(self, key: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {cols} WHERE key=?", (*fields.values(), key))
        self.db.commit()

    def jobs(self, where: str = "1=1", params: tuple = ()) -> list[sqlite3.Row]:
        return self.db.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY match_score DESC NULLS LAST", params
        ).fetchall()

    def row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            title=row["title"], company=row["company"], location=row["location"],
            url=row["url"], source=row["source"], description=row["description"] or "",
            apply_url=row["apply_url"] or "", easy_apply=bool(row["easy_apply"]),
            posted=row["posted"] or "", company_domain=row["company_domain"] or "",
            extra=json.loads(row["extra"] or "{}"),
        )

    # --- contacts ---
    def add_contact(self, job_key: str, c: Contact) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO contacts(job_key, name, title, company, email, linkedin_url,"
            " confidence, source) VALUES(?,?,?,?,?,?,?,?)",
            (job_key, c.name, c.title, c.company, c.email, c.linkedin_url, c.confidence, c.source),
        )
        self.db.commit()

    def contacts(self, job_key: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM contacts WHERE job_key=? ORDER BY confidence DESC", (job_key,)
        ).fetchall()

    def set_draft(self, job_key: str, name: str, draft_id: str) -> None:
        self.db.execute(
            "UPDATE contacts SET draft_id=? WHERE job_key=? AND name=?", (draft_id, job_key, name)
        )
        self.db.commit()
