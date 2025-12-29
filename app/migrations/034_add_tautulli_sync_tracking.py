"""
Migration 034: Add Tautulli sync tracking

Adds column to track the last successful Tautulli sync timestamp
for incremental updates.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 034: Add Tautulli sync tracking")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check if column already exists
    cur.execute("PRAGMA table_info(settings)")
    existing_cols = [row[1] for row in cur.fetchall()]

    if 'tautulli_last_sync' not in existing_cols:
        cur.execute("ALTER TABLE settings ADD COLUMN tautulli_last_sync DATETIME")
        print("✓ Added tautulli_last_sync column")
    else:
        print("✓ tautulli_last_sync column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 034 completed successfully")

if __name__ == '__main__':
    upgrade()
