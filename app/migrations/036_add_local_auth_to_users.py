"""
Migration 036: Add local authentication columns to users table

Adds username and password_hash columns to support local authentication
during onboarding (in addition to Plex OAuth).
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 036: Add local authentication to users")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check existing columns
    cur.execute("PRAGMA table_info(users)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # Add username column
    if 'username' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
        print("✓ Added username column")
    else:
        print("✓ username column already exists")

    # Add password_hash column
    if 'password_hash' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        print("✓ Added password_hash column")
    else:
        print("✓ password_hash column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 036 completed successfully")

if __name__ == '__main__':
    upgrade()
