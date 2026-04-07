#!/usr/bin/env python3
"""
Migration 037: Ensure announcements and user_announcement_views tables exist.

These tables were added to init_db() but never had a dedicated migration,
so existing databases may be missing them.
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

        if 'announcements' in existing:
            print('  [skip] announcements already exists')
        else:
            c.execute('''
                CREATE TABLE announcements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    type TEXT DEFAULT 'info',
                    is_active BOOLEAN DEFAULT 1,
                    start_date DATETIME,
                    end_date DATETIME,
                    created_by INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_announcements_active_dates ON announcements(is_active, start_date, end_date)')
            print('  [ok] Created announcements')

        if 'user_announcement_views' in existing:
            print('  [skip] user_announcement_views already exists')
        else:
            c.execute('''
                CREATE TABLE user_announcement_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    announcement_id INTEGER,
                    viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    dismissed_at DATETIME,
                    UNIQUE(user_id, announcement_id),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (announcement_id) REFERENCES announcements(id)
                )
            ''')
            print('  [ok] Created user_announcement_views')

        conn.commit()
        print('Migration 037 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
