import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(user_notifications)")
    cols = [r[1] for r in cur.fetchall()]

    if 'issue_report_id' not in cols:
        cur.execute("ALTER TABLE user_notifications ADD COLUMN issue_report_id INTEGER")
        print("Added issue_report_id column to user_notifications table.")
    else:
        print("Column issue_report_id already exists in user_notifications table.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Running migration: 027_add_issue_report_id_to_notifications.py")
    upgrade()
    print("Migration 027_add_issue_report_id_to_notifications.py completed.")
