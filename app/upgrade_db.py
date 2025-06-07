import sqlite3
import os

DB_PATH = os.environ.get('SHOWNOTES_DB', 'instance/shownotes.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS plex_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    user_id INTEGER,
    user_name TEXT,
    media_type TEXT,
    show_title TEXT,
    episode_title TEXT,
    season INTEGER,
    episode INTEGER,
    summary TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT
);
'''

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        print('plex_events table created or already exists.')
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
