"""
Migration 025: Add recommendation sharing feature

This migration adds:
1. recommendation_shares table for user-to-user recommendations
2. allow_recommendations column on users table for privacy control
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)


def upgrade(db_path: str) -> bool:
    """
    Apply the migration to add recommendation sharing support.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        True if migration succeeded, False otherwise
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create recommendation_shares table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recommendation_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                media_id INTEGER NOT NULL,
                title TEXT,
                note TEXT,
                is_read BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (to_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        logger.info("Created recommendation_shares table")

        # Create indexes for recommendation_shares
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_rec_shares_to
            ON recommendation_shares(to_user_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_rec_shares_from
            ON recommendation_shares(from_user_id)
        ''')
        logger.info("Created indexes for recommendation_shares")

        # Add allow_recommendations column to users table
        try:
            cursor.execute('''
                ALTER TABLE users ADD COLUMN allow_recommendations BOOLEAN DEFAULT 1
            ''')
            logger.info("Added allow_recommendations column to users table")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                logger.info("allow_recommendations column already exists")
            else:
                raise

        conn.commit()
        logger.info("Migration 025 completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration 025 failed: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if conn:
            conn.close()


def downgrade(db_path: str) -> bool:
    """
    Rollback the migration.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        True if rollback succeeded, False otherwise
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Drop the recommendation_shares table
        cursor.execute('DROP TABLE IF EXISTS recommendation_shares')

        # Note: SQLite doesn't support DROP COLUMN easily
        # The allow_recommendations column will remain but be unused

        conn.commit()
        logger.info("Migration 025 rollback completed")
        return True

    except Exception as e:
        logger.error(f"Migration 025 rollback failed: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    import sys
    import os

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Default database path
    db_path = os.environ.get('DATABASE_PATH', 'data/shownotes.db')

    if len(sys.argv) > 1:
        if sys.argv[1] == 'down':
            success = downgrade(db_path)
        else:
            db_path = sys.argv[1]
            success = upgrade(db_path)
    else:
        success = upgrade(db_path)

    sys.exit(0 if success else 1)
