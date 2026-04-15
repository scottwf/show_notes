#!/usr/bin/env python3
"""
Migration 044: Add Radarr availability tracking columns for homepage movie widgets.
"""
import os
import sqlite3


def upgrade():
    db_path = os.environ.get('SHOWNOTES_DB') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance', 'shownotes.sqlite3',
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        table_exists = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='radarr_movies'"
        ).fetchone()
        if not table_exists:
            print('  [skip] radarr_movies table does not exist')
            return

        existing_columns = {
            row[1] for row in cursor.execute('PRAGMA table_info(radarr_movies)').fetchall()
        }
        columns_to_add = [
            ('path_on_disk', 'TEXT'),
            ('has_file', 'BOOLEAN'),
            ('monitored', 'BOOLEAN'),
            ('digital_release_date', 'TEXT'),
            ('physical_release_date', 'TEXT'),
            ('in_cinemas_date', 'TEXT'),
            ('availability_date', 'TEXT'),
            ('movie_file_added_date', 'TEXT'),
        ]

        for column_name, column_def in columns_to_add:
            if column_name in existing_columns:
                print(f'  [skip] radarr_movies.{column_name} already exists')
                continue
            cursor.execute(f'ALTER TABLE radarr_movies ADD COLUMN {column_name} {column_def}')
            print(f'  [ok] Added radarr_movies.{column_name}')

        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_radarr_movies_upcoming '
            'ON radarr_movies(has_file, monitored, availability_date)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_radarr_movies_recent_additions '
            'ON radarr_movies(has_file, movie_file_added_date)'
        )

        conn.commit()
        print('Migration 044 complete.')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
