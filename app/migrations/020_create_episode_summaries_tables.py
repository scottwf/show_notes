import sqlite3
import os
import sys

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def get_db_connection():
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None

def upgrade():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Attempting to connect to database at: {DB_PATH}")

    # Create episode_summaries table
    if not table_exists(cursor, 'episode_summaries'):
        print("Creating episode_summaries table...")
        cursor.execute("""
            CREATE TABLE episode_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                episode_title TEXT,
                normalized_summary TEXT,
                raw_source_data TEXT,
                source_provider TEXT NOT NULL,
                source_url TEXT,
                confidence_score REAL DEFAULT 1.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tmdb_id, season_number, episode_number, source_provider)
            )
        """)
        print("✓ Created episode_summaries table")
    else:
        print("episode_summaries table already exists. Skipping.")

    # Create season_summaries table
    if not table_exists(cursor, 'season_summaries'):
        print("Creating season_summaries table...")
        cursor.execute("""
            CREATE TABLE season_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                season_title TEXT,
                normalized_summary TEXT,
                raw_source_data TEXT,
                source_provider TEXT NOT NULL,
                source_url TEXT,
                confidence_score REAL DEFAULT 1.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tmdb_id, season_number, source_provider)
            )
        """)
        print("✓ Created season_summaries table")
    else:
        print("season_summaries table already exists. Skipping.")

    # Create show_summaries table
    if not table_exists(cursor, 'show_summaries'):
        print("Creating show_summaries table...")
        cursor.execute("""
            CREATE TABLE show_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                show_title TEXT,
                normalized_summary TEXT,
                raw_source_data TEXT,
                source_provider TEXT NOT NULL,
                source_url TEXT,
                confidence_score REAL DEFAULT 1.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tmdb_id, source_provider)
            )
        """)
        print("✓ Created show_summaries table")
    else:
        print("show_summaries table already exists. Skipping.")

    # Create data_sources table for tracking API configurations
    if not table_exists(cursor, 'data_sources'):
        print("Creating data_sources table...")
        cursor.execute("""
            CREATE TABLE data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_name TEXT UNIQUE NOT NULL,
                api_endpoint TEXT,
                api_key TEXT,
                rate_limit_per_minute INTEGER DEFAULT 60,
                is_active BOOLEAN DEFAULT 1,
                last_sync DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created data_sources table")
    else:
        print("data_sources table already exists. Skipping.")

    # Insert default data sources
    cursor.execute("SELECT COUNT(*) FROM data_sources")
    if cursor.fetchone()[0] == 0:
        print("Inserting default data sources...")
        default_sources = [
            ('TVMaze', 'https://api.tvmaze.com', None, 60, 1),
            ('TMDB', 'https://api.themoviedb.org/3', None, 40, 1),
            ('Wikipedia', 'https://en.wikipedia.org/api/rest_v1', None, 30, 1)
        ]
        cursor.executemany("""
            INSERT INTO data_sources (provider_name, api_endpoint, api_key, rate_limit_per_minute, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, default_sources)
        print("✓ Inserted default data sources")

    # Create indexes for better performance
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_episode_summaries_tmdb_season_episode ON episode_summaries (tmdb_id, season_number, episode_number)",
        "CREATE INDEX IF NOT EXISTS idx_episode_summaries_source ON episode_summaries (source_provider)",
        "CREATE INDEX IF NOT EXISTS idx_episode_summaries_updated ON episode_summaries (updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_season_summaries_tmdb_season ON season_summaries (tmdb_id, season_number)",
        "CREATE INDEX IF NOT EXISTS idx_season_summaries_source ON season_summaries (source_provider)",
        "CREATE INDEX IF NOT EXISTS idx_show_summaries_tmdb ON show_summaries (tmdb_id)",
        "CREATE INDEX IF NOT EXISTS idx_show_summaries_source ON show_summaries (source_provider)"
    ]

    for index_sql in indexes:
        cursor.execute(index_sql)
    
    print("✓ Created indexes")

    # Update schema version
    current_schema_version = 0
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER)")
    version_row = cursor.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if version_row:
        current_schema_version = version_row['version']

    if current_schema_version < 20:
        cursor.execute("INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, 20)")
        print("✓ Updated schema version to 20")
    else:
        print(f"Schema version is already {current_schema_version} or higher. Skipping version update.")

    conn.commit()
    conn.close()
    print("✓ Migration completed successfully")

if __name__ == '__main__':
    upgrade()
