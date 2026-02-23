"""
Migration 003: Add subtitle-first recap pipeline tables.

Adds:
- episode_recaps  – cached episode summaries from subtitle chunks
- season_recaps   – cached season recaps synthesised from episode recaps

Cache key for episode_recaps:
  (show_tmdb_id, season_number, episode_number,
   spoiler_cutoff_episode, local_model, prompt_version)

Cache key for season_recaps:
  (show_tmdb_id, season_number, spoiler_cutoff_episode,
   local_model, prompt_version, openai_model_version)

spoiler_cutoff_episode and openai_model_version are stored as '' / 0 when
not applicable so that the UNIQUE constraint works with SQLite (NULL != NULL).
"""
import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "instance",
)
DB_PATH = os.environ.get(
    "SHOWNOTES_DB", os.path.join(INSTANCE_FOLDER_PATH, "shownotes.sqlite3")
)


def get_db_connection():
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def upgrade():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Migration 003: Connecting to {DB_PATH}")

    # ── episode_recaps ───────────────────────────────────────────────────────
    print("\nCreating episode_recaps table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode_recaps (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            show_tmdb_id           INTEGER NOT NULL,
            season_number          INTEGER NOT NULL,
            episode_number         INTEGER NOT NULL,
            -- 0 means "no cutoff applied"
            spoiler_cutoff_episode INTEGER NOT NULL DEFAULT 0,
            local_model            TEXT    NOT NULL,
            prompt_version         TEXT    NOT NULL DEFAULT '1',
            status                 TEXT    NOT NULL DEFAULT 'pending',
            summary_text           TEXT,
            raw_chunks_json        TEXT,
            runtime_seconds        REAL,
            error_message          TEXT,
            created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (show_tmdb_id, season_number, episode_number,
                    spoiler_cutoff_episode, local_model, prompt_version)
        )
    """)
    print("  + episode_recaps table ready")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_episode_recaps_show_season "
        "ON episode_recaps(show_tmdb_id, season_number)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_episode_recaps_status "
        "ON episode_recaps(status)"
    )
    print("  + episode_recaps indexes ready")

    # ── season_recaps ────────────────────────────────────────────────────────
    print("\nCreating season_recaps table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS season_recaps (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            show_tmdb_id           INTEGER NOT NULL,
            season_number          INTEGER NOT NULL,
            -- 0 means "no cutoff applied"
            spoiler_cutoff_episode INTEGER NOT NULL DEFAULT 0,
            local_model            TEXT    NOT NULL,
            prompt_version         TEXT    NOT NULL DEFAULT '1',
            -- '' means "no OpenAI polish"
            openai_model_version   TEXT    NOT NULL DEFAULT '',
            status                 TEXT    NOT NULL DEFAULT 'pending',
            recap_text             TEXT,
            openai_polished_text   TEXT,
            openai_cost_usd        REAL,
            runtime_seconds        REAL,
            error_message          TEXT,
            created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (show_tmdb_id, season_number, spoiler_cutoff_episode,
                    local_model, prompt_version, openai_model_version)
        )
    """)
    print("  + season_recaps table ready")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_season_recaps_show_season "
        "ON season_recaps(show_tmdb_id, season_number)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_season_recaps_status "
        "ON season_recaps(status)"
    )
    print("  + season_recaps indexes ready")

    # ── schema version ───────────────────────────────────────────────────────
    try:
        cursor.execute("SELECT version FROM schema_version WHERE id = 1")
        row = cursor.fetchone()
        target_version = 5
        if row:
            current = row["version"]
            if current < target_version:
                cursor.execute(
                    "UPDATE schema_version SET version = ? WHERE id = 1",
                    (target_version,),
                )
                print(f"\nSchema version updated from {current} to {target_version}")
            else:
                print(f"\nSchema version already at {current}")
        else:
            cursor.execute(
                "INSERT INTO schema_version (id, version) VALUES (1, ?)",
                (target_version,),
            )
            print(f"\nSchema version set to {target_version}")
    except sqlite3.OperationalError:
        print("\nschema_version table not found – skipping version update")

    conn.commit()
    conn.close()
    print("\nMigration 003 completed successfully!")


if __name__ == "__main__":
    upgrade()
