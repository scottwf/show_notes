"""
Migration 044: Add user profile fields

Adds profile photo, bio, and privacy settings to users table.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 044: Add user profile fields")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Add profile fields to users table
    try:
        cur.execute('ALTER TABLE users ADD COLUMN profile_photo_url TEXT')
        print("✓ Added profile_photo_url column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise
        print("  - profile_photo_url column already exists")

    try:
        cur.execute('ALTER TABLE users ADD COLUMN bio TEXT')
        print("✓ Added bio column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise
        print("  - bio column already exists")

    try:
        cur.execute('ALTER TABLE users ADD COLUMN profile_is_public BOOLEAN DEFAULT 1')
        print("✓ Added profile_is_public column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise
        print("  - profile_is_public column already exists")

    try:
        cur.execute('ALTER TABLE users ADD COLUMN external_links TEXT')
        print("✓ Added external_links column (JSON)")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise
        print("  - external_links column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 044 completed successfully")

if __name__ == '__main__':
    upgrade()
