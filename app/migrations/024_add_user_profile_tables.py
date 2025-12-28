"""
Migration: Add User Profile Tables and Columns

This migration adds:
1. user_favorites table - Track favorited shows
2. user_preferences table - Store user display and notification preferences
3. Additional columns to users table (last_login_at, created_at)
"""

def upgrade(cursor, conn):
    """Add user profile tables and columns"""
    
    # Add columns to users table
    cursor.execute("""
        ALTER TABLE users ADD COLUMN last_login_at DATETIME
    """)
    
    cursor.execute("""
        ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    """)
    
    # Create user_favorites table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_dropped BOOLEAN DEFAULT 0,
            dropped_at DATETIME,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE (user_id, show_id)
        )
    """)
    
    # Create indexes for user_favorites
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_favorites_user_id 
        ON user_favorites(user_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_favorites_show_id 
        ON user_favorites(show_id)
    """)
    
    # Create user_preferences table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            default_view TEXT DEFAULT 'grid',
            episodes_per_page INTEGER DEFAULT 20,
            spoiler_protection TEXT DEFAULT 'partial',
            notification_digest TEXT DEFAULT 'immediate',
            quiet_hours_start TEXT,
            quiet_hours_end TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    print("✅ Added user profile tables and columns")

def downgrade(cursor, conn):
    """Remove user profile tables and columns"""
    
    # Note: SQLite doesn't support DROP COLUMN, so we can't easily remove columns
    # We'll just drop the new tables
    cursor.execute('DROP TABLE IF EXISTS user_favorites')
    cursor.execute('DROP TABLE IF EXISTS user_preferences')
    cursor.execute('DROP INDEX IF EXISTS idx_user_favorites_user_id')
    cursor.execute('DROP INDEX IF EXISTS idx_user_favorites_show_id')
    
    conn.commit()
    print("✅ Removed user profile tables")

if __name__ == '__main__':
    import sqlite3
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python 024_add_user_profile_tables.py <path_to_db>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        upgrade(cursor, conn)
        print(f"Migration applied successfully to {db_path}")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()
