-- Migration: Create table for storing Plex webhook events
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
