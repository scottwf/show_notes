import sqlite3

def add_llm_columns(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Add openai_api_key if it doesn't exist
    cursor.execute("PRAGMA table_info(settings)")
    columns = [row[1] for row in cursor.fetchall()]
    if "openai_api_key" not in columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN openai_api_key TEXT")
        print("Added openai_api_key column to settings")
    if "preferred_llm_provider" not in columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN preferred_llm_provider TEXT")
        print("Added preferred_llm_provider column to settings")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python 20250620_add_llm_columns.py /path/to/your/database.db")
    else:
        add_llm_columns(sys.argv[1])
