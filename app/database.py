import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext
import logging

DATABASE = 'data/shownotes.db' # This will be updated by app.config['DATABASE']

# Define the current schema version. Increment this when you make schema changes.
CURRENT_SCHEMA_VERSION = 3 # Started at 1, incremented to 3 for notifications and reports

def get_db_connection():
    db_path = current_app.config['DATABASE']
    logger = current_app.logger if hasattr(current_app, 'logger') and current_app.logger.hasHandlers() else logging.getLogger(__name__)
    if not (hasattr(current_app, 'logger') and current_app.logger.hasHandlers()):
        if not logger.hasHandlers(): # Avoid adding multiple basicConfig handlers
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s - %(name)s')
    logger.debug(f"Attempting to connect to database at: {db_path}")
    conn = sqlite3.connect(
        current_app.config['DATABASE'],
        detect_types=sqlite3.PARSE_DECLTYPES
    )
    conn.row_factory = sqlite3.Row
    logger.debug(f"Successfully connected to database at: {db_path}")
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
    logger = current_app.logger if hasattr(current_app, 'logger') and current_app.logger.hasHandlers() else logging.getLogger(__name__)
    
    # Basic config for logger if it's not the Flask app's logger or has no handlers
    if not (hasattr(current_app, 'logger') and current_app.logger.hasHandlers()):
        if not logger.hasHandlers(): # Avoid adding multiple basicConfig handlers
            logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s - %(name)s')

    logger.info(f"Executing init_db on database: {current_app.config['DATABASE']}. Attempting to drop and recreate all tables.")
    try:
        # Ensure DROP TABLE statements are definitely present for tables being modified
        db.executescript("""
            DROP TABLE IF EXISTS settings;
            DROP TABLE IF EXISTS api_usage;

            -- DROP TABLE IF EXISTS character_summaries;
            -- DROP TABLE IF EXISTS character_chats;
            -- api_usage is dropped above
            -- DROP TABLE IF EXISTS shows;
            -- DROP TABLE IF EXISTS season_metadata;
            -- DROP TABLE IF EXISTS top_characters;
            -- DROP TABLE IF EXISTS current_watch;
            -- DROP TABLE IF EXISTS webhook_log;
            -- DROP TABLE IF EXISTS autocomplete_logs;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS settings;
            DROP TABLE IF EXISTS sonarr_shows;
            DROP TABLE IF EXISTS sonarr_seasons;
            DROP TABLE IF EXISTS sonarr_episodes;
            DROP TABLE IF EXISTS radarr_movies;
            DROP TABLE IF EXISTS plex_events;
            DROP TABLE IF EXISTS plex_activity_log;
            DROP TABLE IF EXISTS image_cache_queue;
            DROP TABLE IF EXISTS service_sync_status;
            DROP TABLE IF EXISTS user_show_preferences;
            DROP TABLE IF EXISTS notifications;
            DROP TABLE IF EXISTS issue_reports;
            DROP TABLE IF EXISTS schema_version;
            DROP TABLE IF EXISTS subtitles;

            -- CREATE TABLE character_summaries ( id INTEGER PRIMARY KEY AUTOINCREMENT, character_name TEXT NOT NULL, show_title TEXT NOT NULL, season_limit INTEGER, episode_limit INTEGER, raw_summary TEXT, parsed_traits TEXT, parsed_events TEXT, parsed_relationships TEXT, parsed_importance TEXT, parsed_quote TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP );
            -- CREATE TABLE character_chats ( id INTEGER PRIMARY KEY AUTOINCREMENT, character_name TEXT NOT NULL, show_title TEXT NOT NULL, user_message TEXT NOT NULL, character_reply TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP );
            CREATE TABLE api_usage ( id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME NOT NULL, endpoint TEXT NOT NULL, provider TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, cost_usd REAL );
            -- CREATE TABLE shows ( id INTEGER PRIMARY KEY AUTOINCREMENT, tmdb_id INTEGER UNIQUE, title TEXT NOT NULL, description TEXT, poster_path TEXT, backdrop_path TEXT );
            -- CREATE TABLE season_metadata ( id INTEGER PRIMARY KEY AUTOINCREMENT, show_id INTEGER NOT NULL, season_number INTEGER NOT NULL, name TEXT, overview TEXT, poster_path TEXT, episode_count INTEGER, FOREIGN KEY (show_id) REFERENCES shows (id), UNIQUE (show_id, season_number) );
            -- CREATE TABLE top_characters ( id INTEGER PRIMARY KEY AUTOINCREMENT, show_id INTEGER NOT NULL, character_name TEXT NOT NULL, actor_name TEXT, episode_count INTEGER, FOREIGN KEY (show_id) REFERENCES shows (id) );
            -- CREATE TABLE current_watch ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, show_id INTEGER NOT NULL, season_number INTEGER, episode_number INTEGER, last_watched_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (show_id) REFERENCES shows (id), UNIQUE (user_id, show_id) );
            -- CREATE TABLE webhook_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, received_at DATETIME DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL, processed BOOLEAN DEFAULT 0 );
            -- CREATE TABLE autocomplete_logs ( id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, search_term TEXT NOT NULL, selected_item TEXT, item_type TEXT );
            CREATE TABLE users ( id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, plex_user_id TEXT UNIQUE, plex_username TEXT, plex_token TEXT, is_admin INTEGER DEFAULT 0 );
            CREATE TABLE settings ( id INTEGER PRIMARY KEY AUTOINCREMENT, radarr_url TEXT, radarr_api_key TEXT, sonarr_url TEXT, sonarr_api_key TEXT, bazarr_url TEXT, bazarr_api_key TEXT, ollama_url TEXT, openai_api_key TEXT, preferred_llm_provider TEXT, pushover_key TEXT, pushover_token TEXT, plex_client_id TEXT, plex_token TEXT, webhook_secret TEXT, tautulli_url TEXT, tautulli_api_key TEXT );
            CREATE TABLE schema_version ( id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL );
            CREATE TABLE IF NOT EXISTS service_sync_status ( id INTEGER PRIMARY KEY AUTOINCREMENT, service_name TEXT UNIQUE NOT NULL, status TEXT NOT NULL, last_successful_sync_at DATETIME, last_attempted_sync_at DATETIME NOT NULL, message TEXT );
            
            CREATE TABLE sonarr_shows (
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
            );

            CREATE TABLE sonarr_seasons ( id INTEGER PRIMARY KEY AUTOINCREMENT, show_id INTEGER NOT NULL, sonarr_season_id INTEGER, season_number INTEGER NOT NULL, episode_count INTEGER, episode_file_count INTEGER, statistics TEXT, FOREIGN KEY (show_id) REFERENCES sonarr_shows (id), UNIQUE (show_id, season_number) );
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
                ratings_imdb_value REAL,
                ratings_imdb_votes INTEGER,
                ratings_tmdb_value REAL,
                ratings_tmdb_votes INTEGER,
                imdb_id TEXT,
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
                last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                rating_value REAL,
                rating_votes INTEGER,
                rating_type TEXT,
                genres TEXT,
                certification TEXT,
                runtime INTEGER
            );

            CREATE TABLE plex_events ( id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, metadata TEXT, processed BOOLEAN DEFAULT 0, client_ip TEXT );
            CREATE TABLE plex_activity_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, plex_username TEXT, player_title TEXT, player_uuid TEXT, session_key TEXT, rating_key TEXT, parent_rating_key TEXT, grandparent_rating_key TEXT, media_type TEXT, title TEXT, show_title TEXT, season_episode TEXT, view_offset_ms INTEGER, duration_ms INTEGER, event_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, tmdb_id INTEGER, raw_payload TEXT );
            
            CREATE TABLE image_cache_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                item_db_id INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                image_kind TEXT NOT NULL,
                target_filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX idx_image_cache_queue_status_attempts ON image_cache_queue (status, attempts);
            CREATE INDEX idx_users_username ON users (username);
            CREATE INDEX idx_users_plex_user_id ON users (plex_user_id);
            -- CREATE INDEX idx_shows_tmdb_id ON shows (tmdb_id);
            -- CREATE INDEX idx_shows_title ON shows (title);
            -- CREATE INDEX idx_season_metadata_show_id_season_number ON season_metadata (show_id, season_number);
            CREATE INDEX idx_sonarr_shows_sonarr_id ON sonarr_shows (sonarr_id);
            CREATE INDEX idx_sonarr_shows_title ON sonarr_shows (title);
            CREATE INDEX idx_radarr_movies_radarr_id ON radarr_movies (radarr_id);

            CREATE TABLE subtitles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_tmdb_id INTEGER NOT NULL, -- To link with sonarr_shows.tmdb_id
                season_number INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                speaker TEXT,
                line TEXT NOT NULL,
                search_blob TEXT NOT NULL, -- For full-text search
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                -- FOREIGN KEY (show_tmdb_id) REFERENCES sonarr_shows (tmdb_id) ON DELETE CASCADE,
                UNIQUE (show_tmdb_id, season_number, episode_number, start_time, line)
            );

            CREATE INDEX idx_subtitles_show_tmdb_id ON subtitles (show_tmdb_id);
            CREATE INDEX idx_subtitles_season_episode ON subtitles (show_tmdb_id, season_number, episode_number);
            CREATE INDEX idx_subtitles_line_search ON subtitles (search_blob);

            CREATE TABLE user_show_preferences (
                user_id INTEGER,
                show_id INTEGER,
                notify_new_episode INTEGER DEFAULT 1,
                notify_season_finale INTEGER DEFAULT 1,
                notify_series_finale INTEGER DEFAULT 1,
                notify_time TEXT DEFAULT 'immediate',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, show_id)
            );

            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                show_id INTEGER,
                type TEXT,
                message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                seen INTEGER DEFAULT 0
            );

            CREATE TABLE issue_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                media_type TEXT,
                media_id INTEGER,
                show_id INTEGER,
                title TEXT,
                issue_type TEXT,
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'open',
                resolved_by_admin_id INTEGER,
                resolved_at DATETIME,
                resolution_notes TEXT
            );
        """)
        # Insert the current schema version into the new table
        db.execute('INSERT INTO schema_version (id, version) VALUES (1, ?)', (CURRENT_SCHEMA_VERSION,))

        # Add indexes for search performance
        logger.info("Creating search indexes for sonarr_shows and radarr_movies...")
        db.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_shows_title_lower ON sonarr_shows(LOWER(title));')
        db.execute('CREATE INDEX IF NOT EXISTS idx_radarr_movies_title_lower ON radarr_movies(LOWER(title));')
        logger.info("Search indexes created.")

        db.commit() # Explicit commit
        logger.info(f"init_db: All tables dropped and recreated successfully. Schema version set to {CURRENT_SCHEMA_VERSION}. Commit executed.")
    except Exception as e:
        logger.error(f"init_db: Failed to execute schema script: {e}", exc_info=True)
        raise

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear the existing data and create new tables."""
    init_db()
    click.echo('Database initialized with the correct schema.')

def get_setting(key):
    db = get_db()
    logger = current_app.logger if hasattr(current_app, 'logger') and current_app.logger.hasHandlers() else logging.getLogger(__name__)
    try:
        row = db.execute('SELECT {} FROM settings LIMIT 1'.format(key)).fetchone()
        if row:
            return row[key]
    except sqlite3.OperationalError as e:
        logger.warning(f"Could not retrieve setting '{key}' (table might not exist or other DB issue): {e}")
    return None

def set_setting(key, value):
    db = get_db()
    logger = current_app.logger if hasattr(current_app, 'logger') and current_app.logger.hasHandlers() else logging.getLogger(__name__)
    try:
        db.execute('UPDATE settings SET {}=?'.format(key), (value,))
        db.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Could not set setting '{key}': {e}", exc_info=True)

def update_sync_status(conn, service_name, status, message=None):
    """Updates the synchronization status for a given service."""
    cursor = conn.cursor()
    now_iso = sqlite3.datetime.datetime.now().isoformat()

    last_successful_sync_at_update = "last_successful_sync_at = ?,"
    params_successful_sync = [now_iso]
    if status != 'success':
        # If not success, we don't update last_successful_sync_at, so we need to fetch its current value or keep it as is.
        # For UPSERT, if the column is not mentioned in ON CONFLICT, it retains its old value or is NULL for new insert.
        # Simpler: only set it on success.
        last_successful_sync_at_update = ""
        params_successful_sync = []

    # Try to update first, then insert if it doesn't exist (UPSERT behavior)
    # SQLite UPSERT (available from 3.24.0+)
    sql = f"""
    INSERT INTO service_sync_status (service_name, status, { 'last_successful_sync_at,' if status == 'success' else '' } last_attempted_sync_at, message)
    VALUES (?, ?, { ' ?,' if status == 'success' else '' } ?, ?)
    ON CONFLICT(service_name) DO UPDATE SET
        status = excluded.status,
        { 'last_successful_sync_at = excluded.last_successful_sync_at,' if status == 'success' else '' }
        last_attempted_sync_at = excluded.last_attempted_sync_at,
        message = excluded.message;
    """
    
    params = [service_name, status]
    if status == 'success':
        params.append(now_iso) # for last_successful_sync_at
    params.extend([now_iso, message])

    try:
        cursor.execute(sql, tuple(params))
        conn.commit()
        logger = current_app.logger if hasattr(current_app, 'logger') else logging.getLogger(__name__)
        logger.info(f"Updated sync status for {service_name}: {status}")
    except sqlite3.Error as e:
        logger = current_app.logger if hasattr(current_app, 'logger') else logging.getLogger(__name__)
        logger.error(f"Failed to update sync status for {service_name}: {e}")
        # Optionally re-raise or handle

def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)