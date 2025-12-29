"""
Migration 025: Add timezone setting to settings table

This migration adds a 'timezone' column to the settings table to allow
users to configure their local timezone for displaying watch history and
other timestamps. Default is 'UTC'.
"""

import sqlite3
import os

# Check multiple possible locations for the database
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH_INSTANCE = os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3')
DB_PATH_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'shownotes.sqlite3')

# Try to find the database
if os.path.exists(DB_PATH_INSTANCE):
    DB_PATH = DB_PATH_INSTANCE
elif os.path.exists(DB_PATH_ROOT):
    DB_PATH = DB_PATH_ROOT
else:
    DB_PATH = os.environ.get('SHOWNOTES_DB', DB_PATH_INSTANCE)

def upgrade():
    """Add timezone column to settings table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if 'timezone' not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN timezone TEXT DEFAULT 'UTC'")
        print("Added timezone column to settings table (default: UTC)")
    else:
        print("Column timezone already exists in settings table.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 025_add_timezone_to_settings.py")
    upgrade()
    print("Migration 025_add_timezone_to_settings.py completed.")
