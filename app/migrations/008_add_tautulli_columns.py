import sqlite3, os

DB_PATH = os.environ.get('SHOWNOTES_DB', 'instance/shownotes.sqlite3')

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if 'tautulli_url' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN tautulli_url TEXT")
    if 'tautulli_api_key' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN tautulli_api_key TEXT")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    upgrade()
