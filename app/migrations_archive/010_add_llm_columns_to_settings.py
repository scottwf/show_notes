import sqlite3
import os

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if 'openai_api_key' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN openai_api_key TEXT")
        print("Added openai_api_key column to settings table.")
    else:
        print("Column openai_api_key already exists in settings table.")
    if 'preferred_llm_provider' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN preferred_llm_provider TEXT")
        print("Added preferred_llm_provider column to settings table.")
    else:
        print("Column preferred_llm_provider already exists in settings table.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 010_add_llm_columns_to_settings.py")
    upgrade()
    print("Migration 010_add_llm_columns_to_settings.py completed.")
