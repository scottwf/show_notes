import sqlite3
import sys

def create_api_usage_table(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        provider TEXT,
        endpoint TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        cost_usd REAL
    );
    """)
    conn.commit()
    conn.close()
    print("api_usage table created or already exists.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python 20250621_create_api_usage_table.py /path/to/your/database.db")
    else:
        create_api_usage_table(sys.argv[1])
