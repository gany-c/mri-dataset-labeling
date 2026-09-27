import os
import sqlite3
from pathlib import Path

TARGETS = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA',
           'PF OA', 'Effusion', 'Synovitis', "Baker's", 'Contusion', 'Fracture']
DATA = Path(os.environ.get('KNEE_REVIEW_DATA', Path(__file__).resolve().parents[1] / 'data'))

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / 'reviews.sqlite3', timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS studies(uid TEXT PRIMARY KEY, title TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS series(uid TEXT PRIMARY KEY, study TEXT REFERENCES studies(uid), description TEXT,
          plane TEXT, orientation TEXT, spacing TEXT, warnings TEXT, slices TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviewers(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE,
          password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, reviewer INTEGER REFERENCES reviewers(id), expires INTEGER);
        CREATE TABLE IF NOT EXISTS reviews(study TEXT REFERENCES studies(uid), reviewer INTEGER REFERENCES reviewers(id),
          labels TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
          revision INTEGER NOT NULL, updated TEXT NOT NULL, PRIMARY KEY(study));
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, study TEXT, reviewer INTEGER,
          labels TEXT, notes TEXT, status TEXT, revision INTEGER, updated TEXT);
        ''')
