"""
Migration 028: Add LLM tables and settings for AI-powered season recaps.

Adds:
- processing_time_ms column to api_usage table
- LLM provider settings columns to settings table
- llm_prompts table for editable prompt templates
- show_summaries table for generated episode/season summaries
- Seeds default prompt templates
"""
import sqlite3
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def upgrade(db_path=None):
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')

    print(f"Running migration 028 on: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Add processing_time_ms to api_usage if missing
    try:
        cursor.execute("ALTER TABLE api_usage ADD COLUMN processing_time_ms INTEGER")
        print("  Added processing_time_ms column to api_usage")
    except sqlite3.OperationalError:
        print("  processing_time_ms column already exists on api_usage")

    # 2. Add LLM settings columns to settings table
    llm_columns = [
        ("ollama_url", "TEXT"),
        ("ollama_model_name", "TEXT"),
        ("openai_api_key", "TEXT"),
        ("openai_model_name", "TEXT"),
        ("openrouter_api_key", "TEXT"),
        ("openrouter_model_name", "TEXT"),
        ("preferred_llm_provider", "TEXT"),
    ]
    for col_name, col_type in llm_columns:
        try:
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}")
            print(f"  Added {col_name} column to settings")
        except sqlite3.OperationalError:
            print(f"  {col_name} column already exists on settings")

    # 3. Create llm_prompts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_key TEXT UNIQUE NOT NULL,
            prompt_name TEXT NOT NULL,
            prompt_template TEXT NOT NULL,
            description TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  Created llm_prompts table")

    # 4. Create show_summaries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS show_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER NOT NULL,
            season_number INTEGER,
            episode_number INTEGER,
            summary_text TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            prompt_key TEXT,
            generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows(id) ON DELETE CASCADE
        )
    """)
    print("  Created show_summaries table")

    # 5. Add indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_show_summaries_show ON show_summaries(show_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_show_summaries_lookup ON show_summaries(show_id, season_number, episode_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_prompts_key ON llm_prompts(prompt_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage(provider)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_timestamp ON api_usage(timestamp)")
    print("  Created indexes")

    # 6. Seed default prompts (only if they don't exist)
    default_prompts = [
        {
            "prompt_key": "episode_summary",
            "prompt_name": "Episode Summary",
            "description": "Generates a concise summary for a single episode. Available placeholders: {show_title}, {season_number}, {episode_number}, {episode_title}, {episode_overview}",
            "prompt_template": """Write a concise summary (2-3 paragraphs) of {show_title} Season {season_number}, Episode {episode_number}: "{episode_title}".

Here is the episode description for context: {episode_overview}

Focus on the key plot developments, character moments, and how this episode connects to the larger season arc. Write in past tense as a recap for someone who has already watched the episode. Do not include spoiler warnings."""
        },
        {
            "prompt_key": "season_recap",
            "prompt_name": "Season Recap",
            "description": "Generates a recap for an entire season. Available placeholders: {show_title}, {season_number}, {episode_summaries}",
            "prompt_template": """Write a comprehensive season recap (3-5 paragraphs) for {show_title} Season {season_number}.

Here are summaries of the individual episodes for reference:
{episode_summaries}

Provide an engaging recap that covers the major storylines, character development, and key turning points of the season. Write in past tense as a recap for someone who has already watched the season. End with how the season concludes and any cliffhangers or setups for the next season. Do not include spoiler warnings."""
        },
    ]

    for prompt in default_prompts:
        existing = cursor.execute("SELECT id FROM llm_prompts WHERE prompt_key = ?", (prompt["prompt_key"],)).fetchone()
        if not existing:
            cursor.execute(
                "INSERT INTO llm_prompts (prompt_key, prompt_name, prompt_template, description) VALUES (?, ?, ?, ?)",
                (prompt["prompt_key"], prompt["prompt_name"], prompt["prompt_template"], prompt["description"])
            )
            print(f"  Seeded prompt: {prompt['prompt_key']}")
        else:
            print(f"  Prompt already exists: {prompt['prompt_key']}")

    conn.commit()
    conn.close()
    print("Migration 028 completed successfully.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        upgrade(sys.argv[1])
    else:
        upgrade()
