import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext
import logging

# --- Constants ---
DB_VERSION = 3

# --- Database Connection Handling ---
def get_db():
    """Get a database connection from the application context."""
    if 'db' not in g:
        try:
            db_path = current_app.config['DATABASE']
            logging.debug(f"Attempting to connect to database at: {db_path}")
            g.db = sqlite3.connect(
                db_path,
                detect_types=sqlite3.PARSE_DECLTYPES
            )
            g.db.row_factory = sqlite3.Row
            logging.debug(f"Successfully connected to database at: {db_path}")
        except sqlite3.Error as e:
            logging.error(f"Database connection failed: {e}")
            raise
    return g.db

def close_db(e=None):
    """Close the database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

# --- Database Initialization ---
def init_db():
    """Clear existing data and create new tables."""
    db = get_db()
    db_path = current_app.config['DATABASE']
    logging.info(f"Executing init_db on database: {db_path}. Attempting to drop and recreate all tables.")

    try:
        # Combined schema creation script
        schema_script = """
            -- Drop all tables to ensure a clean slate
            DROP TABLE IF EXISTS settings;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS sonarr_shows;
            DROP TABLE IF EXISTS radarr_movies;
            DROP TABLE IF EXISTS plex_events;
            DROP TABLE IF EXISTS plex_activity_log;

            -- Set schema version
            PRAGMA user_version = {version};

            -- Create settings table
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Create users table
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                plex_username TEXT,
                plex_user_id TEXT,
                is_admin INTEGER DEFAULT 0
            );

            -- Create sonarr_shows table
            CREATE TABLE sonarr_shows (
                id INTEGER PRIMARY KEY,
                title TEXT,
                year INTEGER,
                tmdbId INTEGER UNIQUE,
                tvdbId INTEGER,
                status TEXT,
                overview TEXT,
                path TEXT,
                poster TEXT,
                fanart TEXT,
                last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Create radarr_movies table
            CREATE TABLE radarr_movies (
                id INTEGER PRIMARY KEY,
                title TEXT,
                year INTEGER,
                tmdb_id INTEGER UNIQUE,
                imdb_id TEXT,
                status TEXT,
                overview TEXT,
                path_on_disk TEXT,
                poster_url TEXT,
                fanart_url TEXT,
                has_file BOOLEAN,
                monitored BOOLEAN,
                last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Create plex_events table
            CREATE TABLE plex_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                processed BOOLEAN DEFAULT 0,
                client_ip TEXT
            );

            -- Create plex_activity_log table
            CREATE TABLE plex_activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                plex_username TEXT,
                title TEXT,
                grandparent_title TEXT,
                media_type TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                raw_payload TEXT,
                tmdb_id INTEGER
            );
        """.format(version=DB_VERSION)

        db.executescript(schema_script)
        logging.info("Database schema successfully created/updated.")

    except sqlite3.Error as e:
        logging.error(f"init_db: Failed to execute schema script: {e}", exc_info=True)
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred during init_db: {e}", exc_info=True)
        raise


@click.command('init-db')
@with_appcontext
def init_db_command():
    """CLI command to clear the data and create new tables."""
    init_db()
    click.echo('Initialized the database.')

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

# --- Settings Helpers ---
def get_setting(key, default=None):
    """Retrieve a setting from the database."""
    db = get_db()
    setting = db.execute(
        'SELECT value FROM settings WHERE key = ?', (key,)
    ).fetchone()
    return setting['value'] if setting else default

def update_setting(key, value):
    """Update or insert a setting in the database."""
    db = get_db()
    db.execute(
        'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
        (key, value)
    )
    db.commit()

def get_current_schema_version():
    """Get the current schema version from the database."""
    try:
        db = get_db()
        version = db.execute('PRAGMA user_version').fetchone()[0]
        return version
    except (sqlite3.OperationalError, IndexError):
        # This can happen if the DB is new or corrupt
        return None
