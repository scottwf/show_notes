#!/usr/bin/env python3
"""
Run migration 024: Add User Profile Tables

This script applies the user profile migration within the Flask app context.
"""

import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from app.database import get_db

def run_migration():
    """Run the migration within Flask app context"""
    app = create_app()
    
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        print("Starting migration 024: Add User Profile Tables...")
        
        try:
            # Add columns to users table (use ALTER TABLE for existing columns check)
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
                print("✓ Added last_login_at column to users")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("⚠ last_login_at column already exists, skipping")
                else:
                    raise
            
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN created_at DATETIME")
                print("✓ Added created_at column to users")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("⚠ created_at column already exists, skipping")
                else:
                    raise
            
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
            print("✓ Created user_favorites table")
            
            # Create indexes for user_favorites
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_favorites_user_id 
                ON user_favorites(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_favorites_show_id 
                ON user_favorites(show_id)
            """)
            print("✓ Created indexes for user_favorites")
            
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
            print("✓ Created user_preferences table")
            
            db.commit()
            print("\n✅ Migration 024 completed successfully!")
            return True
            
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            db.rollback()
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
