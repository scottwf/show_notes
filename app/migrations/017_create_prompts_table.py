import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def upgrade(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            prompt TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (prompt_id) REFERENCES prompts (id)
        );
    """)
    conn.commit()

def downgrade(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE prompt_history;")
    cursor.execute("DROP TABLE prompts;")
    conn.commit()

if __name__ == "__main__":
    # This part is for standalone execution, not used by upgrade_db.py
    # You would need to create a connection and pass it to upgrade/downgrade
    print("This script is intended to be run by upgrade_db.py")
