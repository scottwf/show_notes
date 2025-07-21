"""
Migration: Add LLM summary columns to episode_characters
"""
import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def upgrade(conn):
    cursor = conn.cursor()
    table_name = 'episode_characters'
    columns_to_add = [
        ('llm_relationships', 'TEXT'),
        ('llm_motivations', 'TEXT'),
        ('llm_quote', 'TEXT'),
        ('llm_traits', 'TEXT'),
        ('llm_events', 'TEXT'),
        ('llm_importance', 'TEXT'),
        ('llm_raw_response', 'TEXT'),
        ('llm_last_updated', 'DATETIME'),
        ('llm_source', 'TEXT')
    ]

    for column, col_type in columns_to_add:
        if not column_exists(cursor, table_name, column):
            cursor.execute(f"""
                ALTER TABLE {table_name} ADD COLUMN {column} {col_type};
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