#!/usr/bin/env python3
"""
Migration 033: Create recommendation_shares and fix any other missing
schema items that exist in init_db but were never added via migration.
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
        existing = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        # ── recommendation_shares ─────────────────────────────────────────────
        if 'recommendation_shares' in existing:
            print('  [skip] recommendation_shares already exists')
        else:
            c.execute('''
                CREATE TABLE recommendation_shares (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    to_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    media_type   TEXT NOT NULL,
                    media_id     INTEGER NOT NULL,
                    title        TEXT,
                    note         TEXT,
                    is_read      BOOLEAN DEFAULT 0,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_rec_shares_to   ON recommendation_shares(to_user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_rec_shares_from ON recommendation_shares(from_user_id)')
            print('  [ok] Created recommendation_shares')

        # ── users columns that may be missing on old installs ─────────────────
        user_cols = {r[1] for r in c.execute('PRAGMA table_info(users)').fetchall()}
        for col, defn in [
            ('allow_recommendations', 'BOOLEAN DEFAULT 1'),
            ('bio',                   'TEXT'),
            ('profile_show_progress', 'BOOLEAN DEFAULT 1'),
        ]:
            if col in user_cols:
                print(f'  [skip] users.{col} already exists')
            else:
                c.execute(f'ALTER TABLE users ADD COLUMN {col} {defn}')
                print(f'  [ok] Added users.{col}')

        conn.commit()
        print('Migration 033 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
