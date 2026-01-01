#!/usr/bin/env python3
"""
Migration 055: Create all missing tables and columns for onboarding
This migration ensures all tables needed after onboarding are created.

Created: 2025-12-31
Reason: Onboarding was incomplete, missing many tables/columns causing login failures
"""

import sqlite3
import os

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    """Add all missing tables and columns"""
    cursor = conn.cursor()
    
    print("Creating missing tables...")
    
    # Essential media tables
    tables = {
        'sonarr_episodes': '''
            CREATE TABLE IF NOT EXISTS sonarr_episodes (
                id INTEGER PRIMARY KEY,
                sonarr_episode_id INTEGER UNIQUE,
                show_id INTEGER,
                season_number INTEGER,
                episode_number INTEGER,
                title TEXT,
                overview TEXT,
                air_date TEXT,
                air_date_utc DATETIME,
                runtime INTEGER,
                has_file BOOLEAN DEFAULT 0,
                file_path TEXT,
                FOREIGN KEY (show_id) REFERENCES sonarr_shows(id)
            )
        ''',
        'sonarr_seasons': '''
            CREATE TABLE IF NOT EXISTS sonarr_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sonarr_season_id INTEGER UNIQUE,
                show_id INTEGER,
                season_number INTEGER,
                monitored BOOLEAN DEFAULT 1,
                FOREIGN KEY (show_id) REFERENCES sonarr_shows(id)
            )
        ''',
        'user_favorites': '''
            CREATE TABLE IF NOT EXISTS user_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                media_type TEXT,
                media_id INTEGER,
                show_id INTEGER,
                is_dropped BOOLEAN DEFAULT 0,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_watch_statistics': '''
            CREATE TABLE IF NOT EXISTS user_watch_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                total_time_watched INTEGER DEFAULT 0,
                movies_watched INTEGER DEFAULT 0,
                episodes_watched INTEGER DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_show_progress': '''
            CREATE TABLE IF NOT EXISTS user_show_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                show_id INTEGER,
                last_watched_season INTEGER,
                last_watched_episode INTEGER,
                last_watched_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_episode_progress': '''
            CREATE TABLE IF NOT EXISTS user_episode_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                episode_id INTEGER,
                watched BOOLEAN DEFAULT 0,
                watch_count INTEGER DEFAULT 0,
                last_watched_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_notifications': '''
            CREATE TABLE IF NOT EXISTS user_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                show_id INTEGER,
                movie_id INTEGER,
                notification_type TEXT,
                title TEXT,
                message TEXT,
                episode_id INTEGER,
                season_number INTEGER,
                episode_number INTEGER,
                type TEXT DEFAULT 'info',
                read BOOLEAN DEFAULT 0,
                is_read BOOLEAN DEFAULT 0,
                read_at DATETIME,
                issue_report_id INTEGER,
                service_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_lists': '''
            CREATE TABLE IF NOT EXISTS user_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                description TEXT,
                is_public BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'user_list_items': '''
            CREATE TABLE IF NOT EXISTS user_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER,
                media_type TEXT,
                media_id INTEGER,
                show_id INTEGER,
                movie_id INTEGER,
                notes TEXT,
                sort_order INTEGER,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (list_id) REFERENCES user_lists(id)
            )
        ''',
        'user_announcement_views': '''
            CREATE TABLE IF NOT EXISTS user_announcement_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                announcement_id INTEGER,
                viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (announcement_id) REFERENCES announcements(id)
            )
        ''',
        'user_watch_streaks': '''
            CREATE TABLE IF NOT EXISTS user_watch_streaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                last_watched_date DATE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'show_cast': '''
            CREATE TABLE IF NOT EXISTS show_cast (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id INTEGER,
                show_tvmaze_id INTEGER,
                person_id INTEGER,
                person_name TEXT,
                person_image_url TEXT,
                character_id INTEGER,
                character_name TEXT,
                character_image_url TEXT,
                actor_name TEXT,
                image_url TEXT,
                cast_order INTEGER,
                is_voice BOOLEAN DEFAULT 0,
                tmdb_person_id INTEGER,
                FOREIGN KEY (show_id) REFERENCES sonarr_shows(id)
            )
        ''',
        'episode_characters': '''
            CREATE TABLE IF NOT EXISTS episode_characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id INTEGER,
                character_name TEXT,
                actor_name TEXT,
                FOREIGN KEY (episode_id) REFERENCES sonarr_episodes(id)
            )
        ''',
        'issue_reports': '''
            CREATE TABLE IF NOT EXISTS issue_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                media_type TEXT,
                media_id INTEGER,
                issue_type TEXT,
                description TEXT,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'announcements': '''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT DEFAULT 'info',
                active BOOLEAN DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME
            )
        ''',
        'plex_activity_log': '''
            CREATE TABLE IF NOT EXISTS plex_activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event TEXT,
                event_type TEXT,
                media_type TEXT,
                title TEXT,
                show_title TEXT,
                plex_username TEXT,
                season_episode TEXT,
                view_offset_ms INTEGER,
                duration_ms INTEGER,
                event_timestamp DATETIME,
                grandparent_rating_key TEXT,
                player_title TEXT,
                tmdb_id INTEGER,
                tvdb_id INTEGER,
                season INTEGER,
                episode INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        'user_daily_watch_stats': '''
            CREATE TABLE IF NOT EXISTS user_daily_watch_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stat_date DATE,
                total_watch_time_ms INTEGER DEFAULT 0,
                episode_count INTEGER DEFAULT 0,
                movie_count INTEGER DEFAULT 0,
                unique_shows_count INTEGER DEFAULT 0,
                UNIQUE(user_id, stat_date),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''',
        'webhook_activity': '''
            CREATE TABLE IF NOT EXISTS webhook_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                service_name TEXT,
                event_type TEXT,
                payload TEXT,
                payload_summary TEXT,
                received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        'system_logs': '''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                message TEXT,
                source TEXT,
                component TEXT,
                details TEXT,
                user_id INTEGER,
                ip_address TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        'service_sync_status': '''
            CREATE TABLE IF NOT EXISTS service_sync_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                last_attempted_sync_at DATETIME,
                last_successful_sync_at DATETIME,
                last_sync_status TEXT,
                last_sync_message TEXT,
                items_synced INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''',
    }
    
    for table_name, create_sql in tables.items():
        try:
            cursor.execute(create_sql)
            print(f"  ✅ {table_name}")
        except sqlite3.OperationalError as e:
            print(f"  ⚠️  {table_name}: {e}")
    
    # Add missing columns to existing tables
    print("\nAdding missing columns to settings table...")
    settings_columns = [
        ('radarr_remote_url', 'TEXT'),
        ('sonarr_remote_url', 'TEXT'),
        ('bazarr_remote_url', 'TEXT'),
        ('tautulli_url', 'TEXT'),
        ('tautulli_api_key', 'TEXT'),
        ('plex_url', 'TEXT'),
        ('plex_token', 'TEXT'),
        ('plex_client_id', 'TEXT'),
        ('openai_api_key', 'TEXT'),
        ('openai_model_name', 'TEXT'),
        ('ollama_model_name', 'TEXT'),
        ('timezone', 'TEXT'),
        ('preferred_llm_provider', 'TEXT'),
        ('pushover_key', 'TEXT'),
        ('pushover_token', 'TEXT'),
        ('jellyseer_url', 'TEXT'),
        ('jellyseer_api_key', 'TEXT'),
        ('jellyseer_remote_url', 'TEXT'),
        ('thetvdb_api_key', 'TEXT'),
    ]
    
    for col_name, col_type in settings_columns:
        try:
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ settings.{col_name}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    
    print("\nAdding missing columns to users table...")
    users_columns = [
        ('username', 'TEXT'),
        ('password_hash', 'TEXT'),
        ('email', 'TEXT'),
        ('profile_photo_url', 'TEXT'),
        ('bio', 'TEXT'),
        ('favorite_genres', 'TEXT'),
        ('joined_at', 'DATETIME'),
        ('last_login_at', 'DATETIME'),
        ('profile_show_profile', 'BOOLEAN DEFAULT 1'),
        ('profile_show_lists', 'BOOLEAN DEFAULT 1'),
        ('profile_show_favorites', 'BOOLEAN DEFAULT 1'),
        ('profile_show_stats', 'BOOLEAN DEFAULT 1'),
        ('profile_show_activity', 'BOOLEAN DEFAULT 1'),
        ('profile_show_history', 'BOOLEAN DEFAULT 1'),
        ('profile_show_progress', 'BOOLEAN DEFAULT 1'),
    ]
    
    for col_name, col_type in users_columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ users.{col_name}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    
    print("\nAdding missing columns to user_lists table...")
    try:
        cursor.execute("ALTER TABLE user_lists ADD COLUMN item_count INTEGER DEFAULT 0")
        print("  ✅ user_lists.item_count")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE user_lists ADD COLUMN updated_at DATETIME")
        print("  ✅ user_lists.updated_at")
    except sqlite3.OperationalError:
        pass
    
    print("\nAdding missing columns to user_notifications table...")
    notifications_columns = [
        ('show_id', 'INTEGER'),
        ('movie_id', 'INTEGER'),
    ]
    for col_name, col_type in notifications_columns:
        try:
            cursor.execute(f"ALTER TABLE user_notifications ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ user_notifications.{col_name}")
        except sqlite3.OperationalError:
            pass
    
    print("\nAdding missing columns to media tables...")
    # Add service IDs to media tables
    try:
        cursor.execute("ALTER TABLE sonarr_shows ADD COLUMN sonarr_id INTEGER")
        print("  ✅ sonarr_shows.sonarr_id")
    except sqlite3.OperationalError:
        pass
    
    # Add all columns needed for sonarr sync
    sonarr_columns = [
        ('season_count', 'INTEGER'),
        ('episode_count', 'INTEGER'),
        ('episode_file_count', 'INTEGER'),
        ('poster_url', 'TEXT'),
        ('fanart_url', 'TEXT'),
        ('path_on_disk', 'TEXT'),
        ('ratings_imdb_value', 'REAL'),
        ('ratings_imdb_votes', 'INTEGER'),
        ('ratings_tmdb_value', 'REAL'),
        ('ratings_tmdb_votes', 'INTEGER'),
        ('ratings_metacritic_value', 'INTEGER'),
        ('metacritic_id', 'TEXT'),
        ('last_synced_at', 'DATETIME'),
        ('tvmaze_id', 'INTEGER'),
        ('premiered', 'TEXT'),
        ('ended', 'TEXT'),
        ('tvmaze_summary', 'TEXT'),
        ('genres', 'TEXT'),
        ('network_name', 'TEXT'),
        ('network_country', 'TEXT'),
        ('runtime', 'INTEGER'),
        ('tvmaze_rating', 'REAL'),
        ('tvmaze_enriched_at', 'DATETIME'),
    ]
    for col_name, col_type in sonarr_columns:
        try:
            cursor.execute(f"ALTER TABLE sonarr_shows ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ sonarr_shows.{col_name}")
        except sqlite3.OperationalError:
            pass
    
    try:
        cursor.execute("ALTER TABLE radarr_movies ADD COLUMN radarr_id INTEGER")
        print("  ✅ radarr_movies.radarr_id")
    except sqlite3.OperationalError:
        pass
    
    # Add all columns needed for radarr sync
    radarr_columns = [
        ('poster_url', 'TEXT'),
        ('fanart_url', 'TEXT'),
        ('path_on_disk', 'TEXT'),
        ('ratings_imdb_value', 'REAL'),
        ('ratings_imdb_votes', 'INTEGER'),
        ('ratings_tmdb_value', 'REAL'),
        ('ratings_tmdb_votes', 'INTEGER'),
        ('ratings_metacritic_value', 'INTEGER'),
        ('ratings_rottenTomatoes_value', 'INTEGER'),
        ('ratings_rottenTomatoes_votes', 'INTEGER'),
        ('metacritic_id', 'TEXT'),
        ('last_synced_at', 'DATETIME'),
        ('runtime', 'INTEGER'),
        ('certification', 'TEXT'),
        ('genres', 'TEXT'),
        ('release_date', 'TEXT'),
        ('original_language_name', 'TEXT'),
        ('original_title', 'TEXT'),
        ('studio', 'TEXT'),
        ('popularity', 'REAL'),
    ]
    for col_name, col_type in radarr_columns:
        try:
            cursor.execute(f"ALTER TABLE radarr_movies ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ radarr_movies.{col_name}")
        except sqlite3.OperationalError:
            pass
    
    # Create unique indexes for ON CONFLICT clauses
    print("\nCreating unique indexes for media sync...")
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sonarr_shows_sonarr_id ON sonarr_shows(sonarr_id)")
        print("  ✅ UNIQUE index on sonarr_shows.sonarr_id")
    except sqlite3.OperationalError as e:
        print(f"  ⚠️  sonarr index: {e}")
    
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_radarr_movies_radarr_id ON radarr_movies(radarr_id)")
        print("  ✅ UNIQUE index on radarr_movies.radarr_id")
    except sqlite3.OperationalError as e:
        print(f"  ⚠️  radarr index: {e}")
    
    print("\nAdding missing columns to announcements table...")
    announcements_columns = [
        ('start_date', 'DATETIME'),
        ('end_date', 'DATETIME'),
        ('created_by', 'INTEGER'),
    ]
    for col_name, col_type in announcements_columns:
        try:
            cursor.execute(f"ALTER TABLE announcements ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ announcements.{col_name}")
        except sqlite3.OperationalError:
            pass
    
    print("\nAdding missing columns to plex_activity_log table...")
    try:
        cursor.execute("ALTER TABLE plex_activity_log ADD COLUMN player_uuid TEXT")
        print("  ✅ plex_activity_log.player_uuid")
    except sqlite3.OperationalError:
        pass
    
    print("\nAdding missing columns to user_announcement_views table...")
    try:
        cursor.execute("ALTER TABLE user_announcement_views ADD COLUMN dismissed_at DATETIME")
        print("  ✅ user_announcement_views.dismissed_at")
    except sqlite3.OperationalError:
        pass
    
    print("\nAdding missing columns to sonarr_seasons table...")
    seasons_columns = [
        ('episode_count', 'INTEGER'),
        ('episode_file_count', 'INTEGER'),
    ]
    for col_name, col_type in seasons_columns:
        try:
            cursor.execute(f"ALTER TABLE sonarr_seasons ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ sonarr_seasons.{col_name}")
        except sqlite3.OperationalError:
            pass
    
    print("\nAdding missing columns to show_cast table...")
    try:
        cursor.execute("ALTER TABLE show_cast ADD COLUMN show_tvmaze_id INTEGER")
        print("  ✅ show_cast.show_tvmaze_id")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE show_cast ADD COLUMN person_id INTEGER")
        print("  ✅ show_cast.person_id")
    except sqlite3.OperationalError:
        pass
    
    print("\nAdding statistics column to sonarr_seasons...")
    try:
        cursor.execute("ALTER TABLE sonarr_seasons ADD COLUMN statistics TEXT")
        print("  ✅ sonarr_seasons.statistics")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    print("\n✅ Migration 055 complete!")

if __name__ == '__main__':
    print("Running migration 055: Create all missing onboarding tables")
    conn = sqlite3.connect(DB_PATH)
    upgrade(conn)
    conn.close()
