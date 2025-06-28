import sqlite3
import os
import sys
from datetime import datetime

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    cursor = conn.cursor()
    # Create the episode_characters table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS episode_characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        show_tmdb_id INTEGER,
        show_tvdb_id INTEGER,
        season_number INTEGER,
        episode_number INTEGER,
        episode_rating_key TEXT,
        character_name TEXT,
        actor_name TEXT,
        actor_id INTEGER,
        actor_thumb TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    print("Successfully created 'episode_characters' table (if it didn't exist).")

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    try:
        upgrade(conn)
    finally:
        conn.close() 