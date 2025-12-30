"""
Migration 041: Add watch statistics tables

Creates tables for tracking user watch statistics, genre preferences, and viewing streaks.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 041: Add watch statistics tables")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create user_watch_statistics table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_watch_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stat_date DATE NOT NULL,
            total_watch_time_ms INTEGER DEFAULT 0,
            episode_count INTEGER DEFAULT 0,
            movie_count INTEGER DEFAULT 0,
            unique_shows_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE (user_id, stat_date)
        )
    """)
    print("✓ Created user_watch_statistics table")

    # Create index for user_watch_statistics
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_watch_statistics_user_date
        ON user_watch_statistics(user_id, stat_date DESC)
    """)
    print("✓ Created index idx_user_watch_statistics_user_date")

    # Create user_genre_statistics table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_genre_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            genre TEXT NOT NULL,
            watch_count INTEGER DEFAULT 0,
            total_watch_time_ms INTEGER DEFAULT 0,
            last_watched_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE (user_id, genre)
        )
    """)
    print("✓ Created user_genre_statistics table")

    # Create index for user_genre_statistics
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_genre_statistics_user_id
        ON user_genre_statistics(user_id)
    """)
    print("✓ Created index idx_user_genre_statistics_user_id")

    # Create user_watch_streaks table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_watch_streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            streak_start_date DATE NOT NULL,
            streak_end_date DATE NOT NULL,
            streak_length_days INTEGER NOT NULL,
            is_current BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    print("✓ Created user_watch_streaks table")

    # Create index for user_watch_streaks
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_watch_streaks_user_current
        ON user_watch_streaks(user_id, is_current)
    """)
    print("✓ Created index idx_user_watch_streaks_user_current")

    conn.commit()
    conn.close()

    print("✅ Migration 041 completed successfully")

if __name__ == '__main__':
    upgrade()
