#!/usr/bin/env python3
"""Stage 6 - Application tracker (SQLite at data/tracker.db).

Usage:
  python tracker.py init
  python tracker.py add --job-id X --title "..." --company "..." --source Y \
                        --url U --score 85 --cv tailored/cv_x.md
  python tracker.py set-status <rowid> applied|drafted|rejected|interview|closed
  python tracker.py list
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
  rowid_hint INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, title TEXT, company TEXT, source TEXT, url TEXT,
  score INTEGER, status TEXT DEFAULT 'queued',
  cv_path TEXT, draft_id TEXT, applied_on TEXT, notes TEXT,
  created_at TEXT DEFAULT (DATE('now'))
);
"""


def conn():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "add", "set-status", "list"])
    ap.add_argument("--job-id"); ap.add_argument("--title"); ap.add_argument("--company")
    ap.add_argument("--source"); ap.add_argument("--url"); ap.add_argument("--score", type=int)
    ap.add_argument("--cv"); ap.add_argument("--notes")
    ap.add_argument("pos", nargs="*", help="rowid and/or status for set-status")
    a = ap.parse_args()
    c = conn()
    if a.cmd == "init":
        print(f"tracker ready at {DB}")
    elif a.cmd == "add":
        cur = c.execute(
            "INSERT INTO applications (job_id,title,company,source,url,score,cv_path,notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (a.job_id, a.title, a.company, a.source, a.url, a.score, a.cv, a.notes))
        c.commit()
        print(f"queued as row {cur.lastrowid}")
    elif a.cmd == "set-status":
        rowid, status = a.pos[0], a.pos[1]
        extra = ", applied_on = ?" if status == "applied" else ""
        c.execute(f"UPDATE applications SET status=?{extra} WHERE rowid_hint=?",
                  (status, date.today().isoformat(), rowid))
        c.commit()
        print(f"row {rowid} -> {status}")
    elif a.cmd == "list":
        for r in c.execute("SELECT rowid_hint, status, score, title, company, source, applied_on "
                           "FROM applications ORDER BY rowid_hint DESC"):
            print(f"  #{r[0]} [{r[1]:8s}] {r[2] or '-':>3}  {r[3][:45]:45s} {r[4][:20]:20s} {r[5]}")


if __name__ == "__main__":
    main()
