#!/usr/bin/env python3
"""
Migration 035: Add is_active to users

Allows admins to deactivate accounts. Plex users imported automatically
default to is_active=0 until an admin explicitly activates them.
Existing users default to is_active=1 so nothing breaks.
"""
import os
import sqlite3


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
        if 'is_active' in cols:
            print('  [skip] users.is_active already exists')
        else:
            c.execute('ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1')
            print('  [ok] Added users.is_active (default 1 for existing users)')

        conn.commit()
        print('Migration 035 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
