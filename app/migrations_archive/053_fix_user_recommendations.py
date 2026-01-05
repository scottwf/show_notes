"""
Migration 053: Fix user_recommendations table schema

Updates the user_recommendations table to use media_type/media_id pattern
instead of separate show_id/movie_id columns.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Create new table with updated schema
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_recommendations_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                media_id INTEGER NOT NULL,
                title TEXT,
                note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE (user_id, media_type, media_id)
            )
        ''')

        # Migrate existing data from old table if it exists
        cur.execute('''
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='user_recommendations'
        ''')

        if cur.fetchone():
            # Migrate show recommendations
            cur.execute('''
                INSERT INTO user_recommendations_new (user_id, media_type, media_id, note, created_at)
                SELECT user_id, 'show', show_id, recommendation_text, created_at
                FROM user_recommendations
                WHERE show_id IS NOT NULL
            ''')

            # Migrate movie recommendations
            cur.execute('''
                INSERT INTO user_recommendations_new (user_id, media_type, media_id, note, created_at)
                SELECT user_id, 'movie', movie_id, recommendation_text, created_at
                FROM user_recommendations
                WHERE movie_id IS NOT NULL
            ''')

            # Drop old table
            cur.execute('DROP TABLE user_recommendations')

        # Rename new table to proper name
        cur.execute('ALTER TABLE user_recommendations_new RENAME TO user_recommendations')

        conn.commit()
        print("✓ Updated user_recommendations table schema")

    except sqlite3.OperationalError as e:
        if 'already exists' in str(e).lower() or 'no such table' in str(e).lower():
            print("✓ user_recommendations table already updated")
        else:
            conn.rollback()
            print(f"Error in migration 053: {e}")
            raise
    except Exception as e:
        conn.rollback()
        print(f"Error in migration 053: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
