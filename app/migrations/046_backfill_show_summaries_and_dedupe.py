"""
Migration 046: Backfill unified show_summaries columns and deduplicate rows.

Some production databases have a show_summaries table that predates the
"unified" schema (see app/database.py's init_db() and migration 043) and
is missing columns the current application code expects: raw_llm_response,
prompt_text, status, error_message, api_usage_id, created_at, updated_at.
They can also have duplicate rows for the same (show_id, season_number,
episode_number, provider, model) identity, left over from before the app
enforced one row per identity -- these violate the idx_show_summaries_identity
unique index migration 043 tries to create, so it skips creating it.

This migration:
1. Adds the missing columns if not already present (backfilling
   created_at/updated_at from the legacy generated_at column where it
   exists).
2. Deletes all but the most recently generated row per identity group.
3. Creates the status/api_usage_id/identity indexes (safe now that the
   columns exist and duplicates are gone).

Safe to run on databases that already have the unified schema -- every
step checks current state first and no-ops if there's nothing to do.
"""
import os
import sqlite3


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(cursor, table_name):
    if not _table_exists(cursor, table_name):
        return set()
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(cursor, table, column, col_type, columns):
    if column in columns:
        print(f"  . {table}.{column} already exists")
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    print(f"  + Added {table}.{column}")
    columns.add(column)


def upgrade(db_path=None):
    if db_path is None:
        db_path = os.environ.get(
            'SHOWNOTES_DB',
            os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3'),
        )

    print(f"Running migration 046 on: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if not _table_exists(cursor, 'show_summaries'):
        print("  . show_summaries does not exist, nothing to do")
        conn.close()
        return

    columns = _column_names(cursor, 'show_summaries')
    had_generated_at = 'generated_at' in columns

    print("Backfilling unified columns...")
    _add_column_if_missing(cursor, 'show_summaries', 'raw_llm_response', 'TEXT', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'prompt_text', 'TEXT', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'status', 'TEXT', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'error_message', 'TEXT', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'api_usage_id', 'INTEGER', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'created_at', 'DATETIME', columns)
    _add_column_if_missing(cursor, 'show_summaries', 'updated_at', 'DATETIME', columns)

    # Existing rows have real summary_text already generated -- 'completed'
    # is the accurate status for them, not the 'pending'/'generating' states
    # new rows pass through.
    cursor.execute("UPDATE show_summaries SET status = 'completed' WHERE status IS NULL")
    if had_generated_at:
        cursor.execute("""
            UPDATE show_summaries
            SET created_at = COALESCE(created_at, generated_at),
                updated_at = COALESCE(updated_at, generated_at)
            WHERE generated_at IS NOT NULL
        """)
    cursor.execute("""
        UPDATE show_summaries
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
    """)
    print("  + Backfilled status/created_at/updated_at")

    print("Deduplicating rows...")
    cursor.execute("""
        SELECT COUNT(*) FROM show_summaries
        WHERE id NOT IN (
            SELECT MAX(id) FROM show_summaries
            GROUP BY show_id, COALESCE(season_number, -1), COALESCE(episode_number, -1),
                     COALESCE(provider, ''), COALESCE(model, '')
        )
    """)
    dup_count = cursor.fetchone()[0]
    if dup_count:
        cursor.execute("""
            DELETE FROM show_summaries
            WHERE id NOT IN (
                SELECT MAX(id) FROM show_summaries
                GROUP BY show_id, COALESCE(season_number, -1), COALESCE(episode_number, -1),
                         COALESCE(provider, ''), COALESCE(model, '')
            )
        """)
        print(f"  + Removed {dup_count} duplicate row(s), kept the most recent per identity")
    else:
        print("  . No duplicate rows found")

    print("Creating indexes...")
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
    print("  + Indexes ready")

    conn.commit()
    conn.close()
    print("Migration 046 completed successfully.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        upgrade(sys.argv[1])
    else:
        upgrade()
