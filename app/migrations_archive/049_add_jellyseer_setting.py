"""
Migration 049: Add Jellyseer URL setting

Adds jellyseer_url column to settings table for integration with Jellyseer/Overseerr
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 049: Add Jellyseer URL setting")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute('ALTER TABLE settings ADD COLUMN jellyseer_url TEXT')
        print("✓ Added jellyseer_url column to settings")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("⚠ Column jellyseer_url already exists, skipping")
        else:
            raise

    conn.commit()
    conn.close()

    print("✅ Migration 049 completed successfully")

if __name__ == '__main__':
    upgrade()
