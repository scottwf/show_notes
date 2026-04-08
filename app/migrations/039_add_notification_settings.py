#!/usr/bin/env python3
"""
Migration 039: Add ntfy settings and notification trigger flags to settings table.
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
        cols = {r[1] for r in c.execute('PRAGMA table_info(settings)')}

        new_cols = [
            ('ntfy_url',                   'TEXT'),
            ('ntfy_topic',                 'TEXT'),
            ('ntfy_token',                 'TEXT'),
            ('notify_on_problem_report',   'BOOLEAN NOT NULL DEFAULT 1'),
            ('notify_on_new_user',         'BOOLEAN NOT NULL DEFAULT 1'),
            ('notify_on_issue_resolved',   'BOOLEAN NOT NULL DEFAULT 0'),
        ]

        for col, defn in new_cols:
            if col in cols:
                print(f'  [skip] settings.{col} already exists')
            else:
                c.execute(f'ALTER TABLE settings ADD COLUMN {col} {defn}')
                print(f'  [ok] Added settings.{col}')

        conn.commit()
        print('Migration 039 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
