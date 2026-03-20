#!/usr/bin/env python3
"""
Migration 027: Add performance indexes

This migration adds indexes to improve query performance for frequently
accessed columns and common query patterns identified during performance analysis.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance', 'shownotes.sqlite3')

    print(f"Connecting to database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # List of indexes to create: (index_name, table, columns)
    indexes = [
        # Sonarr shows - frequently used in lookups and joins
        ('idx_sonarr_shows_tvdb_id', 'sonarr_shows', 'tvdb_id'),
        ('idx_sonarr_shows_tmdb_id', 'sonarr_shows', 'tmdb_id'),
        ('idx_sonarr_shows_title_lower', 'sonarr_shows', 'LOWER(title)'),

        # Radarr movies - tmdb_id for lookups
        ('idx_radarr_movies_tmdb_id', 'radarr_movies', 'tmdb_id'),
        ('idx_radarr_movies_title', 'radarr_movies', 'title'),
        ('idx_radarr_movies_title_lower', 'radarr_movies', 'LOWER(title)'),

        # Composite index for episode lookups
        ('idx_sonarr_episodes_lookup', 'sonarr_episodes', 'season_id, episode_number'),
        ('idx_sonarr_episodes_show_season_ep', 'sonarr_episodes', 'show_id, season_number, episode_number'),
        ('idx_sonarr_episodes_air_date', 'sonarr_episodes', 'air_date_utc'),

        # Episode characters - composite for efficient lookups
        ('idx_episode_characters_tmdb_lookup', 'episode_characters', 'show_tmdb_id, season_number, episode_number'),
        ('idx_episode_characters_tvdb_lookup', 'episode_characters', 'show_tvdb_id, season_number, episode_number'),
        ('idx_episode_characters_char_lookup', 'episode_characters', 'show_tmdb_id, character_name'),

        # User favorites - commonly filtered
        ('idx_user_favorites_user_dropped', 'user_favorites', 'user_id, is_dropped'),
        ('idx_user_favorites_show', 'user_favorites', 'user_id, show_id'),

        # Plex activity - composite for common queries (dashboard, watch history)
        ('idx_plex_activity_user_event', 'plex_activity_log', 'plex_username, event_type'),
        ('idx_plex_activity_user_event_time', 'plex_activity_log', 'plex_username, event_type, event_timestamp'),
        ('idx_plex_activity_media_type', 'plex_activity_log', 'media_type'),
        ('idx_plex_activity_grandparent', 'plex_activity_log', 'grandparent_rating_key'),
        ('idx_plex_activity_show_title', 'plex_activity_log', 'show_title'),
        # Webhook duplicate detection
        ('idx_plex_activity_session_event', 'plex_activity_log', 'session_key, event_type, rating_key'),

        # User progress tables
        ('idx_user_episode_progress_show', 'user_episode_progress', 'user_id, show_id'),
        ('idx_user_episode_progress_watched', 'user_episode_progress', 'user_id, is_watched'),
        ('idx_user_show_progress_user', 'user_show_progress', 'user_id'),

        # User notifications for quick filtering
        ('idx_user_notifications_user_read', 'user_notifications', 'user_id, is_read'),

        # Show cast for lookups
        ('idx_show_cast_show', 'show_cast', 'show_id'),
        ('idx_show_cast_person', 'show_cast', 'person_id'),
        ('idx_show_cast_tvmaze', 'show_cast', 'show_tvmaze_id'),

        # Sonarr tags for user request matching
        ('idx_sonarr_tags_label', 'sonarr_tags', 'LOWER(label)'),

        # API usage for dashboard aggregates
        ('idx_api_usage_provider', 'api_usage', 'provider'),
        ('idx_api_usage_timestamp', 'api_usage', 'timestamp'),
        ('idx_api_usage_composite', 'api_usage', 'provider, timestamp'),

        # Issue/problem reports
        ('idx_issue_reports_created', 'issue_reports', 'created_at'),
        ('idx_problem_reports_status', 'problem_reports', 'status, created_at DESC'),

        # User queries
        ('idx_users_is_admin', 'users', 'is_admin'),

        # Webhook activity lookups
        ('idx_webhook_activity_service', 'webhook_activity', 'service_name'),
        ('idx_webhook_activity_received', 'webhook_activity', 'received_at'),

        # Announcements
        ('idx_announcements_active', 'announcements', 'is_active, start_date, end_date'),
    ]

    created = 0
    skipped = 0
    failed = 0

    try:
        for index_name, table, columns in indexes:
            # Check if index already exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,))
            if cursor.fetchone():
                print(f"  [skip] {index_name} already exists")
                skipped += 1
                continue

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                print(f"  [skip] Table {table} does not exist")
                skipped += 1
                continue

            try:
                cursor.execute(f"CREATE INDEX {index_name} ON {table}({columns})")
                print(f"  [ok] Created {index_name} on {table}({columns})")
                created += 1
            except sqlite3.OperationalError as e:
                print(f"  [fail] {index_name}: {e}")
                failed += 1

        conn.commit()
        print(f"\nMigration 027 completed: {created} created, {skipped} skipped, {failed} failed")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
