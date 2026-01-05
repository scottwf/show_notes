"""
Migration: Add Notifications Table

This migration adds:
1. user_notifications table - Track notifications for favorited shows
"""

def upgrade(cursor, conn):
    """Add user notifications table"""

    # Create user_notifications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            notification_type VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            episode_id INTEGER,
            season_number INTEGER,
            episode_number INTEGER,
            is_read BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            read_at DATETIME,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE CASCADE
        )
    """)

    # Create indexes for user_notifications
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_notifications_user_id
        ON user_notifications(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_notifications_show_id
        ON user_notifications(show_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_notifications_is_read
        ON user_notifications(is_read)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_notifications_created_at
        ON user_notifications(created_at DESC)
    """)

    conn.commit()
    print("✅ Migration 025: Added user_notifications table")


if __name__ == '__main__':
    import sqlite3
    import os

    # Get the database path from environment or use default
    db_path = os.environ.get('DATABASE_PATH', 'instance/shownotes.sqlite3')

    print(f"Running migration on database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        upgrade(cursor, conn)
        print("Migration completed successfully!")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
