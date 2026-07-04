"""Homepage route extracted from media_routes.py (Task 2 refactor).

Handles the dashboard/landing page: now playing, recent activity,
premieres, and movie sections, with per-section caching.
"""
import time
import datetime
from datetime import timezone

from flask import render_template, redirect, url_for, session, flash
from flask_login import login_required, current_user

from ... import database
from ...data_transforms import format_datetime_simple
from . import main_bp
from ._shared import (
    _get_cached_value, _get_media_image_url, _get_profile_stats,
)

@main_bp.route('/')
@login_required
def home():
    """
    User's profile page (watch history with now playing).

    This is the homepage/landing page displaying currently playing media and watch history.
    """
    route_started_at = time.perf_counter()
    timings = []
    recent_activity_limit = 12
    homepage_premiere_limit = 12
    homepage_movie_limit = 12

    def mark_timing(label, started_at):
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        timings.append((label, elapsed_ms))
        return elapsed_ms

    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    step_started_at = time.perf_counter()
    db = database.get_db()
    mark_timing('db_connection', step_started_at)

    # Get user info
    step_started_at = time.perf_counter()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    mark_timing('load_user', step_started_at)

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get currently playing/paused item from Tautulli (real-time data)
    # Single API call returns both the user's session and total stream count
    from ...utils import get_tautulli_data

    current_plex_event = None
    s_username = user['plex_username'] if user['plex_username'] else user['username']

    step_started_at = time.perf_counter()
    tautulli_session, tautulli_stream_count = get_tautulli_data(username=s_username)
    mark_timing('tautulli_activity', step_started_at)

    if tautulli_session:
        # Convert Tautulli session data to our expected format
        # Safely convert numeric values to int
        parent_index = int(tautulli_session.get('parent_media_index', 0) or 0)
        media_index = int(tautulli_session.get('media_index', 0) or 0)
        view_offset = int(tautulli_session.get('view_offset', 0) or 0)
        duration = int(tautulli_session.get('duration', 0) or 0)
        progress_percent = int(tautulli_session.get('progress_percent', 0) or 0)

        current_plex_event = {
            'title': tautulli_session.get('full_title') or tautulli_session.get('title'),
            'media_type': tautulli_session.get('media_type'),
            'show_title': tautulli_session.get('grandparent_title'),
            'season_episode': f"S{parent_index:02d}E{media_index:02d}" if tautulli_session.get('media_type') == 'episode' else None,
            'view_offset_ms': view_offset * 1000,  # Tautulli returns seconds
            'duration_ms': duration * 1000,  # Tautulli returns seconds
            'state': tautulli_session.get('state'),  # playing, paused, buffering
            'progress_percent': progress_percent,
            'year': tautulli_session.get('year'),
            'rating_key': tautulli_session.get('rating_key'),
            'grandparent_rating_key': tautulli_session.get('grandparent_rating_key'),
            'poster_url': tautulli_session.get('thumb'),
            'overview': tautulli_session.get('summary'),  # Episode/movie description
        }

        # Try to get TMDB ID from our database and build URLs for linking
        if current_plex_event['media_type'] == 'movie':
            movie = db.execute('SELECT tmdb_id FROM radarr_movies WHERE title = ?',
                             (current_plex_event['title'],)).fetchone()
            if movie:
                current_plex_event['tmdb_id'] = movie['tmdb_id']
                current_plex_event['link_tmdb_id'] = movie['tmdb_id']
                current_plex_event['item_type_for_url'] = 'movie'
                current_plex_event['cached_poster_url'] = _get_media_image_url('poster', movie['tmdb_id'])
        elif current_plex_event['media_type'] == 'episode' and current_plex_event['show_title']:
            show = db.execute('SELECT id, tmdb_id FROM sonarr_shows WHERE LOWER(title) = ?',
                            (current_plex_event['show_title'].lower(),)).fetchone()
            if show:
                current_plex_event['show_tmdb_id'] = show['tmdb_id']
                current_plex_event['link_tmdb_id'] = show['tmdb_id']
                current_plex_event['item_type_for_url'] = 'show'
                current_plex_event['cached_poster_url'] = _get_media_image_url('poster', show['tmdb_id'])
                # Set episode title (from Tautulli's title field, which has the episode name)
                current_plex_event['episode_title'] = tautulli_session.get('title')
                # Build episode detail URL
                current_plex_event['episode_detail_url'] = url_for('main.episode_detail',
                                                                   tmdb_id=show['tmdb_id'],
                                                                   season_number=parent_index,
                                                                   episode_number=media_index)
                # Get episode overview from our database (more accurate than Tautulli's show summary)
                episode = db.execute('''
                    SELECT overview FROM sonarr_episodes
                    WHERE show_id = ? AND season_number = ? AND episode_number = ?
                ''', (show['id'], parent_index, media_index)).fetchone()
                if episode and episode['overview']:
                    current_plex_event['overview'] = episode['overview']

    def load_stats():
        cached_stats = _get_profile_stats(db, user_id, now_playing_count=0, member_id=session.get('member_id'))
        cached_stats['now_playing_count'] = tautulli_stream_count
        return cached_stats

    def load_recent_shows():
        recent_watched = db.execute("""
            SELECT
                media_type,
                CASE
                    WHEN media_type = 'episode' THEN show_title
                    ELSE title
                END as display_title,
                tmdb_id,
                MAX(event_timestamp) as latest_timestamp
            FROM plex_activity_log
            WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble')
            AND (duration_ms IS NULL OR duration_ms >= 600000)
            AND event_timestamp >= datetime('now', '-7 days')
            GROUP BY
                CASE
                    WHEN media_type = 'episode' THEN show_title
                    WHEN media_type = 'movie' THEN tmdb_id
                    ELSE title
                END
            ORDER BY latest_timestamp DESC
            LIMIT ?
        """, (s_username, recent_activity_limit)).fetchall()

        movie_tmdb_ids = [dict(i)['tmdb_id'] for i in recent_watched
                          if dict(i)['media_type'] == 'movie' and dict(i).get('tmdb_id')]
        show_titles = [dict(i)['display_title'].lower() for i in recent_watched
                       if dict(i)['media_type'] == 'episode' and dict(i).get('display_title')]

        movies_by_id = {}
        if movie_tmdb_ids:
            placeholders = ','.join('?' * len(movie_tmdb_ids))
            for row in db.execute(
                f'SELECT tmdb_id, title, year, status, poster_url FROM radarr_movies WHERE tmdb_id IN ({placeholders})',
                movie_tmdb_ids
            ).fetchall():
                movies_by_id[row['tmdb_id']] = dict(row)

        shows_by_title = {}
        if show_titles:
            placeholders = ','.join('?' * len(show_titles))
            for row in db.execute(
                f'SELECT tmdb_id, title, year, status, poster_url FROM sonarr_shows WHERE LOWER(title) IN ({placeholders})',
                show_titles
            ).fetchall():
                shows_by_title[row['title'].lower()] = dict(row)

        recent_shows_enriched = []
        for item in recent_watched:
            item_dict = dict(item)

            if item_dict['media_type'] == 'movie' and item_dict.get('tmdb_id'):
                movie = movies_by_id.get(item_dict['tmdb_id'])
                if movie:
                    item_dict['title'] = movie['title']
                    item_dict['year'] = movie['year']
                    item_dict['status'] = movie['status']
                    item_dict['cached_poster_url'] = _get_media_image_url('poster', movie['tmdb_id'], variant='thumb')
                    item_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=movie['tmdb_id'])
                    item_dict['item_type'] = 'movie'
                    recent_shows_enriched.append(item_dict)

            elif item_dict['media_type'] == 'episode' and item_dict.get('display_title'):
                show = shows_by_title.get(item_dict['display_title'].lower())
                if show:
                    item_dict['title'] = show['title']
                    item_dict['year'] = show['year']
                    item_dict['status'] = show['status']
                    item_dict['show_db_id'] = show['tmdb_id']
                    item_dict['cached_poster_url'] = _get_media_image_url('poster', show['tmdb_id'], variant='thumb')
                    item_dict['detail_url'] = url_for('main.show_detail', tmdb_id=show['tmdb_id'])
                    item_dict['item_type'] = 'show'
                    recent_shows_enriched.append(item_dict)

        return recent_shows_enriched

    def _relative_date_label(date_val, today_local):
        """Return 'Today', 'Tomorrow', 'Yesterday', or None for other dates."""
        if not date_val:
            return None
        try:
            if isinstance(date_val, str):
                dt = datetime.datetime.fromisoformat(date_val.replace('Z', '+00:00'))
            else:
                dt = date_val
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            air_date = dt.astimezone().date()
            delta = (air_date - today_local).days
            if delta == 0:
                return 'Today'
            if delta == 1:
                return 'Tomorrow'
            if delta == -1:
                return 'Yesterday'
        except (ValueError, AttributeError):
            pass
        return None

    def load_premieres():
        now_dt = datetime.datetime.now(timezone.utc).replace(microsecond=0)
        now = now_dt.isoformat().replace('+00:00', 'Z')
        seven_days_ago = (now_dt - datetime.timedelta(days=7)).isoformat().replace('+00:00', 'Z')
        today_local = datetime.datetime.now().date()

        _fav_member_id = session.get('member_id')
        if _fav_member_id:
            favorited_show_ids = db.execute("""
                SELECT show_id FROM user_favorites
                WHERE user_id = ? AND member_id = ? AND is_dropped = 0
            """, (user_id, _fav_member_id)).fetchall()
        else:
            favorited_show_ids = db.execute("""
                SELECT show_id FROM user_favorites
                WHERE user_id = ? AND is_dropped = 0
            """, (user_id,)).fetchall()
        favorited_ids = [row['show_id'] for row in favorited_show_ids]

        watched_show_ids = db.execute("""
            SELECT DISTINCT s.id
            FROM plex_activity_log pal
            JOIN sonarr_shows s ON LOWER(s.title) = LOWER(pal.show_title)
            WHERE pal.plex_username = ?
                AND pal.media_type = 'episode'
                AND pal.show_title IS NOT NULL
        """, (s_username,)).fetchall()
        watched_ids = [row['id'] for row in watched_show_ids]

        user_tag_ids = []
        if current_user.plex_username:
            user_tags = db.execute("""
                SELECT id FROM sonarr_tags
                WHERE label LIKE ?
            """, (f"%{current_user.plex_username}%",)).fetchall()
            user_tag_ids = [tag['id'] for tag in user_tags]

        user_requested_ids = []
        if user_tag_ids:
            tag_conditions = []
            tag_params = []
            for tag_id in user_tag_ids:
                tag_conditions.append("(s.tags = ? OR s.tags LIKE ? OR s.tags LIKE ? OR s.tags LIKE ?)")
                tag_params.extend([str(tag_id), f"{tag_id},%", f"%,{tag_id}", f"%,{tag_id},%"])

            user_requested_shows = db.execute(f"""
                SELECT DISTINCT s.id
                FROM sonarr_shows s
                WHERE s.tags IS NOT NULL AND ({' OR '.join(tag_conditions)})
            """, tag_params).fetchall()
            user_requested_ids = [row['id'] for row in user_requested_shows]

        tracked_show_ids = list(set(favorited_ids + watched_ids + user_requested_ids))

        favorited_season_premieres = []
        if tracked_show_ids:
            placeholders = ','.join('?' * len(tracked_show_ids))
            favorited_season_premieres = db.execute(f"""
                SELECT
                    e.id as episode_id,
                    e.episode_number,
                    e.title as episode_title,
                    e.air_date_utc,
                    e.has_file,
                    e.overview,
                    ss.season_number,
                    s.id as show_db_id,
                    s.tmdb_id,
                    s.title as show_title,
                    s.poster_url,
                    s.year,
                    s.tags
                FROM sonarr_episodes e
                JOIN sonarr_seasons ss ON e.season_id = ss.id
                JOIN sonarr_shows s ON ss.show_id = s.id
                WHERE s.id IN ({placeholders})
                    AND e.episode_number = 1
                    AND ss.season_number > 1
                    AND e.air_date_utc IS NOT NULL
                    AND e.air_date_utc >= ?
                ORDER BY
                    CASE WHEN e.air_date_utc >= ? THEN 0 ELSE 1 END ASC,
                    CASE WHEN e.air_date_utc >= ? THEN e.air_date_utc END ASC,
                    CASE WHEN e.air_date_utc < ? THEN e.air_date_utc END DESC
                LIMIT ?
            """, (*tracked_show_ids, seven_days_ago, now, now, now, homepage_premiere_limit)).fetchall()

        all_series_premieres = db.execute("""
            SELECT
                s.id as show_db_id,
                s.tmdb_id,
                s.title as show_title,
                s.poster_url,
                s.year,
                s.overview,
                ss.season_number,
                e.episode_number,
                e.air_date_utc as premiere_date,
                s.tags
            FROM sonarr_shows s
            JOIN sonarr_seasons ss ON ss.show_id = s.id
            JOIN sonarr_episodes e ON e.season_id = ss.id
            WHERE e.episode_number = 1
                AND ss.season_number = 1
                AND e.air_date_utc IS NOT NULL
                AND e.air_date_utc >= ?
            ORDER BY
                CASE WHEN e.air_date_utc >= ? THEN 0 ELSE 1 END ASC,
                CASE WHEN e.air_date_utc >= ? THEN e.air_date_utc END ASC,
                CASE WHEN e.air_date_utc < ? THEN e.air_date_utc END DESC
            LIMIT ?
        """, (seven_days_ago, now, now, now, homepage_premiere_limit)).fetchall()

        formatted_favorited_premieres = []
        for ep in favorited_season_premieres:
            ep_dict = dict(ep)
            ep_dict['cached_poster_url'] = _get_media_image_url('poster', ep['tmdb_id'], variant='thumb')
            ep_dict['show_url'] = url_for('main.show_detail', tmdb_id=ep['tmdb_id'])
            ep_dict['episode_url'] = url_for('main.episode_detail',
                                             tmdb_id=ep['tmdb_id'],
                                             season_number=ep['season_number'],
                                             episode_number=ep['episode_number'])
            ep_dict['is_favorited'] = ep['show_db_id'] in favorited_ids
            ep_dict['premiere_type'] = f"S{ep['season_number']}"
            ep_dict['is_newly_aired'] = ep['air_date_utc'] and ep['air_date_utc'] < now
            rel = _relative_date_label(ep['air_date_utc'], today_local)
            ep_dict['date_label'] = rel if rel else format_datetime_simple(ep['air_date_utc'], '%b %d')
            ep_dict['user_requested'] = False
            if user_tag_ids and ep['tags']:
                show_tag_ids = [int(tag_id) for tag_id in str(ep['tags']).split(',') if tag_id.strip().isdigit()]
                ep_dict['user_requested'] = any(tag_id in user_tag_ids for tag_id in show_tag_ids)
            formatted_favorited_premieres.append(ep_dict)

        formatted_series_premieres = []
        for show in all_series_premieres:
            show_dict = dict(show)
            show_dict['cached_poster_url'] = _get_media_image_url('poster', show['tmdb_id'], variant='thumb')
            show_dict['show_url'] = url_for('main.show_detail', tmdb_id=show['tmdb_id'])
            show_dict['episode_url'] = url_for('main.episode_detail',
                                               tmdb_id=show['tmdb_id'],
                                               season_number=show['season_number'],
                                               episode_number=show['episode_number'])
            show_dict['premiere_type'] = 'Series Premiere'
            show_dict['is_newly_aired'] = show['premiere_date'] and show['premiere_date'] < now
            rel = _relative_date_label(show['premiere_date'], today_local)
            show_dict['date_label'] = rel if rel else format_datetime_simple(show['premiere_date'], '%b %d')
            show_dict['user_requested'] = False
            if user_tag_ids and show['tags']:
                show_tag_ids = [int(tag_id) for tag_id in str(show['tags']).split(',') if tag_id.strip().isdigit()]
                show_dict['user_requested'] = any(tag_id in user_tag_ids for tag_id in show_tag_ids)
            formatted_series_premieres.append(show_dict)

        return {
            'favorited_season_premieres': formatted_favorited_premieres,
            'all_series_premieres': formatted_series_premieres,
        }

    def load_movies():
        availability_expr = (
            "COALESCE("
            "m.availability_date, "
            "m.digital_release_date, "
            "m.release_date, "
            "m.physical_release_date, "
            "m.in_cinemas_date"
            ")"
        )

        recently_synced = db.execute("""
            SELECT
                m.tmdb_id,
                m.title,
                m.year,
                m.overview,
                m.poster_url,
                m.status,
                m.release_date,
                m.has_file,
                m.last_synced_at,
                m.movie_file_added_date
            FROM radarr_movies m
            WHERE COALESCE(m.has_file, 0) = 1
            ORDER BY COALESCE(m.movie_file_added_date, m.last_synced_at, m.release_date) DESC
            LIMIT ?
        """, (homepage_movie_limit,)).fetchall()

        coming_soon_movies = db.execute(f"""
            SELECT
                m.tmdb_id,
                m.title,
                m.year,
                m.overview,
                m.poster_url,
                m.status,
                m.release_date,
                m.has_file,
                m.last_synced_at,
                m.availability_date,
                m.digital_release_date,
                m.physical_release_date,
                m.in_cinemas_date,
                {availability_expr} as display_release_date
            FROM radarr_movies m
            WHERE COALESCE(m.has_file, 0) = 0
                AND COALESCE(m.monitored, 1) = 1
                AND {availability_expr} IS NOT NULL
                AND {availability_expr} > date('now')
            ORDER BY {availability_expr} ASC, m.title COLLATE NOCASE ASC
            LIMIT ?
        """, (homepage_movie_limit,)).fetchall()

        formatted_recently_downloaded = []
        for movie in recently_synced:
            movie_dict = dict(movie)
            movie_dict['cached_poster_url'] = _get_media_image_url('poster', movie['tmdb_id'], variant='thumb')
            movie_dict['movie_url'] = url_for('main.movie_detail', tmdb_id=movie['tmdb_id'])
            movie_dict['badge_text'] = 'In Library'
            formatted_recently_downloaded.append(movie_dict)

        formatted_coming_soon = []
        for movie in coming_soon_movies:
            movie_dict = dict(movie)
            movie_dict['cached_poster_url'] = _get_media_image_url('poster', movie['tmdb_id'], variant='thumb')
            movie_dict['movie_url'] = url_for('main.movie_detail', tmdb_id=movie['tmdb_id'])
            movie_dict['badge_text'] = 'Coming Soon'
            movie_dict['display_release_date'] = (
                movie_dict.get('display_release_date')
                or movie_dict.get('availability_date')
                or movie_dict.get('release_date')
            )
            formatted_coming_soon.append(movie_dict)

        return {
            'recently_downloaded': formatted_recently_downloaded,
            'coming_soon_movies': formatted_coming_soon,
        }

    step_started_at = time.perf_counter()
    stats = dict(_get_cached_value(f'homepage:stats:{user_id}', 120, load_stats))
    mark_timing('homepage_stats', step_started_at)
    stats['now_playing_count'] = tautulli_stream_count
    step_started_at = time.perf_counter()
    recent_shows_enriched = _get_cached_value(f'homepage:recent:{user_id}', 120, load_recent_shows)
    mark_timing('homepage_recent', step_started_at)
    step_started_at = time.perf_counter()
    premieres_payload = _get_cached_value(f'homepage:premieres:{user_id}', 300, load_premieres)
    mark_timing('homepage_premieres', step_started_at)
    step_started_at = time.perf_counter()
    movies_payload = _get_cached_value('homepage:movies', 600, load_movies)
    mark_timing('homepage_movies', step_started_at)

    step_started_at = time.perf_counter()
    response = render_template('home_dashboard.html',
                               user=user_dict,
                               current_plex_event=current_plex_event,
                               recent_shows=recent_shows_enriched,
                               favorited_season_premieres=premieres_payload['favorited_season_premieres'],
                               all_series_premieres=premieres_payload['all_series_premieres'],
                               recently_downloaded=movies_payload['recently_downloaded'],
                               coming_soon_movies=movies_payload['coming_soon_movies'],
                               **stats)
    mark_timing('render_template', step_started_at)

    total_ms = round((time.perf_counter() - route_started_at) * 1000, 2)
    timing_summary = ', '.join(f'{label}={elapsed_ms}ms' for label, elapsed_ms in timings)
    print(f"homepage_timing user_id={user_id} total={total_ms}ms {timing_summary}", flush=True)

    return response
