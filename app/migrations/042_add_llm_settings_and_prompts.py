"""
Migration 042: Add llm_prompts table, summary settings columns, and summary feedback table.

New settings columns:
  - openrouter_api_key, openrouter_model_name (were missing from schema)
  - gemini_api_key, gemini_model_name
  - llm_model_cutoff_date (per-model cutoff for display/disclaimers)
  - summary_length (short/medium/long)
  - summary_only_watched (bool - skip shows no one has watched)
  - summary_show_disclaimer (bool - show cutoff disclaimer)

New tables:
  - llm_prompts: editable prompt templates
  - summary_feedback: user ratings/reports on AI summaries
"""

import sqlite3
import os
import sys

DB_PATH = os.environ.get('DB_PATH', '/app/instance/shownotes.sqlite3')


def run(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def col_exists(table, col):
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info({table})')]
        return col in cols

    def table_exists(name):
        return cur.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()[0] > 0

    # --- settings columns ---
    new_cols = [
        ('openrouter_api_key',     'TEXT'),
        ('openrouter_model_name',  'TEXT'),
        ('gemini_api_key',         'TEXT'),
        ('gemini_model_name',      'TEXT DEFAULT "gemini-2.0-flash"'),
        ('summary_length',         'TEXT DEFAULT "medium"'),
        ('summary_only_watched',   'INTEGER DEFAULT 1'),
        ('summary_show_disclaimer','INTEGER DEFAULT 1'),
    ]
    for col, typedef in new_cols:
        if not col_exists('settings', col):
            cur.execute(f'ALTER TABLE settings ADD COLUMN {col} {typedef}')
            print(f'  [ok] Added settings.{col}')
        else:
            print(f'  [skip] settings.{col} already exists')

    # --- llm_prompts table ---
    if not table_exists('llm_prompts'):
        cur.execute('''
            CREATE TABLE llm_prompts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_key       TEXT    NOT NULL UNIQUE,
                prompt_name      TEXT    NOT NULL,
                description      TEXT,
                prompt_template  TEXT    NOT NULL,
                default_template TEXT    NOT NULL,
                updated_at       TEXT
            )
        ''')
        print('  [ok] Created llm_prompts table')

        defaults = [
            (
                'episode_summary',
                'Episode Summary',
                'Generates a spoiler-aware summary for a single episode.',
                '''You are a TV show assistant writing concise episode summaries for a personal media tracker.

Show: {show_title}
Season {season_number}, Episode {episode_number}: "{episode_title}"
Air date: {air_date}

Write a {length} summary ({"1-2 sentences" if length == "short" else "3-4 sentences" if length == "medium" else "5-6 sentences"}) of this episode. Focus on key plot points. Do not include spoilers for future episodes. Write in present tense.

If the episode aired after your knowledge cutoff date, note that your summary may be incomplete or inaccurate.'''
            ),
            (
                'season_recap',
                'Season Recap',
                'Generates a recap of a full season for returning viewers.',
                '''You are a TV show assistant writing season recaps for a personal media tracker.

Show: {show_title}
Season {season_number} ({episode_count} episodes, aired {year})

Write a {length} recap ({"2-3 sentences" if length == "short" else "4-6 sentences" if length == "medium" else "8-10 sentences"}) of this season. Cover the main story arcs and character development. Write in past tense as a recap for someone who watched it and wants a refresher.

If the season aired after your knowledge cutoff date, note that your recap may be incomplete or inaccurate.'''
            ),
            (
                'show_overview',
                'Show Overview',
                'Generates an engaging overview/pitch for a show.',
                '''You are a TV show assistant writing show descriptions for a personal media tracker.

Show: {show_title}
Genre: {genres}
Network: {network}
Status: {status}

Write a {length} description ({"1-2 sentences" if length == "short" else "3-4 sentences" if length == "medium" else "5-6 sentences"}) of this show that would make someone want to watch it. Write in present tense.

If the show premiered or has had significant developments after your knowledge cutoff date, note that your description may be outdated.'''
            ),
        ]
        for key, name, desc, template in defaults:
            cur.execute('''
                INSERT INTO llm_prompts (prompt_key, prompt_name, description, prompt_template, default_template)
                VALUES (?, ?, ?, ?, ?)
            ''', (key, name, desc, template, template))
        print(f'  [ok] Inserted {len(defaults)} default prompts')
    else:
        print('  [skip] llm_prompts already exists')

    # --- summary_feedback table ---
    if not table_exists('summary_feedback'):
        cur.execute('''
            CREATE TABLE summary_feedback (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                summary_type TEXT    NOT NULL,  -- episode, season, show
                show_id      INTEGER,
                season_number INTEGER,
                episode_id   INTEGER,
                rating       INTEGER,           -- 1=thumbs up, -1=thumbs down, NULL=report only
                report_type  TEXT,              -- inaccurate, outdated, spoilers, other
                notes        TEXT,
                created_at   TEXT DEFAULT (DATETIME('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (show_id) REFERENCES sonarr_shows(id)
            )
        ''')
        print('  [ok] Created summary_feedback table')
    else:
        print('  [skip] summary_feedback already exists')

    conn.commit()
    conn.close()
    print('Migration 042 complete.')


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run(path)
