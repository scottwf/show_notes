import sqlite3, os

DB_PATH = os.environ.get('SHOWNOTES_DB', 'instance/shownotes.sqlite3')

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if 'last_login_at' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    upgrade()
