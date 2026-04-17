"""
Migration 045: Add finale_notifications preference to users table.

Values:
  'all'       (default) — notify for finales of any show in the library
  'favorites' — notify only for favorited shows
"""

import sqlite3
import os


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN finale_notifications TEXT NOT NULL DEFAULT 'all'"
        )
        conn.commit()
        print("Migration 045: added finale_notifications column to users")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("Migration 045: column already exists, skipping")
        else:
            raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
