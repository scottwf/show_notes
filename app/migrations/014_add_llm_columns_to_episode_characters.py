"""
Migration: Add LLM summary columns to episode_characters
"""
import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_relationships TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_motivations TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_quote TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_traits TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_events TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_importance TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_raw_response TEXT;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_last_updated DATETIME;
    """)
    conn.execute("""
        ALTER TABLE episode_characters ADD COLUMN llm_source TEXT;
    """)
    conn.commit()

def downgrade(conn):
    # SQLite does not support DROP COLUMN directly; would require table rebuild.
    pass

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    try:
        upgrade(conn)
    finally:
        conn.close() 