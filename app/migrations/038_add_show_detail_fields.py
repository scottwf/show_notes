#!/usr/bin/env python3
"""
Migration 038: Add tagline, original_language, and production_countries to sonarr_shows.

These fields come from the TMDB TV response and enable richer show detail pages.
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

    existing_cols = {r[1] for r in c.execute("PRAGMA table_info(sonarr_shows)").fetchall()}

    added = []
    for col, definition in [
        ('tagline',             'TEXT'),
        ('original_language',   'TEXT'),
        ('production_countries','TEXT'),  # JSON array e.g. ["US", "GB"]
        ('content_rating',      'TEXT'),  # e.g. "TV-MA"
    ]:
        if col not in existing_cols:
            c.execute(f'ALTER TABLE sonarr_shows ADD COLUMN {col} {definition}')
            added.append(col)
            print(f'  [added] sonarr_shows.{col}')
        else:
            print(f'  [skip] sonarr_shows.{col} already exists')

    conn.commit()
    conn.close()
    if added:
        print(f'Migration 038 complete: added {", ".join(added)}')
    else:
        print('Migration 038: nothing to do')


if __name__ == '__main__':
    upgrade()
