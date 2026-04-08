#!/usr/bin/env python3
"""
Migration 041: Add ical_token to users table for personal calendar feed URLs.
"""
import os
import sqlite3
import secrets


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    try:
        user_cols = {r[1] for r in c.execute('PRAGMA table_info(users)').fetchall()}
        if 'ical_token' in user_cols:
            print('  [skip] users.ical_token already exists')
        else:
            c.execute('ALTER TABLE users ADD COLUMN ical_token TEXT')
            print('  [ok] Added users.ical_token')

        # Generate tokens for existing users who don't have one
        users = c.execute('SELECT id FROM users WHERE ical_token IS NULL').fetchall()
        for (uid,) in users:
            token = secrets.token_urlsafe(32)
            c.execute('UPDATE users SET ical_token = ? WHERE id = ?', (token, uid))
        if users:
            print(f'  [ok] Generated ical_token for {len(users)} existing users')

        conn.commit()
        print('Migration 041 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
