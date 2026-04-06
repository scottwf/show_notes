#!/usr/bin/env python3
"""
Migration 031: Household members — multi-profile support per Plex account

Creates household_members table so multiple people sharing one Plex account
can each have their own ShowNotes profile (favorites, lists, notifications,
recommendations). One existing user → one default member, backfilled.

After this migration:
  - household_members.is_default = 1 → the auto-created profile for existing users
  - user_favorites / user_notifications / user_lists / user_recommendations
    all gain a nullable member_id FK — NULL means "belongs to account owner,
    not yet attributed to a member"
"""
import os
import sqlite3


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        # ── 1. Create household_members ──────────────────────────────────────
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='household_members'")
        if c.fetchone():
            print('  [skip] household_members already exists')
        else:
            c.execute('''
                CREATE TABLE household_members (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    avatar_url  TEXT,
                    avatar_color TEXT NOT NULL DEFAULT '#0ea5e9',
                    is_default  BOOLEAN NOT NULL DEFAULT 0,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('CREATE INDEX idx_household_members_user ON household_members(user_id)')
            print('  [ok] Created household_members')

        # ── 2. Add member_id to per-member tables ────────────────────────────
        tables = [
            'user_favorites',
            'user_notifications',
            'user_lists',
            'user_recommendations',
        ]
        for tbl in tables:
            c.execute(f"PRAGMA table_info({tbl})")
            cols = [row[1] for row in c.fetchall()]
            if 'member_id' in cols:
                print(f'  [skip] {tbl}.member_id already exists')
            else:
                c.execute(f'ALTER TABLE {tbl} ADD COLUMN member_id INTEGER REFERENCES household_members(id)')
                print(f'  [ok] Added {tbl}.member_id')

        # ── 3. Create a default member for every existing user ───────────────
        users = c.execute('SELECT id, username, profile_photo_url FROM users').fetchall()
        colors = ['#0ea5e9', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#ec4899']
        for i, user in enumerate(users):
            existing = c.execute(
                'SELECT id FROM household_members WHERE user_id = ? AND is_default = 1',
                (user['id'],)
            ).fetchone()
            if existing:
                print(f'  [skip] default member already exists for user {user["username"]}')
                continue

            color = colors[i % len(colors)]
            c.execute(
                '''INSERT INTO household_members (user_id, display_name, avatar_url, avatar_color, is_default)
                   VALUES (?, ?, ?, ?, 1)''',
                (user['id'], user['username'], user['profile_photo_url'], color)
            )
            member_id = c.lastrowid

            # Backfill existing rows so they belong to the default member
            for tbl in tables:
                c.execute(f'UPDATE {tbl} SET member_id = ? WHERE user_id = ? AND member_id IS NULL',
                          (member_id, user['id']))

            print(f'  [ok] Created default member "{user["username"]}" (id={member_id}) for user {user["id"]}')

        conn.commit()
        print('Migration 031 complete.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
