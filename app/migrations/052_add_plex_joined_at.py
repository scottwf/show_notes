"""
Migration 052: Add plex_joined_at column to users table

Adds a column to store the user's actual Plex account creation date
from Plex's API, rather than relying on local activity log.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Add plex_joined_at column to users table
        cur.execute('''
            ALTER TABLE users ADD COLUMN plex_joined_at DATETIME
        ''')

        conn.commit()
        print("✓ Added plex_joined_at column to users table")

    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("✓ plex_joined_at column already exists")
        else:
            conn.rollback()
            print(f"Error in migration 052: {e}")
            raise
    except Exception as e:
        conn.rollback()
        print(f"Error in migration 052: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
