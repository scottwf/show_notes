#!/usr/bin/env python3
"""
Migration 030: Add sonarr episodes/seasons indexes for homepage premieres

Fixes homepage_premieres cold-cache load: was 70+ seconds due to full scan
of 72K episodes. After index: 0.3ms.
"""
import os, sqlite3


def upgrade():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    indexes = [
        ('idx_sonarr_episodes_ep_airdate',
         'CREATE INDEX idx_sonarr_episodes_ep_airdate ON sonarr_episodes(episode_number, air_date_utc)'),
        ('idx_sonarr_seasons_number',
         'CREATE INDEX idx_sonarr_seasons_number ON sonarr_seasons(season_number)'),
    ]
    try:
        for name, sql in indexes:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,))
            if cursor.fetchone():
                print(f'  [skip] {name} already exists')
            else:
                cursor.execute(sql)
                print(f'  [ok] Created {name}')
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
