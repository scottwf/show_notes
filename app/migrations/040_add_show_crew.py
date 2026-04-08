#!/usr/bin/env python3
"""
Migration 040: Add show_crew table for storing creators and key crew members.

Populated from TVMaze /shows/{id}/crew during enrichment. Used to display
"Created by" and executive producers on the show detail page.
"""
import os
import sqlite3


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    if 'show_crew' in existing:
        print('  [skip] show_crew already exists')
    else:
        c.execute('''
            CREATE TABLE show_crew (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id INTEGER NOT NULL REFERENCES sonarr_shows(id) ON DELETE CASCADE,
                person_name TEXT NOT NULL,
                job TEXT NOT NULL,
                person_image_url TEXT,
                tvmaze_person_id INTEGER,
                sort_order INTEGER DEFAULT 0
            )
        ''')
        c.execute('CREATE INDEX idx_show_crew_show_id ON show_crew(show_id)')
        c.execute('CREATE INDEX idx_show_crew_job ON show_crew(show_id, job)')
        print('  [created] show_crew table')

    conn.commit()
    conn.close()
    print('Migration 040 complete')


if __name__ == '__main__':
    upgrade()
