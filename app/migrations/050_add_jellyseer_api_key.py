"""
Migration 050: Add Jellyseer API key setting

Adds jellyseer_api_key column to settings table for API integration
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 050: Add Jellyseer API key setting")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute('ALTER TABLE settings ADD COLUMN jellyseer_api_key TEXT')
        print("✓ Added jellyseer_api_key column to settings")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("⚠ Column jellyseer_api_key already exists, skipping")
        else:
            raise

    conn.commit()
    conn.close()

    print("✅ Migration 050 completed successfully")

if __name__ == '__main__':
    upgrade()
