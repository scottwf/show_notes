import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext

DATABASE = 'data/shownotes.db' # This will be updated by app.config['DATABASE']

def get_db_connection():
    conn = sqlite3.connect(
        current_app.config['DATABASE'],
        detect_types=sqlite3.PARSE_DECLTYPES
    )
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
    if 'db' not in g:
        g.db = get_db_connection()
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()

    db.executescript("""
        DROP TABLE IF EXISTS character_summaries;
        DROP TABLE IF EXISTS character_chats;
        DROP TABLE IF EXISTS api_usage;
        DROP TABLE IF EXISTS shows;
        DROP TABLE IF EXISTS season_metadata;
        DROP TABLE IF EXISTS top_characters;
        DROP TABLE IF EXISTS current_watch;
        DROP TABLE IF EXISTS webhook_log;
        DROP TABLE IF EXISTS autocomplete_logs;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS settings;
        DROP TABLE IF EXISTS sonarr_shows;
        DROP TABLE IF EXISTS sonarr_seasons;
        DROP TABLE IF EXISTS sonarr_episodes;
        DROP TABLE IF EXISTS radarr_movies;
        DROP TABLE IF EXISTS plex_events; /* <-- ADDED DROP HERE */
        DROP TABLE IF EXISTS service_status;

        CREATE TABLE character_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_name TEXT NOT NULL,
            show_title TEXT NOT NULL,
            season_limit INTEGER,
            episode_limit INTEGER,
            raw_summary TEXT,
            parsed_traits TEXT,
            parsed_events TEXT,
            parsed_relationships TEXT,
            parsed_importance TEXT,
            parsed_quote TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE character_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_name TEXT NOT NULL,
            show_title TEXT NOT NULL,
            user_message TEXT NOT NULL,
            character_reply TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            endpoint TEXT NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            cost_usd REAL
        );

        CREATE TABLE shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            poster_path TEXT,
            backdrop_path TEXT
        );

        CREATE TABLE season_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            name TEXT,
            overview TEXT,
            poster_path TEXT,
            episode_count INTEGER,
            FOREIGN KEY (show_id) REFERENCES shows (id),
            UNIQUE (show_id, season_number)
        );

        CREATE TABLE top_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER NOT NULL,
            character_name TEXT NOT NULL,
            actor_name TEXT,
            episode_count INTEGER,
            FOREIGN KEY (show_id) REFERENCES shows (id)
        );

        CREATE TABLE current_watch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            show_id INTEGER NOT NULL,
            season_number INTEGER,
            episode_number INTEGER,
            last_watched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (show_id) REFERENCES shows (id),
            UNIQUE (user_id, show_id)
        );

        CREATE TABLE webhook_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            payload TEXT NOT NULL,
            processed BOOLEAN DEFAULT 0
        );

        CREATE TABLE autocomplete_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            search_term TEXT NOT NULL,
            selected_item TEXT,
            item_type TEXT -- e.g., 'show', 'character'
        );

        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, -- Ensure local usernames are unique
            password_hash TEXT,
            plex_user_id TEXT UNIQUE, -- Store Plex User ID, ensure it's unique if linking
            plex_username TEXT,     -- Store Plex Username
            plex_token TEXT,        -- This might be the Plex auth token, consider if it needs to be stored long-term
            is_admin INTEGER DEFAULT 0
        );

        CREATE TABLE settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            radarr_url TEXT,
            radarr_api_key TEXT,
            sonarr_url TEXT,
            sonarr_api_key TEXT,
            bazarr_url TEXT,
            bazarr_api_key TEXT,
            ollama_url TEXT,
            pushover_key TEXT,
            pushover_token TEXT,
            plex_client_id TEXT,
            plex_token TEXT,
            webhook_secret TEXT
        );

        CREATE TABLE sonarr_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sonarr_id INTEGER UNIQUE NOT NULL,
            tvdb_id INTEGER,
            imdb_id TEXT,
            title TEXT NOT NULL,
            year INTEGER,
            overview TEXT,
            status TEXT,
            season_count INTEGER,
            episode_count INTEGER,
            episode_file_count INTEGER,
            poster_url TEXT,
            fanart_url TEXT,
            path_on_disk TEXT,
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sonarr_seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER NOT NULL,
            sonarr_season_id INTEGER,
            season_number INTEGER NOT NULL,
            episode_count INTEGER,
            episode_file_count INTEGER,
            statistics TEXT,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id),
            UNIQUE (show_id, season_number)
        );

        CREATE TABLE sonarr_episodes (
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
            FOREIGN KEY (season_id) REFERENCES sonarr_seasons (id)
        );

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
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE plex_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            user_id TEXT,
            user_name TEXT,
            media_type TEXT,
            show_title TEXT,
            episode_title TEXT,
            season TEXT,
            episode TEXT,
            summary TEXT,
            raw_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            processed INTEGER DEFAULT 0
        );

        CREATE TABLE service_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            status TEXT CHECK(status IN ('online', 'degraded', 'offline', 'unknown')) NOT NULL DEFAULT 'unknown',
            last_checked DATETIME,
            response_time INTEGER,
            version TEXT,
            details TEXT
        );

        CREATE INDEX idx_sonarr_shows_sonarr_id ON sonarr_shows (sonarr_id);
        CREATE INDEX idx_sonarr_shows_title ON sonarr_shows (title);
        CREATE INDEX idx_radarr_movies_radarr_id ON radarr_movies (radarr_id);
        CREATE INDEX idx_radarr_movies_title ON radarr_movies (title);
        CREATE INDEX idx_sonarr_seasons_show_id ON sonarr_seasons (show_id);
        CREATE INDEX idx_sonarr_episodes_season_id ON sonarr_episodes (season_id);
    """)
    click.echo('Initialized the database with the correct schema.')

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear the existing data and create new tables."""
    init_db()
    click.echo('Database initialized with the correct schema.')

def get_setting(key):
    db = get_db()
    row = db.execute('SELECT {} FROM settings LIMIT 1'.format(key)).fetchone()
    if row:
        return row[key]
    return None

def set_setting(key, value):
    db = get_db()
    db.execute('UPDATE settings SET {}=?'.format(key), (value,))
    db.commit()

def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
