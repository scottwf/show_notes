import sqlite3
import os
import sys
import json
import re
from datetime import datetime

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def get_db_connection():
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def clean_html_tags(text):
    """Remove HTML tags from text"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)

def upgrade():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Attempting to connect to database at: {DB_PATH}")

    # Populate show summaries from Sonarr
    print("Populating show summaries from Sonarr...")
    cursor.execute("""
        SELECT s.tmdb_id, s.title, s.overview, s.sonarr_id, s.year, s.status, 
               s.ratings_imdb_value, s.ratings_imdb_votes, s.ratings_tmdb_value, s.ratings_tmdb_votes
        FROM sonarr_shows s
        WHERE s.overview IS NOT NULL AND s.overview != ''
    """)
    
    shows = cursor.fetchall()
    for show in shows:
        clean_overview = clean_html_tags(show['overview'])
        raw_data = {
            'sonarr_id': show['sonarr_id'],
            'title': show['title'],
            'overview': show['overview'],
            'year': show['year'],
            'status': show['status'],
            'ratings': {
                'imdb_value': show['ratings_imdb_value'],
                'imdb_votes': show['ratings_imdb_votes'],
                'tmdb_value': show['ratings_tmdb_value'],
                'tmdb_votes': show['ratings_tmdb_votes']
            }
        }
        
        cursor.execute("""
            INSERT OR REPLACE INTO show_summaries 
            (tmdb_id, show_title, normalized_summary, raw_source_data, source_provider, 
             source_url, confidence_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            show['tmdb_id'], show['title'], clean_overview, json.dumps(raw_data),
            'Sonarr', 'https://sonarr.tv', 1.0, datetime.now(), datetime.now()
        ))
    
    show_count = len(shows)
    print(f"✓ Populated {show_count} show summaries")

    # Populate episode summaries from Sonarr
    print("Populating episode summaries from Sonarr...")
    cursor.execute("""
        SELECT s.tmdb_id, se.season_number, e.episode_number, e.title, e.overview,
               e.sonarr_episode_id, e.sonarr_show_id, e.air_date_utc, e.has_file, e.monitored,
               e.ratings_imdb_value, e.ratings_imdb_votes, e.ratings_tmdb_value, e.ratings_tmdb_votes
        FROM sonarr_episodes e
        JOIN sonarr_seasons se ON e.season_id = se.id
        JOIN sonarr_shows s ON se.show_id = s.id
        WHERE e.overview IS NOT NULL AND e.overview != ''
    """)
    
    episodes = cursor.fetchall()
    for episode in episodes:
        clean_overview = clean_html_tags(episode['overview'])
        raw_data = {
            'sonarr_episode_id': episode['sonarr_episode_id'],
            'sonarr_show_id': episode['sonarr_show_id'],
            'title': episode['title'],
            'overview': episode['overview'],
            'air_date_utc': episode['air_date_utc'],
            'has_file': episode['has_file'],
            'monitored': episode['monitored'],
            'ratings': {
                'imdb_value': episode['ratings_imdb_value'],
                'imdb_votes': episode['ratings_imdb_votes'],
                'tmdb_value': episode['ratings_tmdb_value'],
                'tmdb_votes': episode['ratings_tmdb_votes']
            }
        }
        
        cursor.execute("""
            INSERT OR REPLACE INTO episode_summaries 
            (tmdb_id, season_number, episode_number, episode_title, normalized_summary, 
             raw_source_data, source_provider, source_url, confidence_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode['tmdb_id'], episode['season_number'], episode['episode_number'],
            episode['title'], clean_overview, json.dumps(raw_data),
            'Sonarr', 'https://sonarr.tv', 1.0, datetime.now(), datetime.now()
        ))
    
    episode_count = len(episodes)
    print(f"✓ Populated {episode_count} episode summaries")

    # Create season summaries by aggregating episode data
    print("Creating season summaries from episode data...")
    cursor.execute("""
        SELECT s.tmdb_id, se.season_number, se.sonarr_season_id, se.episode_count, 
               se.episode_file_count, se.statistics,
               GROUP_CONCAT(
                   CASE 
                       WHEN e.title IS NOT NULL AND e.title != '' 
                       THEN 'Episode ' || e.episode_number || ': ' || e.title
                       ELSE 'Episode ' || e.episode_number
                   END, 
                   '; '
               ) as episode_list,
               COUNT(e.id) as actual_episode_count
        FROM sonarr_seasons se
        JOIN sonarr_shows s ON se.show_id = s.id
        LEFT JOIN sonarr_episodes e ON se.id = e.season_id
        GROUP BY s.tmdb_id, se.season_number, se.id
    """)
    
    seasons = cursor.fetchall()
    for season in seasons:
        episode_list = season['episode_list'] or 'No episodes available.'
        summary = f"This season contains {season['actual_episode_count']} episodes. Episodes include: {episode_list}"
        
        raw_data = {
            'sonarr_season_id': season['sonarr_season_id'],
            'season_number': season['season_number'],
            'episode_count': season['episode_count'],
            'episode_file_count': season['episode_file_count'],
            'statistics': season['statistics'],
            'episode_list': episode_list
        }
        
        cursor.execute("""
            INSERT OR REPLACE INTO season_summaries 
            (tmdb_id, season_number, season_title, normalized_summary, raw_source_data, 
             source_provider, source_url, confidence_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            season['tmdb_id'], season['season_number'], f"Season {season['season_number']}",
            summary, json.dumps(raw_data), 'Sonarr', 'https://sonarr.tv', 0.8,
            datetime.now(), datetime.now()
        ))
    
    season_count = len(seasons)
    print(f"✓ Created {season_count} season summaries")

    # Update data sources to mark Sonarr as synced
    cursor.execute("""
        INSERT OR REPLACE INTO data_sources 
        (provider_name, api_endpoint, api_key, rate_limit_per_minute, is_active, last_sync, created_at)
        VALUES ('Sonarr', 'Local Database', NULL, 0, 1, datetime('now'), datetime('now'))
    """)
    print("✓ Updated data sources")

    # Update schema version
    current_schema_version = 0
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER)")
    version_row = cursor.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if version_row:
        current_schema_version = version_row['version']

    if current_schema_version < 21:
        cursor.execute("INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, 21)")
        print("✓ Updated schema version to 21")
    else:
        print(f"Schema version is already {current_schema_version} or higher. Skipping version update.")

    conn.commit()
    conn.close()
    print("✓ Migration completed successfully")

if __name__ == '__main__':
    upgrade()
