"""
Migration 035: Add missing settings columns for onboarding

Adds columns that onboarding needs but weren't in the initial schema:
- pushover_key (separate from pushover_api_key)
- pushover_token
- plex_client_id
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 035: Add missing settings columns")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check existing columns
    cur.execute("PRAGMA table_info(settings)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # Add missing columns
    if 'pushover_key' not in existing_cols:
        cur.execute("ALTER TABLE settings ADD COLUMN pushover_key TEXT")
        print("✓ Added pushover_key column")
    else:
        print("✓ pushover_key column already exists")

    if 'pushover_token' not in existing_cols:
        cur.execute("ALTER TABLE settings ADD COLUMN pushover_token TEXT")
        print("✓ Added pushover_token column")
    else:
        print("✓ pushover_token column already exists")

    if 'plex_client_id' not in existing_cols:
        cur.execute("ALTER TABLE settings ADD COLUMN plex_client_id TEXT")
        print("✓ Added plex_client_id column")
    else:
        print("✓ plex_client_id column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 035 completed successfully")

if __name__ == '__main__':
    upgrade()
