"""
Migration 001: Add scheduler configuration, LLM summary tables, and fix missing settings columns.

Adds:
- Scheduler config columns to settings (configurable sync times)
- LLM summary config columns to settings (knowledge cutoff, quiet hours)
- preferred_llm_provider column (was missing from init_db)
- season_summaries table
- show_summaries table
"""
import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))


def get_db_connection():
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_index_if_columns_exist(cursor, index_name, table, *columns):
    """
    Create an index only if the table/columns still exist.

    Later migrations (e.g. 043) can replace season_summaries/show_summaries
    with a different schema, so this migration may run against a database
    where these columns no longer exist. Skip instead of erroring.
    """
    existing_cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    missing = [c for c in columns if c not in existing_cols]
    if missing:
        print(f"  . Skipped {index_name} ({table}.{missing[0]} does not exist)")
        return
    cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({', '.join(columns)})")
    print(f"  + {index_name} ready")


def add_column_if_missing(cursor, table, column, col_type, default=None):
    """Safely add a column, ignoring if it already exists."""
    default_clause = f" DEFAULT {default}" if default is not None else ""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
        print(f"  + Added {table}.{column}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  . {table}.{column} already exists")
        else:
            raise


def upgrade():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Migration 001: Connecting to {DB_PATH}")

    # --- Settings columns: Scheduler configuration ---
    print("\nAdding scheduler configuration columns...")
    add_column_if_missing(cursor, 'settings', 'schedule_tautulli_hour', 'INTEGER', 3)
    add_column_if_missing(cursor, 'settings', 'schedule_tautulli_minute', 'INTEGER', 0)
    add_column_if_missing(cursor, 'settings', 'schedule_sonarr_day', 'TEXT', "'sun'")
    add_column_if_missing(cursor, 'settings', 'schedule_sonarr_hour', 'INTEGER', 4)
    add_column_if_missing(cursor, 'settings', 'schedule_sonarr_minute', 'INTEGER', 0)
    add_column_if_missing(cursor, 'settings', 'schedule_radarr_day', 'TEXT', "'sun'")
    add_column_if_missing(cursor, 'settings', 'schedule_radarr_hour', 'INTEGER', 5)
    add_column_if_missing(cursor, 'settings', 'schedule_radarr_minute', 'INTEGER', 0)

    # --- Settings columns: LLM summary configuration ---
    print("\nAdding LLM summary configuration columns...")
    add_column_if_missing(cursor, 'settings', 'preferred_llm_provider', 'TEXT')
    add_column_if_missing(cursor, 'settings', 'llm_knowledge_cutoff_date', 'TEXT')
    add_column_if_missing(cursor, 'settings', 'summary_schedule_start_hour', 'INTEGER', 2)
    add_column_if_missing(cursor, 'settings', 'summary_schedule_end_hour', 'INTEGER', 6)
    add_column_if_missing(cursor, 'settings', 'summary_delay_seconds', 'INTEGER', 30)
    add_column_if_missing(cursor, 'settings', 'summary_enabled', 'INTEGER', 0)

    # --- Summary tables ---
    print("\nCreating summary tables...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS season_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER NOT NULL,
            show_title TEXT,
            season_number INTEGER NOT NULL,
            summary_text TEXT,
            raw_llm_response TEXT,
            llm_provider TEXT NOT NULL,
            llm_model TEXT NOT NULL,
            prompt_text TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tmdb_id, season_number, llm_provider, llm_model)
        )
    """)
    print("  + season_summaries table ready")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS show_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER NOT NULL,
            show_title TEXT,
            summary_text TEXT,
            raw_llm_response TEXT,
            llm_provider TEXT NOT NULL,
            llm_model TEXT NOT NULL,
            prompt_text TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tmdb_id, llm_provider, llm_model)
        )
    """)
    print("  + show_summaries table ready")

    # --- Indexes ---
    print("\nCreating indexes...")
    create_index_if_columns_exist(cursor, 'idx_season_summaries_tmdb_season', 'season_summaries', 'tmdb_id', 'season_number')
    create_index_if_columns_exist(cursor, 'idx_season_summaries_status', 'season_summaries', 'status')
    create_index_if_columns_exist(cursor, 'idx_show_summaries_tmdb', 'show_summaries', 'tmdb_id')
    create_index_if_columns_exist(cursor, 'idx_show_summaries_status', 'show_summaries', 'status')

    # --- Update schema version ---
    cursor.execute("SELECT version FROM schema_version WHERE id = 1")
    row = cursor.fetchone()
    if row:
        current = row['version']
        if current < 4:
            cursor.execute("UPDATE schema_version SET version = 4 WHERE id = 1")
            print(f"\nSchema version updated from {current} to 4")
        else:
            print(f"\nSchema version already at {current}")
    else:
        cursor.execute("INSERT INTO schema_version (id, version) VALUES (1, 4)")
        print("\nSchema version set to 4")

    conn.commit()
    conn.close()
    print("\nMigration 001 completed successfully!")


if __name__ == '__main__':
    upgrade()
