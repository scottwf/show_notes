import os
import json
import requests
import re
import sqlite3
import time
import threading
import datetime
from datetime import timezone
import urllib.parse
import logging
import markdown as md

from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort, g
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from ... import database
from . import main_bp
from ._shared import (
    get_current_member, get_user_members, set_member_session,
    _get_cached_value, _get_cached_image_path, _get_media_image_url,
    is_onboarding_complete, _get_profile_stats, _get_plex_event_details,
    _calculate_show_completion, MEMBER_AVATAR_COLORS,
)

def _calculate_watch_statistics(user_id, start_date, end_date):
    """
    Calculate watch statistics from plex_activity_log for a date range.

    Note: Only processes 'media.stop' and 'media.scrobble' events from Plex webhooks,
    which have duration_ms in actual milliseconds. Does NOT process 'watched' events
    from Tautulli imports, as those store duration_ms in seconds despite the column name.

    Args:
        user_id: User ID
        start_date: Start date (datetime.date)
        end_date: End date (datetime.date)

    Returns:
        dict: Statistics for each date in the range
    """
    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return {}

    plex_username = user['plex_username']

    # Query activity log for the date range
    stats_by_date = {}
    current_date = start_date

    while current_date <= end_date:
        date_start = datetime.datetime.combine(current_date, datetime.time.min)
        date_end = datetime.datetime.combine(current_date, datetime.time.max)

        # Get all watch events for this date
        events = db.execute('''
            SELECT
                media_type,
                tmdb_id,
                duration_ms,
                view_offset_ms
            FROM plex_activity_log
            WHERE plex_username = ?
                AND event_timestamp >= ?
                AND event_timestamp <= ?
                AND event_type IN ('media.stop', 'media.scrobble')
        ''', (plex_username, date_start, date_end)).fetchall()

        # Calculate stats for this date
        total_watch_time_ms = 0
        episode_count = 0
        movie_count = 0
        unique_shows = set()

        for event in events:
            # Calculate watch time (use view_offset if available, otherwise duration)
            watch_time = event['view_offset_ms'] or event['duration_ms'] or 0
            total_watch_time_ms += watch_time

            if event['media_type'] == 'episode':
                episode_count += 1
                if event['tmdb_id']:
                    # For episodes, tmdb_id is the show's TMDB ID
                    unique_shows.add(event['tmdb_id'])
            elif event['media_type'] == 'movie':
                movie_count += 1

        stats_by_date[current_date.isoformat()] = {
            'total_watch_time_ms': total_watch_time_ms,
            'episode_count': episode_count,
            'movie_count': movie_count,
            'unique_shows_count': len(unique_shows)
        }

        current_date += datetime.timedelta(days=1)

    return stats_by_date


def _update_daily_statistics(user_id, date):
    """
    Update daily watch statistics for a user and date.
    Called by webhook after watch events.

    Args:
        user_id: User ID
        date: Date to update (datetime.date)
    """
    db = database.get_db()

    # Calculate stats for this date
    stats = _calculate_watch_statistics(user_id, date, date)
    if not stats or date.isoformat() not in stats:
        return

    date_stats = stats[date.isoformat()]

    # Insert or update daily statistics
    db.execute('''
        INSERT INTO user_watch_statistics
        (user_id, stat_date, total_watch_time_ms, episode_count, movie_count, unique_shows_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, stat_date) DO UPDATE SET
            total_watch_time_ms = excluded.total_watch_time_ms,
            episode_count = excluded.episode_count,
            movie_count = excluded.movie_count,
            unique_shows_count = excluded.unique_shows_count,
            updated_at = CURRENT_TIMESTAMP
    ''', (
        user_id,
        date.isoformat(),
        date_stats['total_watch_time_ms'],
        date_stats['episode_count'],
        date_stats['movie_count'],
        date_stats['unique_shows_count']
    ))

    db.commit()


def _calculate_current_streak(user_id):
    """
    Calculate the current watch streak for a user.

    Args:
        user_id: User ID

    Returns:
        int: Current streak length in days
    """
    db = database.get_db()

    # Get all dates with watch activity, ordered by date descending
    dates = db.execute('''
        SELECT stat_date
        FROM user_watch_statistics
        WHERE user_id = ?
            AND (episode_count > 0 OR movie_count > 0)
        ORDER BY stat_date DESC
    ''', (user_id,)).fetchall()

    if not dates:
        return 0

    # Check if there's activity today or yesterday
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    most_recent_date = datetime.date.fromisoformat(dates[0]['stat_date'])

    if most_recent_date not in [today, yesterday]:
        # Streak is broken
        return 0

    # Count consecutive days
    streak_length = 1
    expected_date = most_recent_date - datetime.timedelta(days=1)

    for i in range(1, len(dates)):
        current_date = datetime.date.fromisoformat(dates[i]['stat_date'])

        if current_date == expected_date:
            streak_length += 1
            expected_date -= datetime.timedelta(days=1)
        else:
            # Gap found, streak ends
            break

    return streak_length


def _update_watch_streak(user_id):
    """
    Update the watch streak record for a user.

    Args:
        user_id: User ID
    """
    db = database.get_db()

    current_streak = _calculate_current_streak(user_id)

    if current_streak == 0:
        # Mark all streaks as not current
        db.execute('''
            UPDATE user_watch_streaks
            SET is_current = 0
            WHERE user_id = ? AND is_current = 1
        ''', (user_id,))
        db.commit()
        return

    # Get the most recent streak record
    recent_streak = db.execute('''
        SELECT id, streak_length_days, streak_start_date
        FROM user_watch_streaks
        WHERE user_id = ? AND is_current = 1
        ORDER BY streak_end_date DESC
        LIMIT 1
    ''', (user_id,)).fetchone()

    today = datetime.date.today()

    if recent_streak:
        # Update existing streak
        streak_start = datetime.date.fromisoformat(recent_streak['streak_start_date'])

        db.execute('''
            UPDATE user_watch_streaks
            SET streak_end_date = ?,
                streak_length_days = ?
            WHERE id = ?
        ''', (today.isoformat(), current_streak, recent_streak['id']))
    else:
        # Create new streak record
        streak_start = today - datetime.timedelta(days=current_streak - 1)

        db.execute('''
            INSERT INTO user_watch_streaks
            (user_id, streak_start_date, streak_end_date, streak_length_days, is_current)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, streak_start.isoformat(), today.isoformat(), current_streak))

    db.commit()


def _get_genre_distribution(user_id):
    """
    Get genre distribution from watched shows and movies.

    Args:
        user_id: User ID

    Returns:
        list: List of dicts with genre and watch_count
    """
    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return []

    plex_username = user['plex_username']

    # OPTIMIZED: Single query with JOINs instead of N+1 queries
    # Fetch all watched media with genres in one query
    watched_with_genres = db.execute('''
        SELECT
            pal.media_type,
            pal.tmdb_id,
            COUNT(*) as watch_count,
            CASE
                WHEN pal.media_type = 'episode' THEN ss.genres
                WHEN pal.media_type = 'movie' THEN rm.genres
            END as genres
        FROM plex_activity_log pal
        LEFT JOIN sonarr_shows ss ON pal.media_type = 'episode' AND pal.tmdb_id = ss.tmdb_id
        LEFT JOIN radarr_movies rm ON pal.media_type = 'movie' AND pal.tmdb_id = rm.tmdb_id
        WHERE pal.plex_username = ?
            AND pal.event_type IN ('media.stop', 'media.scrobble')
            AND pal.tmdb_id IS NOT NULL
        GROUP BY pal.media_type, pal.tmdb_id
    ''', (plex_username,)).fetchall()

    # Collect genres from the joined results
    genre_counts = {}

    for media in watched_with_genres:
        genres = []
        if media['genres']:
            try:
                genres = json.loads(media['genres']) if isinstance(media['genres'], str) else media['genres']
            except:
                pass

        # Count genres
        for genre in genres:
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + media['watch_count']

    # Convert to list and sort by count
    genre_list = [{'genre': genre, 'count': count} for genre, count in genre_counts.items()]
    genre_list.sort(key=lambda x: x['count'], reverse=True)

    return genre_list


# ============================================================================
# Watch Statistics API Endpoints
# ============================================================================

@main_bp.route('/api/profile/statistics/overview')
@login_required
def api_statistics_overview():
    """Get overview statistics for the current user"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get total watch time and counts (all time)
    total_stats = db.execute('''
        SELECT
            COALESCE(SUM(total_watch_time_ms), 0) as total_watch_time_ms,
            COALESCE(SUM(episode_count), 0) as total_episodes,
            COALESCE(SUM(movie_count), 0) as total_movies
        FROM user_watch_statistics
        WHERE user_id = ?
    ''', (user_id,)).fetchone()

    # Get current streak
    current_streak = _calculate_current_streak(user_id)

    # Shows completed (>= 95% completion)
    completed_shows = db.execute('''
        SELECT COUNT(*) as cnt FROM user_show_progress
        WHERE user_id = ? AND completion_percentage >= 95
    ''', (user_id,)).fetchone()['cnt'] or 0

    # Average weekly watch hours (last 12 weeks)
    weekly_avg = db.execute('''
        SELECT COALESCE(SUM(total_watch_time_ms), 0) / 12.0 / 3600000.0 AS avg_weekly_hours
        FROM user_watch_statistics
        WHERE user_id = ? AND stat_date >= date('now', '-84 days')
    ''', (user_id,)).fetchone()['avg_weekly_hours'] or 0

    # Longest single-day watch
    best_day = db.execute('''
        SELECT stat_date, total_watch_time_ms / 3600000.0 AS hours
        FROM user_watch_statistics
        WHERE user_id = ?
        ORDER BY total_watch_time_ms DESC
        LIMIT 1
    ''', (user_id,)).fetchone()

    total_hours = (total_stats['total_watch_time_ms'] or 0) / (1000 * 60 * 60)

    return jsonify({
        'success': True,
        'total_watch_time_hours': round(total_hours, 1),
        'total_episodes': total_stats['total_episodes'] or 0,
        'total_movies': total_stats['total_movies'] or 0,
        'current_streak_days': current_streak,
        'completed_shows': completed_shows,
        'avg_weekly_hours': round(weekly_avg, 1),
        'best_day_hours': round(best_day['hours'], 1) if best_day else 0,
        'best_day_date': best_day['stat_date'] if best_day else None
    })


@main_bp.route('/api/profile/statistics/watch-time')
@login_required
def api_statistics_watch_time():
    """Get daily watch time data for charts"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Get period parameter (default 30 days)
    period = request.args.get('period', '30')
    try:
        days = int(period)
        if days not in [30, 90, 365]:
            days = 30
    except:
        days = 30

    db = database.get_db()

    # Get daily stats for the period
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days - 1)

    daily_stats = db.execute('''
        SELECT
            stat_date,
            total_watch_time_ms,
            episode_count,
            movie_count
        FROM user_watch_statistics
        WHERE user_id = ?
            AND stat_date >= ?
            AND stat_date <= ?
        ORDER BY stat_date ASC
    ''', (user_id, start_date.isoformat(), end_date.isoformat())).fetchall()

    # Fill in missing dates with zeros
    data = []
    current_date = start_date
    stats_dict = {row['stat_date']: row for row in daily_stats}

    while current_date <= end_date:
        date_str = current_date.isoformat()
        if date_str in stats_dict:
            row = stats_dict[date_str]
            watch_hours = (row['total_watch_time_ms'] or 0) / (1000 * 60 * 60)
            data.append({
                'date': date_str,
                'watch_hours': round(watch_hours, 2),
                'episode_count': row['episode_count'] or 0,
                'movie_count': row['movie_count'] or 0
            })
        else:
            data.append({
                'date': date_str,
                'watch_hours': 0,
                'episode_count': 0,
                'movie_count': 0
            })

        current_date += datetime.timedelta(days=1)

    return jsonify({
        'success': True,
        'data': data
    })


@main_bp.route('/api/profile/statistics/genres')
@login_required
def api_statistics_genres():
    """Get genre distribution for pie chart"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    genres = _get_genre_distribution(user_id)

    return jsonify({
        'success': True,
        'genres': genres[:10]  # Limit to top 10 genres
    })


@main_bp.route('/api/profile/statistics/viewing-patterns')
@login_required
def api_statistics_viewing_patterns():
    """Get viewing patterns by hour and day of week"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return jsonify({'success': True, 'patterns': []})

    plex_username = user['plex_username']

    # Get all watch events
    events = db.execute('''
        SELECT event_timestamp
        FROM plex_activity_log
        WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble')
    ''', (plex_username,)).fetchall()

    # Count by hour and day of week
    hour_counts = [0] * 24
    day_counts = [0] * 7  # 0=Monday, 6=Sunday

    for event in events:
        try:
            # Parse timestamp
            if isinstance(event['event_timestamp'], str):
                timestamp = datetime.datetime.fromisoformat(event['event_timestamp'].replace('Z', '+00:00'))
            else:
                timestamp = event['event_timestamp']

            hour_counts[timestamp.hour] += 1
            day_counts[timestamp.weekday()] += 1
        except:
            pass

    return jsonify({
        'success': True,
        'by_hour': hour_counts,
        'by_day': day_counts
    })


@main_bp.route('/api/profile/statistics/top-shows')
@login_required
def api_statistics_top_shows():
    """Get top watched shows or movies"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Get parameters
    media_type = request.args.get('type', 'show')
    limit = request.args.get('limit', '10')

    try:
        limit = int(limit)
        if limit > 50:
            limit = 50
    except:
        limit = 10

    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return jsonify({'success': True, 'items': []})

    plex_username = user['plex_username']

    if media_type == 'show':
        # Get top shows
        top_items = db.execute('''
            SELECT
                s.id,
                s.tmdb_id,
                s.title,
                COUNT(*) as watch_count,
                SUM(pal.duration_ms) as total_watch_time_ms
            FROM plex_activity_log pal
            JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
            WHERE pal.plex_username = ?
                AND pal.media_type = 'episode'
                AND pal.event_type IN ('media.stop', 'media.scrobble')
            GROUP BY s.id, s.tmdb_id, s.title
            ORDER BY watch_count DESC
            LIMIT ?
        ''', (plex_username, limit)).fetchall()
    else:
        # Get top movies
        top_items = db.execute('''
            SELECT
                m.id,
                m.tmdb_id,
                m.title,
                COUNT(*) as watch_count,
                SUM(pal.duration_ms) as total_watch_time_ms
            FROM plex_activity_log pal
            JOIN radarr_movies m ON pal.tmdb_id = m.tmdb_id
            WHERE pal.plex_username = ?
                AND pal.media_type = 'movie'
                AND pal.event_type IN ('media.stop', 'media.scrobble')
            GROUP BY m.id, m.tmdb_id, m.title
            ORDER BY watch_count DESC
            LIMIT ?
        ''', (plex_username, limit)).fetchall()

    # Format results
    items = []
    for item in top_items:
        total_ms = item['total_watch_time_ms'] or 0
        total_minutes = int(total_ms / (1000 * 60))
        hours = total_minutes // 60
        minutes = total_minutes % 60
        watch_time_formatted = f"{hours}:{minutes:02d}"

        items.append({
            'id': item['id'],
            'tmdb_id': item['tmdb_id'],
            'title': item['title'],
            'watch_count': item['watch_count'],
            'watch_time': watch_time_formatted,
            'media_type': media_type
        })

    return jsonify({
        'success': True,
        'items': items
    })


@main_bp.route('/api/profile/statistics/monthly')
@login_required
def api_statistics_monthly():
    """Get monthly watch summary for bar/area chart"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    rows = db.execute('''
        SELECT
            strftime('%Y-%m', stat_date) AS month,
            ROUND(SUM(total_watch_time_ms) / 3600000.0, 1) AS watch_hours,
            SUM(episode_count) AS episodes,
            SUM(movie_count) AS movies
        FROM user_watch_statistics
        WHERE user_id = ?
          AND stat_date >= date('now', '-24 months')
        GROUP BY month
        ORDER BY month ASC
    ''', (user_id,)).fetchall()

    return jsonify({
        'success': True,
        'data': [dict(r) for r in rows]
    })


@main_bp.route('/profile/statistics')
@login_required
def profile_statistics():
    """Display user watch statistics and viewing trends"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your statistics.', 'error')
        return redirect(url_for('main.login'))

    # Get basic counts for the tab navigation
    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

    return render_template('profile_statistics.html',
                         user=user_dict,
                         **stats,
                         active_tab='statistics')


# ============================================================================
# Custom Lists API Endpoints
# ============================================================================

