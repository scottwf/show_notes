"""
Migration 043: Upgrade AI summary storage to unified show_summaries schema.

This replaces the legacy split tables:
- show_summaries (tmdb_id/show_title/llm_provider/llm_model)
- season_summaries

With a single table:
- show_summaries (show_id, season_number, episode_number, provider, model, ...)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(cursor, table_name):
    if not _table_exists(cursor, table_name):
        return set()
    return {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def upgrade(db_path=None):
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')

    print(f"Running migration 043 on: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    existing_columns = _column_names(cursor, 'show_summaries')
    already_upgraded = {'show_id', 'season_number', 'episode_number', 'provider', 'model'}.issubset(existing_columns)

    if already_upgraded:
        print("  Unified show_summaries schema already present")
    else:
        if _table_exists(cursor, 'show_summaries'):
            cursor.execute("ALTER TABLE show_summaries RENAME TO show_summaries_legacy")
            print("  Renamed legacy show_summaries to show_summaries_legacy")

        cursor.execute("""
            CREATE TABLE show_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id INTEGER NOT NULL,
                season_number INTEGER,
                episode_number INTEGER,
                summary_text TEXT,
                raw_llm_response TEXT,
                provider TEXT,
                model TEXT,
                prompt_key TEXT,
                prompt_text TEXT,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                api_usage_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (show_id) REFERENCES sonarr_shows(id) ON DELETE CASCADE,
                FOREIGN KEY (api_usage_id) REFERENCES api_usage(id) ON DELETE SET NULL
            )
        """)
        print("  Created unified show_summaries table")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_show_summaries_show ON show_summaries(show_id)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_show_summaries_lookup ON show_summaries(show_id, season_number, episode_number)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_show_summaries_status ON show_summaries(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_show_summaries_api_usage ON show_summaries(api_usage_id)")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_show_summaries_identity
        ON show_summaries(
            show_id,
            COALESCE(season_number, -1),
            COALESCE(episode_number, -1),
            COALESCE(provider, ''),
            COALESCE(model, '')
        )
    """)

    if _table_exists(cursor, 'show_summaries_legacy'):
        cursor.execute("""
            INSERT INTO show_summaries (
                show_id, season_number, episode_number, summary_text, raw_llm_response,
                provider, model, prompt_text, status, error_message, created_at, updated_at
            )
            SELECT
                s.id,
                NULL,
                NULL,
                l.summary_text,
                l.raw_llm_response,
                l.llm_provider,
                l.llm_model,
                l.prompt_text,
                l.status,
                l.error_message,
                l.created_at,
                l.updated_at
            FROM show_summaries_legacy l
            JOIN sonarr_shows s ON s.tmdb_id = l.tmdb_id
        """)
        print("  Migrated legacy show-level summaries")
        cursor.execute("DROP TABLE show_summaries_legacy")
        print("  Dropped show_summaries_legacy")

    season_columns = _column_names(cursor, 'season_summaries')
    if {'tmdb_id', 'season_number', 'llm_provider', 'llm_model'}.issubset(season_columns):
        cursor.execute("""
            INSERT INTO show_summaries (
                show_id, season_number, episode_number, summary_text, raw_llm_response,
                provider, model, prompt_text, status, error_message, created_at, updated_at
            )
            SELECT
                s.id,
                ss.season_number,
                NULL,
                ss.summary_text,
                ss.raw_llm_response,
                ss.llm_provider,
                ss.llm_model,
                ss.prompt_text,
                ss.status,
                ss.error_message,
                ss.created_at,
                ss.updated_at
            FROM season_summaries ss
            JOIN sonarr_shows s ON s.tmdb_id = ss.tmdb_id
        """)
        print("  Migrated legacy season summaries")
        cursor.execute("DROP TABLE season_summaries")
        print("  Dropped season_summaries")

    conn.commit()
    conn.close()
    print("Migration 043 completed successfully.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        upgrade(sys.argv[1])
    else:
        upgrade()
