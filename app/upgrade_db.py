import sqlite3
import os

DB_PATH = os.environ.get('SHOWNOTES_DB', 'instance/shownotes.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS plex_events (
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
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS sonarr_shows (
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
    poster_url TEXT,
    fanart_url TEXT,
    path_on_disk TEXT,
    has_file BOOLEAN,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
'''

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        print('Database schema upgraded successfully (plex_events, sonarr_shows, sonarr_seasons, sonarr_episodes, radarr_movies tables checked/created).')
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
