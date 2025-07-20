import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if 'thetvdb_api_key' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN thetvdb_api_key TEXT")
        print("Added thetvdb_api_key column to settings table.")
    else:
        print("Column thetvdb_api_key already exists in settings table.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 016_add_thetvdb_api_key_to_settings.py")
    upgrade()
    print("Migration 016_add_thetvdb_api_key_to_settings.py completed.") 