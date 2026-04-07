#!/usr/bin/env python3
"""Migration 036: Add last_active_at to household_members."""
import os, sqlite3

def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(household_members)')]
        if 'last_active_at' in cols:
            print('  [skip] household_members.last_active_at already exists')
        else:
            c.execute('ALTER TABLE household_members ADD COLUMN last_active_at DATETIME')
            print('  [ok] Added household_members.last_active_at')
        conn.commit()
        print('Migration 036 complete.')
    except Exception as e:
        conn.rollback(); print(f'Error: {e}'); raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
