import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]

    if 'sonarr_remote_url' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN sonarr_remote_url TEXT")
        print("Added sonarr_remote_url column to settings table.")
    else:
        print("Column sonarr_remote_url already exists in settings table.")

    if 'radarr_remote_url' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN radarr_remote_url TEXT")
        print("Added radarr_remote_url column to settings table.")
    else:
        print("Column radarr_remote_url already exists in settings table.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 026_add_remote_url_to_settings.py")
    upgrade()
    print("Migration 026_add_remote_url_to_settings.py completed.")
