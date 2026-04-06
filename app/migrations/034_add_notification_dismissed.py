#!/usr/bin/env python3
"""
Migration 034: Add is_dismissed to user_notifications

Dismissed notifications don't show in the main list or badge count,
but remain accessible in the notifications center dismissed archive.
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
        cols = [r[1] for r in c.execute('PRAGMA table_info(user_notifications)')]
        if 'is_dismissed' in cols:
            print('  [skip] user_notifications.is_dismissed already exists')
        else:
            c.execute('ALTER TABLE user_notifications ADD COLUMN is_dismissed BOOLEAN NOT NULL DEFAULT 0')
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_notifications_dismissed ON user_notifications(user_id, is_dismissed)')
            print('  [ok] Added user_notifications.is_dismissed')

        conn.commit()
        print('Migration 034 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
