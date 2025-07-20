import sqlite3
import os

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sonarr_url TEXT,
            sonarr_api_key TEXT,
            radarr_url TEXT,
            radarr_api_key TEXT,
            bazarr_url TEXT,
            bazarr_api_key TEXT,
            ollama_url TEXT,
            pushover_api_key TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plex_user_id TEXT UNIQUE,
            plex_username TEXT,
            plex_token TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    upgrade(conn)
    conn.close()
