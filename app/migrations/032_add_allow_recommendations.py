#!/usr/bin/env python3
"""
Migration 032: Add allow_recommendations to users

Column was defined in init_db schema but never added via migration,
so existing installs were missing it and profile saves would fail.
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
        cols = [r[1] for r in c.execute('PRAGMA table_info(users)').fetchall()]
        if 'allow_recommendations' in cols:
            print('  [skip] users.allow_recommendations already exists')
        else:
            c.execute('ALTER TABLE users ADD COLUMN allow_recommendations BOOLEAN DEFAULT 1')
            print('  [ok] Added users.allow_recommendations')
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
