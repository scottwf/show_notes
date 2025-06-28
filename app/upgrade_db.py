import sqlite3
import os
import importlib
import glob
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

DB_PATH = os.environ.get('SHOWNOTES_DB', 'instance/shownotes.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS plex_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    user_id INTEGER,
    user_name TEXT,
    media_type TEXT,
    show_title TEXT,
    episode_title TEXT,
    season INTEGER,
    episode INTEGER,
    summary TEXT,
    tmdb_id INTEGER, -- Added tmdb_id
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT
);

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
);

CREATE TABLE IF NOT EXISTS sonarr_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL,
    sonarr_season_id INTEGER,
    season_number INTEGER NOT NULL,
    episode_count INTEGER,
    episode_file_count INTEGER,
    monitored BOOLEAN,
    statistics TEXT,
    FOREIGN KEY (show_id) REFERENCES sonarr_shows (id)
);

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
);

CREATE TABLE IF NOT EXISTS radarr_movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    radarr_id INTEGER UNIQUE NOT NULL,
    tmdb_id INTEGER,
    imdb_id TEXT,
    title TEXT NOT NULL,
    year INTEGER,
    overview TEXT,
    status TEXT,
    release_date TEXT,
    original_language TEXT,
    production_countries TEXT,
    studios TEXT,
    runtime INTEGER,
    tmdb_vote_average REAL,
    tmdb_vote_count INTEGER,
    imdb_rating REAL,
    imdb_votes INTEGER,
    poster_url TEXT,
    fanart_url TEXT,
    path_on_disk TEXT,
    has_file BOOLEAN,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS image_cache_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    item_db_id INTEGER NOT NULL,
    image_url TEXT NOT NULL,
    image_kind TEXT NOT NULL,
    target_filename TEXT NOT NULL,
    status TEXT DEFAULT 'pending' NOT NULL, -- pending, processing, completed, failed
    attempts INTEGER DEFAULT 0 NOT NULL,
    last_attempt_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);
'''

def run_all_migrations(conn):
    migration_files = sorted(glob.glob('app/migrations/[0-9][0-9][0-9]_*.py'))
    for path in migration_files:
        modname = 'app.migrations.' + os.path.basename(path)[:-3]
        mod = importlib.import_module(modname)
        if hasattr(mod, 'upgrade'):
            print(f'Running migration: {modname}')
            mod.upgrade(conn)

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        run_all_migrations(conn)
        print('All migrations applied.')
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
