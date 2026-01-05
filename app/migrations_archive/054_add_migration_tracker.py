"""
Migration 054: Add migration tracker table

Creates a table to track which migrations have been applied.
This enables safe upgrades between releases.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Create migration tracker table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_number INTEGER PRIMARY KEY,
                migration_name TEXT NOT NULL,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        print("✓ Created schema_migrations table")

        # Backfill existing migrations (000-053)
        # Mark all as applied since they're already in the database
        existing_migrations = [
            (0, '000_initial_schema'),
            (51, '051_announcement_notifications'),
            (52, '052_add_plex_joined_at'),
            (53, '053_fix_user_recommendations'),
            (54, '054_add_migration_tracker')
        ]

        for num, name in existing_migrations:
            try:
                cur.execute('''
                    INSERT OR IGNORE INTO schema_migrations (migration_number, migration_name, applied_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (num, name))
            except:
                pass  # Ignore if already exists

        conn.commit()
        print("✓ Backfilled existing migrations")

    except sqlite3.OperationalError as e:
        if 'already exists' in str(e).lower():
            print("✓ schema_migrations table already exists")
        else:
            conn.rollback()
            print(f"Error in migration 054: {e}")
            raise
    except Exception as e:
        conn.rollback()
        print(f"Error in migration 054: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
