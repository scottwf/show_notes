import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            level TEXT NOT NULL,
            component TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            user_id INTEGER,
            ip_address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✓ Created system_logs table")

    # Indexes for efficient querying
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp
        ON system_logs(timestamp DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_system_logs_level
        ON system_logs(level)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_system_logs_component
        ON system_logs(component)
    """)
    print("✓ Created indexes")

    conn.commit()
    conn.close()
    print("\n✅ Migration 032 completed successfully")

if __name__ == '__main__':
    print("Running migration: 032_create_system_logs_table.py")
    upgrade()
