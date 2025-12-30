#!/usr/bin/env python3
"""
Create missing core tables

Creates the core media tables that aren't created by migrations but are
needed by the application. These are normally created by init_db() but
that function drops existing tables.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'shownotes.sqlite3')

def main():
    print("\n" + "="*70)
    print(" "*15 + "CREATE MISSING CORE TABLES")
    print("="*70)
    print("")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure users table has local authentication columns
    print("▶️  Checking users table...")
    cur.execute("PRAGMA table_info(users)")
    existing_cols = [row[1] for row in cur.fetchall()]

    if 'username' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
        print("   ✓ Added username column to users table")

    if 'password_hash' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        print("   ✓ Added password_hash column to users table")

    if 'username' in existing_cols and 'password_hash' in existing_cols:
        print("   ✓ Users table already has authentication columns")

    # Create sonarr_shows
    print("▶️  Creating sonarr_shows...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sonarr_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sonarr_id INTEGER UNIQUE NOT NULL,
            tvdb_id INTEGER,
            tmdb_id INTEGER,
            imdb_id TEXT,
            title TEXT NOT NULL,
            year INTEGER,
            overview TEXT,
            status TEXT,
            ended BOOLEAN,
            season_count INTEGER,
            episode_count INTEGER,
            episode_file_count INTEGER,
            poster_url TEXT,
            fanart_url TEXT,
            path_on_disk TEXT,
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ratings_imdb_value REAL,
            ratings_imdb_votes INTEGER,
            ratings_tmdb_value REAL,
            ratings_tmdb_votes INTEGER,
            ratings_metacritic_value REAL,
            metacritic_id TEXT
        )
    """)

    # Create sonarr_seasons
    print("▶️  Creating sonarr_seasons...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sonarr_seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER NOT NULL,
            sonarr_season_id INTEGER,
            season_number INTEGER NOT NULL,
            episode_count INTEGER,
            episode_file_count INTEGER,
            statistics TEXT,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id),
            UNIQUE (show_id, season_number)
        )
    """)

    # Create sonarr_episodes
    print("▶️  Creating sonarr_episodes...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sonarr_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER NOT NULL,
            sonarr_show_id INTEGER NOT NULL,
            sonarr_episode_id INTEGER UNIQUE NOT NULL,
            episode_number INTEGER NOT NULL,
            title TEXT,
            overview TEXT,
            air_date_utc TEXT,
            has_file BOOLEAN,
            monitored BOOLEAN,
            ratings_imdb_value REAL,
            ratings_imdb_votes INTEGER,
            ratings_tmdb_value REAL,
            ratings_tmdb_votes INTEGER,
            imdb_id TEXT,
            FOREIGN KEY (season_id) REFERENCES sonarr_seasons (id)
        )
    """)

    # Create radarr_movies
    print("▶️  Creating radarr_movies...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS radarr_movies (
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
            rating_votes INTEGER,
            rating_type TEXT,
            genres TEXT,
            certification TEXT,
            runtime INTEGER,
            release_date TEXT
        )
    """)

    # Create plex_activity_log
    print("▶️  Creating plex_activity_log...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS plex_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            plex_username TEXT,
            player_title TEXT,
            player_uuid TEXT,
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
    """)

    # Create subtitles
    print("▶️  Creating subtitles...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subtitles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_tmdb_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            speaker TEXT,
            line TEXT NOT NULL,
            search_blob TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (show_tmdb_id, season_number, episode_number, start_time, line)
        )
    """)

    # Create user_favorites
    print("▶️  Creating user_favorites...")
    cur.execute("""
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

    # Create user_preferences
    print("▶️  Creating user_preferences...")
    cur.execute("""
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

    # Create user_notifications
    print("▶️  Creating user_notifications...")
    cur.execute("""
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

    # Create indexes
    print("▶️  Creating indexes...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sonarr_shows_sonarr_id ON sonarr_shows (sonarr_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sonarr_shows_title ON sonarr_shows (title)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sonarr_shows_tmdb_id ON sonarr_shows (tmdb_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_radarr_movies_radarr_id ON radarr_movies (radarr_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_radarr_movies_tmdb_id ON radarr_movies (tmdb_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_show_tmdb_id ON subtitles (show_tmdb_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_season_episode ON subtitles (show_tmdb_id, season_number, episode_number)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_line_search ON subtitles (search_blob)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_favorites_user_id ON user_favorites (user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_favorites_show_id ON user_favorites (show_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_notifications_user_id ON user_notifications (user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_notifications_show_id ON user_notifications (show_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_notifications_is_read ON user_notifications (is_read)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_notifications_created_at ON user_notifications (created_at DESC)")

    conn.commit()
    conn.close()

    print("\n" + "="*70)
    print("✅ All core tables created successfully!")
    print("="*70)
    print("\n📋 Tables created:")
    print("  • sonarr_shows")
    print("  • sonarr_seasons")
    print("  • sonarr_episodes")
    print("  • radarr_movies")
    print("  • plex_activity_log")
    print("  • subtitles")
    print("  • user_favorites")
    print("  • user_preferences")
    print("  • user_notifications")
    print("\n✨ Your database is now ready for onboarding!\n")

if __name__ == '__main__':
    main()
