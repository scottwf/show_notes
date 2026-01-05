import sqlite3
import os
import sys

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_show_preferences (
            user_id INTEGER,
            show_id INTEGER,
            notify_new_episode INTEGER DEFAULT 1,
            notify_season_finale INTEGER DEFAULT 1,
            notify_series_finale INTEGER DEFAULT 1,
            notify_time TEXT DEFAULT 'immediate',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, show_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            show_id INTEGER,
            type TEXT,
            message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            seen INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS issue_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            media_type TEXT,
            media_id INTEGER,
            show_id INTEGER,
            title TEXT,
            issue_type TEXT,
            comment TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open',
            resolved_by_admin_id INTEGER,
            resolved_at DATETIME,
            resolution_notes TEXT
        )
    ''')
    conn.commit()
    print("Added notification and issue report tables.")

if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    upgrade(conn)
    conn.close()
