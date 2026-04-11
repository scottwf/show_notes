import os
import json
import datetime
from datetime import timezone as dt_timezone
import pytz
from flask import current_app, url_for
from . import database
from .service_testing import get_jellyseerr_requests_for_user

def generate_ical_for_user(db, user_id, feed_filter='all', alarm='1d'):
    """
    Generate an iCal (.ics) feed for a user's favorited shows.

    Args:
        feed_filter: 'all' | 'premieres' | 'series' | 'finales'
            - all: every upcoming episode from favorites
            - premieres: only season/series premiere episodes (ep 1)
            - series: only series premieres (ep 1, season 1)
            - finales: only season finale episodes
        alarm: '1d' | '2h' | 'none'
            - 1d: alert 1 day before air date
            - 2h: alert 2 hours before air date (only useful if time is known)
            - none: no alarm
    """
    import datetime as dt

    def ical_escape(text):
        if not text:
            return ''
        text = str(text).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n').replace('\r', '')
        return text

    def fold_line(line):
        """RFC 5545: fold lines longer than 75 octets."""
        encoded = line.encode('utf-8')
        if len(encoded) <= 75:
            return line + '\r\n'
        result = []
        while len(encoded) > 75:
            split = 75
            while split > 0 and (encoded[split] & 0xC0) == 0x80:
                split -= 1
            result.append(encoded[:split].decode('utf-8'))
            encoded = encoded[split:]
        result.append(encoded.decode('utf-8'))
        return '\r\n '.join(result) + '\r\n'

    now_utc = dt.datetime.now(dt.timezone.utc)
    ninety_days = (now_utc.date() + dt.timedelta(days=90)).isoformat()

    # Calendar name based on filter
    cal_names = {
        'all': 'ShowNotes - My Shows',
        'premieres': 'ShowNotes - Premieres',
        'series': 'ShowNotes - Series Premieres',
        'finales': 'ShowNotes - Season Finales',
    }
    cal_name = cal_names.get(feed_filter, 'ShowNotes - My Shows')

    # Get user's favorited show IDs
    favorites = db.execute(
        'SELECT DISTINCT show_id FROM user_favorites WHERE user_id = ? AND is_dropped = 0',
        (user_id,)
    ).fetchall()
    favorited_show_ids = [f['show_id'] for f in favorites]

    if not favorited_show_ids:
        events = []
    else:
        placeholders = ','.join('?' * len(favorited_show_ids))
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S')

        # Build WHERE clause additions based on filter
        filter_clause = ''
        if feed_filter == 'premieres':
            filter_clause = 'AND e.episode_number = 1'
        elif feed_filter == 'series':
            filter_clause = 'AND e.episode_number = 1 AND ss.season_number = 1'
        elif feed_filter == 'finales':
            filter_clause = '''AND e.episode_number > 1
              AND e.episode_number = (
                SELECT MAX(e2.episode_number) FROM sonarr_episodes e2 WHERE e2.season_id = e.season_id
              )'''

        rows = db.execute(f"""
            SELECT e.id, e.title as ep_title, e.episode_number, e.air_date_utc,
                   e.overview, ss.season_number, s.title as show_title, s.tmdb_id,
                   e.episode_number = 1 as is_premiere,
                   (e.episode_number = (
                     SELECT MAX(e2.episode_number) FROM sonarr_episodes e2 WHERE e2.season_id = e.season_id
                   ) AND e.episode_number > 1) as is_finale
            FROM sonarr_episodes e
            JOIN sonarr_seasons ss ON e.season_id = ss.id
            JOIN sonarr_shows s ON ss.show_id = s.id
            WHERE s.id IN ({placeholders})
              AND ss.season_number > 0
              AND e.air_date_utc >= ?
              AND e.air_date_utc <= ?
              {filter_clause}
            ORDER BY e.air_date_utc ASC
            LIMIT 500
        """, favorited_show_ids + [now_str, ninety_days + ' 23:59:59']).fetchall()
        events = [dict(r) for r in rows]

    # Movies feed: upcoming monitored Radarr releases (not yet downloaded)
    if feed_filter == 'movies':
        movie_rows = db.execute("""
            SELECT id, title, release_date, overview, tmdb_id
            FROM radarr_movies
            WHERE monitored = 1
              AND has_file = 0
              AND release_date >= ?
              AND release_date <= ?
            ORDER BY release_date ASC
            LIMIT 200
        """, (now_str[:10], ninety_days)).fetchall()
        movie_events = [dict(r) for r in movie_rows]
    else:
        movie_events = []

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//ShowNotes//ShowNotes Calendar//EN',
        f'X-WR-CALNAME:{ical_escape(cal_name)}',
        'X-WR-CALDESC:Upcoming TV events from your ShowNotes favorites',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]

    def append_alarm(lines, title, alarm):
        if alarm == '1d':
            lines.append('BEGIN:VALARM')
            lines.append('ACTION:DISPLAY')
            lines.append('TRIGGER:-P1D')
            lines.append(f'DESCRIPTION:{ical_escape("Reminder: " + title + " airs tomorrow")}')
            lines.append('END:VALARM')
        elif alarm == '2h':
            lines.append('BEGIN:VALARM')
            lines.append('ACTION:DISPLAY')
            lines.append('TRIGGER:-PT2H')
            lines.append(f'DESCRIPTION:{ical_escape("Reminder: " + title + " airs today")}')
            lines.append('END:VALARM')

    # TV episode events
    for ev in events:
        air_date = ev.get('air_date_utc', '')
        if not air_date:
            continue
        try:
            air_dt = dt.datetime.fromisoformat(str(air_date).replace('Z', '+00:00'))
            date_str = air_dt.strftime('%Y%m%d')
        except Exception:
            continue

        sn = ev.get('season_number', 0)
        en = ev.get('episode_number', 0)
        ep_title = ev.get('ep_title') or f'Episode {en}'
        show_title = ev.get('show_title', 'Unknown Show')
        is_premiere = bool(ev.get('is_premiere'))
        is_finale = bool(ev.get('is_finale'))

        if is_premiere and sn == 1:
            label = ' \U0001f7e2 Series Premiere'
        elif is_premiere:
            label = f' \U0001f7e1 Season {sn} Premiere'
        elif is_finale:
            label = f' \U0001f534 Season {sn} Finale'
        else:
            label = ''

        summary = f'{show_title} - S{sn:02d}E{en:02d}: {ep_title}{label}'

        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:shownotes-ep-{ev["id"]}-{feed_filter}@shownotes')
        lines.append(f'DTSTART;VALUE=DATE:{date_str}')
        lines.append(f'DTEND;VALUE=DATE:{date_str}')
        lines.append(f'SUMMARY:{ical_escape(summary)}')
        if ev.get('overview'):
            lines.append(f'DESCRIPTION:{ical_escape(ev["overview"])}')
        lines.append(f'DTSTAMP:{now_utc.strftime("%Y%m%dT%H%M%SZ")}')
        append_alarm(lines, show_title, alarm)
        lines.append('END:VEVENT')

    # Movie events
    for mv in movie_events:
        release_date = mv.get('release_date', '')
        if not release_date:
            continue
        try:
            date_str = str(release_date)[:10].replace('-', '')
            if len(date_str) != 8:
                continue
        except Exception:
            continue

        title = mv.get('title', 'Unknown Movie')
        summary = f'\U0001f3a5 {title}'

        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:shownotes-movie-{mv["id"]}@shownotes')
        lines.append(f'DTSTART;VALUE=DATE:{date_str}')
        lines.append(f'DTEND;VALUE=DATE:{date_str}')
        lines.append(f'SUMMARY:{ical_escape(summary)}')
        if mv.get('overview'):
            lines.append(f'DESCRIPTION:{ical_escape(mv["overview"])}')
        lines.append(f'DTSTAMP:{now_utc.strftime("%Y%m%dT%H%M%SZ")}')
        append_alarm(lines, title, alarm)
        lines.append('END:VEVENT')

    lines.append('END:VCALENDAR')

    return ''.join(fold_line(line) for line in lines)


def get_calendar_cache_path():
    """Get the path to the calendar cache file."""
    cache_dir = os.path.join(current_app.root_path, 'static', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'calendar_data.json')


def get_calendar_cache():
    """
    Get cached calendar data if it exists and is from today.

    Returns:
        dict: Cached calendar data or None if cache is stale/missing
    """
    try:
        cache_path = get_calendar_cache_path()

        if not os.path.exists(cache_path):
            return None

        with open(cache_path, 'r') as f:
            cache = json.load(f)

        # Check if cache is from today (UTC date)
        cache_date = cache.get('cache_date')
        today = datetime.datetime.now(dt_timezone.utc).date().isoformat()

        if cache_date != today:
            current_app.logger.info(f"Calendar cache is stale (from {cache_date}, today is {today})")
            return None

        current_app.logger.debug("Using cached calendar data")
        return cache.get('data')

    except Exception as e:
        current_app.logger.error(f"Error reading calendar cache: {e}")
        return None


def set_calendar_cache(data):
    """
    Save calendar data to cache.

    Args:
        data: Dictionary with calendar data to cache
    """
    try:
        cache_path = get_calendar_cache_path()

        cache = {
            'cache_date': datetime.datetime.now(dt_timezone.utc).date().isoformat(),
            'cached_at': datetime.datetime.now(dt_timezone.utc).isoformat(),
            'data': data
        }

        with open(cache_path, 'w') as f:
            json.dump(cache, f)

        current_app.logger.info("Calendar data cached successfully")

    except Exception as e:
        current_app.logger.error(f"Error writing calendar cache: {e}")


def invalidate_calendar_cache():
    """
    Invalidate the calendar cache (e.g., after Sonarr sync).
    """
    try:
        cache_path = get_calendar_cache_path()

        if os.path.exists(cache_path):
            os.remove(cache_path)
            current_app.logger.info("Calendar cache invalidated")

    except Exception as e:
        current_app.logger.error(f"Error invalidating calendar cache: {e}")


def build_calendar_data(db):
    """
    Build calendar data from the database.

    This fetches all upcoming episodes and premieres and returns them
    in a format that can be cached and used by both the calendar page
    and homepage widgets.

    Args:
        db: Database connection

    Returns:
        dict: Calendar data with upcoming_episodes and premieres
    """
    from flask import url_for
    import datetime as dt

    now_utc = dt.datetime.now(dt.timezone.utc)
    now = now_utc.strftime('%Y-%m-%d %H:%M:%S')
    today = now_utc.date().isoformat()

    # Get all upcoming episodes (next 30 days, limit 200)
    thirty_days_later = (now_utc.date() + dt.timedelta(days=30)).isoformat()

    upcoming_episodes = db.execute("""
        SELECT
            e.id as episode_id,
            e.title as episode_title,
            e.episode_number,
            e.air_date_utc,
            e.overview as episode_overview,
            e.has_file,
            ss.season_number,
            s.id as show_id,
            s.title as show_title,
            s.tmdb_id,
            s.tvdb_id,
            s.year,
            s.status,
            s.network_name
        FROM sonarr_episodes e
        JOIN sonarr_seasons ss ON e.season_id = ss.id
        JOIN sonarr_shows s ON ss.show_id = s.id
        WHERE e.air_date_utc >= ?
          AND e.air_date_utc <= ?
          AND ss.season_number > 0
        ORDER BY e.air_date_utc ASC
        LIMIT 200
    """, (now, thirty_days_later + ' 23:59:59')).fetchall()

    # Get all premieres (season premiere = episode 1, not yet downloaded)
    premieres = db.execute("""
        SELECT
            e.id as episode_id,
            e.title as episode_title,
            e.episode_number,
            e.air_date_utc,
            e.overview as episode_overview,
            e.has_file,
            ss.season_number,
            s.id as show_id,
            s.title as show_title,
            s.tmdb_id,
            s.tvdb_id,
            s.year,
            s.status,
            s.network_name,
            s.sonarr_id,
            s.tags as show_tags
        FROM sonarr_episodes e
        JOIN sonarr_seasons ss ON e.season_id = ss.id
        JOIN sonarr_shows s ON ss.show_id = s.id
        WHERE e.episode_number = 1
          AND ss.season_number > 0
          AND e.air_date_utc >= ?
          AND e.has_file = 0
        ORDER BY e.air_date_utc ASC
        LIMIT 100
    """, (now,)).fetchall()

    # Get upcoming season finales (last episode of each season, next 60 days)
    sixty_days_later = (now_utc.date() + dt.timedelta(days=60)).isoformat()
    finales = db.execute("""
        SELECT
            e.id as episode_id,
            e.title as episode_title,
            e.episode_number,
            e.air_date_utc,
            e.overview as episode_overview,
            e.has_file,
            ss.season_number,
            s.id as show_id,
            s.title as show_title,
            s.tmdb_id,
            s.tvdb_id,
            s.year,
            s.status,
            s.network_name,
            s.sonarr_id,
            s.tags as show_tags
        FROM sonarr_episodes e
        JOIN sonarr_seasons ss ON e.season_id = ss.id
        JOIN sonarr_shows s ON ss.show_id = s.id
        WHERE ss.season_number > 0
          AND e.air_date_utc >= ?
          AND e.air_date_utc <= ?
          AND e.episode_number > 1
          AND e.episode_number = (
            SELECT MAX(e2.episode_number) FROM sonarr_episodes e2 WHERE e2.season_id = e.season_id
          )
        ORDER BY e.air_date_utc ASC
        LIMIT 100
    """, (now, sixty_days_later + ' 23:59:59')).fetchall()

    # Get all Sonarr tags for user request matching
    sonarr_tags = db.execute("SELECT id, label FROM sonarr_tags").fetchall()
    tags_by_label = {tag['label'].lower(): tag['id'] for tag in sonarr_tags}

    # Convert to serializable format
    def episode_to_dict(ep, is_premiere=False, is_finale=False):
        ep_dict = dict(ep)
        # Add computed fields that don't depend on user context
        ep_dict['is_season_premiere'] = ep_dict.get('episode_number') == 1
        ep_dict['is_series_premiere'] = ep_dict.get('episode_number') == 1 and ep_dict.get('season_number') == 1
        ep_dict['is_season_finale'] = is_finale

        # Parse tags if present
        if ep_dict.get('show_tags'):
            try:
                ep_dict['show_tags'] = json.loads(ep_dict['show_tags'])
            except:
                ep_dict['show_tags'] = []

        return ep_dict

    data = {
        'upcoming_episodes': [episode_to_dict(ep) for ep in upcoming_episodes],
        'premieres': [episode_to_dict(ep, is_premiere=True) for ep in premieres],
        'finales': [episode_to_dict(ep, is_finale=True) for ep in finales],
        'tags_by_label': tags_by_label,
        'built_at': now_utc.isoformat()
    }

    return data


def get_calendar_data_for_user(db, user_id, plex_username=None):
    """
    Get calendar data enriched with user-specific information.

    This uses cached data when available and adds user context like
    favorites and watch history.

    Args:
        db: Database connection
        user_id: Current user's ID
        plex_username: User's Plex username for request matching

    Returns:
        dict: Calendar data with user context added
    """
    from flask import url_for

    # Try to get cached data
    cached = get_calendar_cache()

    if cached:
        data = cached
    else:
        # Build fresh data
        data = build_calendar_data(db)
        # Cache it for other users/requests
        set_calendar_cache(data)

    # Get user-specific data
    favorited_show_ids = set()
    watched_show_ids = set()

    # Get user's favorites
    favorites = db.execute(
        'SELECT show_id FROM user_favorites WHERE user_id = ? AND is_dropped = 0',
        (user_id,)
    ).fetchall()
    favorited_show_ids = {f['show_id'] for f in favorites}

    # Get user's watched shows from Plex activity (join by title — grandparent_rating_key
    # is a Plex internal ID, not a TVDB ID, so CAST join always returns 0 results)
    watched = db.execute("""
        SELECT DISTINCT s.id
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON LOWER(s.title) = LOWER(pal.show_title)
        WHERE pal.plex_username = ?
          AND pal.media_type = 'episode'
          AND pal.show_title IS NOT NULL
    """, (plex_username or '',)).fetchall()
    watched_show_ids = {w['id'] for w in watched}

    # Get user's tag ID for request matching via Sonarr tags
    user_tag_id = None
    if plex_username:
        tags_by_label = data.get('tags_by_label', {})
        user_tag_id = tags_by_label.get(plex_username.lower())

    # Also get user's Jellyseerr requested show TMDB IDs directly
    jellyseerr_requested_tmdb_ids = get_jellyseerr_requests_for_user(plex_username) if plex_username else set()

    # Build requested show_ids from Jellyseerr TMDB IDs
    jellyseerr_requested_show_ids = set()
    if jellyseerr_requested_tmdb_ids:
        placeholders = ','.join('?' * len(jellyseerr_requested_tmdb_ids))
        rows = db.execute(
            f'SELECT id FROM sonarr_shows WHERE tmdb_id IN ({placeholders})',
            list(jellyseerr_requested_tmdb_ids)
        ).fetchall()
        jellyseerr_requested_show_ids = {r['id'] for r in rows}

    # Tracked shows = favorited + watched
    tracked_show_ids = favorited_show_ids | watched_show_ids

    # Enrich episodes with user context and URLs
    def enrich_episode(ep):
        ep = ep.copy()  # Don't modify cached data
        show_id = ep.get('show_id')
        tmdb_id = ep.get('tmdb_id')

        ep['is_favorited'] = show_id in favorited_show_ids
        ep['is_watched'] = show_id in watched_show_ids
        ep['is_tracked'] = show_id in tracked_show_ids

        # Check if user requested this show (Sonarr tags OR direct Jellyseerr lookup)
        ep['user_requested'] = False
        if user_tag_id and ep.get('show_tags'):
            ep['user_requested'] = user_tag_id in ep['show_tags']
        if not ep['user_requested'] and show_id in jellyseerr_requested_show_ids:
            ep['user_requested'] = True

        # Add URLs (these need to be generated at request time)
        if tmdb_id:
            ep['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=tmdb_id)
            ep['show_url'] = url_for('main.show_detail', tmdb_id=tmdb_id)

        return ep

    enriched_data = {
        'upcoming_episodes': [enrich_episode(ep) for ep in data['upcoming_episodes']],
        'premieres': [enrich_episode(ep) for ep in data['premieres']],
        'finales': [enrich_episode(ep) for ep in data.get('finales', [])],
        'tracked_show_ids': list(tracked_show_ids),
        'favorited_show_ids': list(favorited_show_ids),
        'user_tag_id': user_tag_id
    }

    # Filter upcoming to only tracked shows for the main calendar view
    enriched_data['tracked_upcoming'] = [
        ep for ep in enriched_data['upcoming_episodes']
        if ep['is_tracked']
    ]

    # Filter finales to tracked shows
    enriched_data['tracked_finales'] = [
        ep for ep in enriched_data['finales']
        if ep['is_tracked']
    ]

    return enriched_data
