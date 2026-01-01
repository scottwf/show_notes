"""
Migration 056: Remove unused database columns

This migration removes columns that have been identified as unused in the codebase.
See DATABASE_ANALYSIS.md for detailed analysis and justification.

Columns being removed:
1. episode_characters.llm_background (deprecated LLM feature)
2. user_show_preferences.notify_new_episode (incomplete notification feature)
3. user_show_preferences.notify_season_finale (incomplete notification feature)
4. user_show_preferences.notify_series_finale (incomplete notification feature)
5. user_show_preferences.notify_time (incomplete notification feature)
6. users.external_links (incomplete profile feature)
7. users.profile_is_public (incomplete privacy feature)
8. radarr_movies.rating_type (unused rating metadata)
9. radarr_movies.rating_votes (unused rating metadata)
10. plex_activity_log.player_uuid (unused Plex data)
11. webhook_activity.processed (never checked)

Note: image_cache_queue.item_db_id and notifications.seen are kept for now
pending further investigation of their purpose.

SQLite Note: DROP COLUMN requires SQLite 3.35.0+. This script will check
the version and use table recreation if needed.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'instance'
)
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))


def get_sqlite_version(conn):
    """Get SQLite version as tuple of integers"""
    cursor = conn.cursor()
    version_str = cursor.execute("SELECT sqlite_version()").fetchone()[0]
    return tuple(int(x) for x in version_str.split('.'))


def check_table_exists(conn, table_name):
    """Check if a table exists"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def check_column_exists(conn, table_name, column_name):
    """Check if a column exists in a table"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def drop_column_modern(conn, table_name, column_name):
    """Drop column using ALTER TABLE DROP COLUMN (SQLite 3.35.0+)"""
    cursor = conn.cursor()
    cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
    print(f"  ✓ Dropped {table_name}.{column_name} using ALTER TABLE")


def drop_column_legacy(conn, table_name, column_name, table_schemas):
    """
    Drop column by recreating table (for SQLite < 3.35.0)
    
    Args:
        conn: Database connection
        table_name: Name of the table
        column_name: Name of the column to drop
        table_schemas: Dict mapping table names to their new CREATE TABLE statements
    """
    if table_name not in table_schemas:
        print(f"  ⚠️  Skipping {table_name}.{column_name} - no schema provided for legacy method")
        return
    
    cursor = conn.cursor()
    
    # Get current columns
    cursor.execute(f"PRAGMA table_info({table_name})")
    current_columns = [row[1] for row in cursor.fetchall()]
    
    # Remove the column to drop
    if column_name not in current_columns:
        print(f"  ⚠️  Column {table_name}.{column_name} doesn't exist")
        return
    
    remaining_columns = [col for col in current_columns if col != column_name]
    columns_list = ', '.join(remaining_columns)
    
    # Create new table with updated schema
    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old")
    cursor.execute(table_schemas[table_name])
    
    # Copy data
    cursor.execute(f"""
        INSERT INTO {table_name} ({columns_list})
        SELECT {columns_list} FROM {table_name}_old
    """)
    
    # Drop old table
    cursor.execute(f"DROP TABLE {table_name}_old")
    
    print(f"  ✓ Dropped {table_name}.{column_name} using table recreation")


# New table schemas without the unused columns
# Only needed for legacy SQLite versions
TABLE_SCHEMAS_WITHOUT_UNUSED_COLUMNS = {
    'episode_characters': """
        CREATE TABLE IF NOT EXISTS episode_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_tmdb_id INTEGER,
            show_tvdb_id INTEGER,
            season_number INTEGER,
            episode_number INTEGER,
            episode_rating_key TEXT,
            character_name TEXT,
            actor_name TEXT,
            actor_id INTEGER,
            actor_thumb TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """,
    'user_show_preferences': """
        CREATE TABLE user_show_preferences (
            user_id INTEGER,
            show_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, show_id)
        )
    """,
    'users': """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            plex_user_id TEXT UNIQUE,
            plex_username TEXT,
            plex_token TEXT,
            is_admin INTEGER DEFAULT 0,
            last_login_at DATETIME,
            plex_joined_at DATETIME,
            bio TEXT,
            profile_photo_url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """,
    'radarr_movies': """
        CREATE TABLE radarr_movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            radarr_id INTEGER UNIQUE NOT NULL,
            tmdb_id INTEGER,
            imdb_id TEXT,
            title TEXT NOT NULL,
            year INTEGER,
            overview TEXT,
            status TEXT,
            poster_url TEXT,
            fanart_url TEXT,
            path_on_disk TEXT,
            has_file BOOLEAN,
            monitored BOOLEAN,
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            rating_value REAL,
            genres TEXT,
            certification TEXT,
            runtime INTEGER,
            release_date TEXT,
            original_language_name TEXT,
            studio TEXT
        )
    """,
    'plex_activity_log': """
        CREATE TABLE plex_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            plex_username TEXT,
            player_title TEXT,
            session_key TEXT,
            rating_key TEXT,
            parent_rating_key TEXT,
            grandparent_rating_key TEXT,
            media_type TEXT,
            title TEXT,
            show_title TEXT,
            season_episode TEXT,
            view_offset_ms INTEGER,
            duration_ms INTEGER,
            event_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            tmdb_id INTEGER,
            raw_payload TEXT
        )
    """,
    'webhook_activity': """
        CREATE TABLE webhook_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            payload_summary TEXT
        )
    """
}


def upgrade():
    """Remove unused columns from database"""
    print("=" * 80)
    print("Migration 056: Remove unused database columns")
    print("=" * 80)
    print()
    
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        print("Skipping migration (database will be created with clean schema)")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check SQLite version
        sqlite_version = get_sqlite_version(conn)
        print(f"SQLite version: {'.'.join(map(str, sqlite_version))}")
        
        use_modern_drop = sqlite_version >= (3, 35, 0)
        if use_modern_drop:
            print("Using ALTER TABLE DROP COLUMN (modern method)")
        else:
            print("Using table recreation (legacy method for SQLite < 3.35.0)")
        print()
        
        # Define columns to drop
        columns_to_drop = [
            ('episode_characters', 'llm_background'),
            ('user_show_preferences', 'notify_new_episode'),
            ('user_show_preferences', 'notify_season_finale'),
            ('user_show_preferences', 'notify_series_finale'),
            ('user_show_preferences', 'notify_time'),
            ('users', 'external_links'),
            ('users', 'profile_is_public'),
            ('radarr_movies', 'rating_type'),
            ('radarr_movies', 'rating_votes'),
            ('plex_activity_log', 'player_uuid'),
            ('webhook_activity', 'processed'),
        ]
        
        dropped_count = 0
        skipped_count = 0
        
        for table_name, column_name in columns_to_drop:
            # Check if table exists
            if not check_table_exists(conn, table_name):
                print(f"  ⚠️  Table {table_name} doesn't exist, skipping {column_name}")
                skipped_count += 1
                continue
            
            # Check if column exists
            if not check_column_exists(conn, table_name, column_name):
                print(f"  ⚠️  Column {table_name}.{column_name} doesn't exist, already removed")
                skipped_count += 1
                continue
            
            # Drop the column
            try:
                if use_modern_drop:
                    drop_column_modern(conn, table_name, column_name)
                else:
                    drop_column_legacy(conn, table_name, column_name, TABLE_SCHEMAS_WITHOUT_UNUSED_COLUMNS)
                dropped_count += 1
            except sqlite3.Error as e:
                print(f"  ❌ Error dropping {table_name}.{column_name}: {e}")
                skipped_count += 1
        
        conn.commit()
        
        print()
        print("=" * 80)
        print(f"Migration complete: {dropped_count} columns dropped, {skipped_count} skipped")
        print("=" * 80)
        print()
        print("See DATABASE_ANALYSIS.md for detailed rationale")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
