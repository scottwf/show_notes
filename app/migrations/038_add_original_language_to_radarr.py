"""
Migration 038: Add original_language_name column to radarr_movies

Adds original_language_name column that the Radarr sync expects.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 038: Add original_language_name to radarr_movies")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check existing columns
    cur.execute("PRAGMA table_info(radarr_movies)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # Add original_language_name column
    if 'original_language_name' not in existing_cols:
        cur.execute("ALTER TABLE radarr_movies ADD COLUMN original_language_name TEXT")
        print("✓ Added original_language_name column")
    else:
        print("✓ original_language_name column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 038 completed successfully")

if __name__ == '__main__':
    upgrade()
