import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if 'ollama_model_name' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN ollama_model_name TEXT")
        print("Added ollama_model_name column to settings table.")
    else:
        print("Column ollama_model_name already exists in settings table.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 011_add_ollama_model_name_to_settings.py")
    upgrade()
    print("Migration 011_add_ollama_model_name_to_settings.py completed.")
