import sqlite3
import sys

def add_processing_time_column(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Check if the column already exists
    cursor.execute("PRAGMA table_info(api_usage)")
    columns = [row[1] for row in cursor.fetchall()]
    if "processing_time_ms" not in columns:
        cursor.execute("ALTER TABLE api_usage ADD COLUMN processing_time_ms INTEGER")
        print("Added processing_time_ms column to api_usage table.")
    else:
        print("processing_time_ms column already exists.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python 20250621_add_processing_time_to_api_usage.py /path/to/your/database.db")
    else:
        add_processing_time_column(sys.argv[1])
