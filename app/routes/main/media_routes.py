import json
import re
import sqlite3
import datetime
from datetime import timezone

from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, abort
)
from flask_login import login_required

from ... import database
from . import main_bp
from ._shared import (
    _get_profile_stats, MEMBER_AVATAR_COLORS,
)

@main_bp.route('/search')
@login_required
def search():
    """
    Provides search results for the main user-facing search bar.

    This API endpoint is called by the JavaScript search functionality. It takes
    a query parameter 'q' and searches the `sonarr_shows` and `radarr_movies`
    tables for matching titles.

    Args:
        q (str): The search term, provided as a URL query parameter.

    Returns:
        flask.Response: A JSON response containing a list of search results,
                        including title, type, year, and a URL to the detail page.
    """
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify({'results': [], 'jellyseer_url': None, 'query': ''})

    db = database.get_db()
    
    # Prefer remote/public Jellyseerr URL for browser links, fallback to local URL.
    settings = db.execute(
        'SELECT jellyseer_remote_url, jellyseer_url FROM settings LIMIT 1'
    ).fetchone()
    jellyseer_url = None
    if settings:
        jellyseer_url = (
            settings['jellyseer_remote_url']
            or settings['jellyseer_url']
            or None
        )
    
    # Search Sonarr
    sonarr_results = db.execute(
        "SELECT title, 'show' as type, tmdb_id, year, poster_url, fanart_url FROM sonarr_shows WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    # Search Radarr
    radarr_results = db.execute(
        "SELECT title, 'movie' as type, tmdb_id, year, poster_url, fanart_url FROM radarr_movies WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    results = []
    for row in sonarr_results + radarr_results:
        item = dict(row)
        if item.get('tmdb_id'):
            item['poster_url'] = url_for('main.image_proxy', type='poster', id=item['tmdb_id'])
            item['fanart_url'] = url_for('main.image_proxy', type='background', id=item['tmdb_id'])
        else:
            # Set to placeholder or None if no tmdb_id, so templates don't break
            item['poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
            item['fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
        results.append(item)
    
    # Sort results by title
    results.sort(key=lambda x: x['title'])
    
    return jsonify({
        'results': results,
        'jellyseer_url': jellyseer_url,
        'query': request.args.get('q', '')
    })

@main_bp.route('/movie/<int:tmdb_id>')
@login_required
def movie_detail(tmdb_id):
    """
    Displays the detail page for a specific movie.

    It fetches the movie's metadata from the `radarr_movies` table using the
    provided TMDB ID. It also retrieves related watch history for the logged-in
    user from the `plex_activity_log` table to show view count and last watched date.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the movie.

    Returns:
        A rendered HTML template for the movie detail page, or a 404 error
        if the movie is not found in the database.
    """
    db = database.get_db()
    movie = db.execute('SELECT * FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not movie:
        abort(404)
    movie_dict = dict(movie)
    if movie_dict.get('tmdb_id'):
        movie_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=movie_dict['tmdb_id'])
        movie_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=movie_dict['tmdb_id'])
    else:
        movie_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        movie_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    admin_service_links = _build_admin_service_links(db, 'movie', movie_dict)
    return render_template('movie_detail.html', movie=movie_dict, admin_service_links=admin_service_links)


def _get_tautulli_rating_key_for_media(db, media_type, tmdb_id):
    """Look up a Plex rating key from activity history for Tautulli deep-links."""
    if media_type == 'show':
        row = db.execute(
            """
            SELECT grandparent_rating_key
            FROM plex_activity_log
            WHERE tmdb_id = ?
              AND media_type = 'episode'
              AND grandparent_rating_key IS NOT NULL
            ORDER BY event_timestamp DESC
            LIMIT 1
            """,
            (tmdb_id,)
        ).fetchone()
        return row['grandparent_rating_key'] if row else None

    row = db.execute(
        """
        SELECT rating_key
        FROM plex_activity_log
        WHERE tmdb_id = ?
          AND media_type = ?
          AND rating_key IS NOT NULL
        ORDER BY event_timestamp DESC
        LIMIT 1
        """,
        (tmdb_id, media_type)
    ).fetchone()
    return row['rating_key'] if row else None


def _build_admin_service_links(db, media_type, media_dict):
    """Build admin-only external service links for detail pages."""
    settings = db.execute(
        'SELECT tautulli_url, sonarr_url, radarr_url FROM settings LIMIT 1'
    ).fetchone()

    if not settings:
        return {}

    links = {}
    tautulli_url = settings['tautulli_url'].rstrip('/') if settings['tautulli_url'] else None
    sonarr_url = settings['sonarr_url'].rstrip('/') if settings['sonarr_url'] else None
    radarr_url = settings['radarr_url'].rstrip('/') if settings['radarr_url'] else None

    if media_type == 'show' and sonarr_url and media_dict.get('sonarr_id'):
        links['sonarr'] = f"{sonarr_url}/series/{media_dict['sonarr_id']}"

    if media_type == 'movie' and radarr_url and media_dict.get('radarr_id'):
        links['radarr'] = f"{radarr_url}/movie/{media_dict['radarr_id']}"

    if tautulli_url and media_dict.get('tmdb_id'):
        rating_key = _get_tautulli_rating_key_for_media(db, media_type, media_dict['tmdb_id'])
        if rating_key:
            links['tautulli'] = f"{tautulli_url}/info?rating_key={rating_key}"

    return links

def _calculate_year_display(show_dict: dict) -> str:
    """Calculate year display string (2016-2019 or 2016-Present)"""
    premiered = show_dict.get('premiered')
    end_date = show_dict.get('end_date')

    if premiered:
        start_year = premiered[:4]
        if end_date:
            end_year = end_date[:4]
            return f"{start_year}-{end_year}" if start_year != end_year else start_year
        return f"{start_year}-Present"

    return str(show_dict['year']) if show_dict.get('year') else "Unknown"

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    """
    Displays the detail page for a specific TV show.

    This function gathers comprehensive information for a show, including:
    - Basic metadata from the `sonarr_shows` table.
    - A list of all seasons and episodes from the `sonarr_seasons` and
      `sonarr_episodes` tables.
    - The user's watch history for the show from `plex_activity_log`.
    - A "featured episode" card, which highlights either the most recently
      watched episode or the next unwatched episode.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the show.

    Returns:
        A rendered HTML template for the show detail page, or a 404 error
        if the show is not found.
    """
    db = database.get_db()
    s_username = session.get('username')
    show_dict = None

    show_row = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        current_app.logger.warning(f"Show with TMDB ID {tmdb_id} not found in sonarr_shows.")
        abort(404)
    show_dict = dict(show_row)
    show_dict['year_display'] = _calculate_year_display(show_dict)

    # Parse genres from JSON
    genres_list = []
    if show_dict.get('genres'):
        try:
            genres_list = json.loads(show_dict['genres'])
        except json.JSONDecodeError:
            pass
    show_dict['genres_list'] = genres_list

    # Fetch cast information (try show_id, then tvdb_id, then tvmaze_id)
    cast_members = []
    cast_rows = db.execute("""
        SELECT * FROM show_cast
        WHERE show_id = ?
        ORDER BY cast_order ASC
        LIMIT 20
    """, (show_dict['id'],)).fetchall()

    if not cast_rows and show_dict.get('tvdb_id'):
        cast_rows = db.execute("""
            SELECT * FROM show_cast
            WHERE show_tvdb_id = ?
            ORDER BY cast_order ASC
            LIMIT 20
        """, (show_dict['tvdb_id'],)).fetchall()

    if not cast_rows and show_dict.get('tvmaze_id'):
        cast_rows = db.execute("""
            SELECT * FROM show_cast
            WHERE show_tvmaze_id = ?
            ORDER BY cast_order ASC
            LIMIT 20
        """, (show_dict['tvmaze_id'],)).fetchall()

    if cast_rows:
        cast_members = [dict(row) for row in cast_rows]

    # Fetch crew (creators, executive producers)
    crew_rows = db.execute("""
        SELECT person_name, job, person_image_url, tvmaze_person_id, sort_order
        FROM show_crew
        WHERE show_id = ?
        ORDER BY CASE job WHEN 'Creator' THEN 0 WHEN 'Co-Creator' THEN 1 WHEN 'Showrunner' THEN 2 ELSE 3 END, sort_order ASC
    """, (show_dict['id'],)).fetchall()
    crew_members = [dict(row) for row in crew_rows] if crew_rows else []

    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id'])
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    show_db_id = show_dict['id']

    # Fetch seasons and episodes in batch to avoid N+1 queries
    seasons_rows = db.execute(
        'SELECT * FROM sonarr_seasons WHERE show_id = ? ORDER BY season_number DESC', (show_db_id,)
    ).fetchall()

    # Get all season IDs (excluding Season 0)
    season_ids = [s['id'] for s in seasons_rows if s['season_number'] != 0]

    # Batch fetch all episodes for all seasons at once
    episodes_by_season = {}
    if season_ids:
        placeholders = ','.join('?' * len(season_ids))
        all_episodes = db.execute(
            f'SELECT * FROM sonarr_episodes WHERE season_id IN ({placeholders}) ORDER BY season_id, episode_number DESC',
            season_ids
        ).fetchall()
        # Group episodes by season_id
        for ep in all_episodes:
            season_id = ep['season_id']
            if season_id not in episodes_by_season:
                episodes_by_season[season_id] = []
            episodes_by_season[season_id].append(dict(ep))

    seasons_with_episodes = []
    all_show_episodes_for_next_aired_check = []

    for season_row in seasons_rows:
        if season_row['season_number'] == 0:
            # Skip specials/Season 0 from main listing
            continue
        season_dict = dict(season_row)
        season_db_id = season_dict['id']

        # Get episodes from pre-fetched map
        current_season_episodes = episodes_by_season.get(season_db_id, [])
        season_dict['episodes'] = current_season_episodes
        seasons_with_episodes.append(season_dict)
        all_show_episodes_for_next_aired_check.extend(current_season_episodes)

    next_aired_episode_info = None
    if show_dict.get('status', '').lower() == 'continuing' or show_dict.get('status', '').lower() == 'upcoming': # Only look for next_aired if show is active
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            relevant_episodes = [ep for ep in all_show_episodes_for_next_aired_check if ep.get('air_date_utc')]
            relevant_episodes.sort(key=lambda ep: ep['air_date_utc'])

            for episode in relevant_episodes:
                air_date_str = episode['air_date_utc']
                try:
                    air_date = datetime.datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                    if air_date > now_utc:
                        season_number_for_next_aired = None
                        # Find season number for this episode
                        for s_dict in seasons_with_episodes:
                            if s_dict['id'] == episode['season_id']:
                                season_number_for_next_aired = s_dict['season_number']
                                break

                        if season_number_for_next_aired is not None: # Ensure season number was found
                            next_aired_episode_info = {
                                'title': episode['title'],
                                'season_number': season_number_for_next_aired,
                                'episode_number': episode['episode_number'],
                                'air_date_utc': air_date_str,
                                'season_episode_str': f"S{str(season_number_for_next_aired).zfill(2)}E{str(episode['episode_number']).zfill(2)}"
                            }
                            break # Found the earliest next aired episode
                except (ValueError, TypeError) as e_parse:
                    current_app.logger.debug(f"Could not parse air_date_utc '{air_date_str}' for episode ID {episode.get('id')}: {e_parse}")
                    continue
        except Exception as e_next_aired:
            current_app.logger.error(f"Error determining next aired episode for show TMDB ID {tmdb_id}: {e_next_aired}")

    currently_watched_episode_info = None
    last_watched_episode_info = None
    plex_username = session.get('username')
    show_tmdb_id_for_plex = show_dict.get('tmdb_id')

    if plex_username and show_tmdb_id_for_plex:
        try:
            # Match by tmdb_id which is reliably set by both Plex webhooks and Tautulli sync
            plex_activity_row = db.execute(
                """
                SELECT title, season_episode, view_offset_ms, duration_ms, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND tmdb_id = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.play', 'media.pause', 'media.resume')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, show_tmdb_id_for_plex)
            ).fetchone()

            if plex_activity_row:
                currently_watched_episode_info = dict(plex_activity_row)
                if currently_watched_episode_info.get('view_offset_ms') is not None and \
                   currently_watched_episode_info.get('duration_ms') is not None and \
                   currently_watched_episode_info['duration_ms'] > 0:
                    progress = (currently_watched_episode_info['view_offset_ms'] / currently_watched_episode_info['duration_ms']) * 100
                    currently_watched_episode_info['progress_percent'] = round(progress)
        except sqlite3.Error as e_sql:
            current_app.logger.error(f"SQLite error fetching currently watched episode for show TMDB ID {show_tmdb_id_for_plex} and user {plex_username}: {e_sql}")
        except Exception as e_watched:
            current_app.logger.error(f"Generic error fetching currently watched episode for show TMDB ID {show_tmdb_id_for_plex} and user {plex_username}: {e_watched}")

        if not currently_watched_episode_info:
            last_row = db.execute(
                """
                SELECT title, season_episode, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND tmdb_id = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.stop', 'media.scrobble', 'watched')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, show_tmdb_id_for_plex)
            ).fetchone()
            if last_row:
                last_watched_episode_info = dict(last_row)

    next_up_episode = get_next_up_episode(
        currently_watched_episode_info,
        last_watched_episode_info,
        show_dict,
        seasons_with_episodes
    )

    # Get Jellyseer URL for request button — prefer public/remote URL for browser links
    settings = db.execute('SELECT jellyseer_url, jellyseer_remote_url FROM settings LIMIT 1').fetchone()
    jellyseer_url = None
    if settings:
        jellyseer_url = settings['jellyseer_remote_url'] or settings['jellyseer_url'] or None
    admin_service_links = _build_admin_service_links(db, 'show', show_dict)

    # Fetch season summaries
    show_summary = None
    season_recaps = {}
    try:
        from app.summary_services import get_season_summary, get_show_summary
        for season_dict in seasons_with_episodes:
            season_dict['summary'] = get_season_summary(tmdb_id, season_dict['season_number'])
            if season_dict['summary']:
                season_recaps[season_dict['season_number']] = season_dict['summary']
        show_summary = get_show_summary(tmdb_id)
    except Exception as e:
        current_app.logger.debug(f"Could not fetch summaries: {e}")

    # Cutoff disclaimer: read from settings, pass to template if disclaimer is enabled
    cutoff_disclaimer = None
    try:
        settings_row = db.execute('SELECT summary_show_disclaimer, llm_knowledge_cutoff_date FROM settings LIMIT 1').fetchone()
        if settings_row and settings_row['summary_show_disclaimer'] not in ('0', 0, None) and settings_row['llm_knowledge_cutoff_date']:
            import datetime as _dt
            cutoff_date = _dt.datetime.strptime(settings_row['llm_knowledge_cutoff_date'], '%Y-%m-%d').date()
            cutoff_disclaimer = cutoff_date.strftime('%B %Y')
    except Exception:
        pass

    return render_template('show_detail.html',
                           show=show_dict,
                           seasons_with_episodes=seasons_with_episodes,
                           next_aired_episode_info=next_aired_episode_info,
                           next_up_episode=next_up_episode,
                           cast_members=cast_members,
                           crew_members=crew_members,
                           jellyseer_url=jellyseer_url,
                           admin_service_links=admin_service_links,
                           season_recaps=season_recaps,
                           show_summary=show_summary,
                           cutoff_disclaimer=cutoff_disclaimer
                           )

def get_next_up_episode(currently_watched, last_watched, show_info, seasons_with_episodes, user_prefs=None):
    """
    Determines the "Next Up" episode for a show's detail page with enhanced logic.
    """
    if user_prefs is None:
        user_prefs = {'skip_specials': True, 'order': 'default'}

    db = database.get_db()
    source_info = None
    is_currently_watching = False
    is_next_unwatched = False

    if currently_watched:
        source_info = currently_watched
        is_currently_watching = True
    elif last_watched:
        last_season_episode_str = last_watched.get('season_episode')
        match = re.match(r'S(\d+)E(\d+)', last_season_episode_str) if last_season_episode_str else None
        if match:
            last_season_num = int(match.group(1))
            last_episode_num = int(match.group(2))

            all_episodes = []
            for season in sorted(seasons_with_episodes, key=lambda s: s['season_number']):
                if user_prefs['skip_specials'] and season['season_number'] == 0:
                    continue
                # Sort episodes within the season
                sorted_episodes = sorted(season['episodes'], key=lambda e: e['episode_number'])
                for episode in sorted_episodes:
                    all_episodes.append({
                        'season_number': season['season_number'],
                        **episode
                    })

            last_watched_index = -1
            for i, ep in enumerate(all_episodes):
                if ep['season_number'] == last_season_num and ep['episode_number'] == last_episode_num:
                    last_watched_index = i
                    break

            if last_watched_index != -1:
                # Search for the next available episode, considering multi-part episodes
                for i in range(last_watched_index + 1, len(all_episodes)):
                    next_ep = all_episodes[i]
                    if next_ep.get('has_file'):
                        # Check for multi-part episode logic (e.g., if the title is the same as the previous)
                        if i > 0 and all_episodes[i-1]['title'] == next_ep['title']:
                            # This might be the second part of a multi-part episode, let's see if we should skip it
                            # For now, we assume the user wants to see the next file regardless.
                            # More complex logic could be added here.
                            pass

                        source_info = {
                            'title': next_ep['title'],
                            'season_episode': f"S{str(next_ep['season_number']).zfill(2)}E{str(next_ep['episode_number']).zfill(2)}",
                            'event_timestamp': last_watched.get('event_timestamp')
                        }
                        is_next_unwatched = True
                        break

        if not source_info:
            source_info = last_watched

    if not source_info:
        return None

    season_episode_str = source_info.get('season_episode')
    match = re.match(r'S(\d+)E(\d+)', season_episode_str) if season_episode_str else None
    if not match:
        return None
    season_number, episode_number = map(int, match.groups())

    episode_detail_url = url_for('main.episode_detail',
                                 tmdb_id=show_info['tmdb_id'],
                                 season_number=season_number,
                                 episode_number=episode_number)

    raw_timestamp = source_info.get('event_timestamp')
    formatted_timestamp = "Unknown"
    if raw_timestamp:
        try:
            dt_obj = datetime.datetime.fromisoformat(str(raw_timestamp).replace('Z', '+00:00'))
            formatted_timestamp = dt_obj.strftime("%b %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            formatted_timestamp = str(raw_timestamp)

    return {
        'title': source_info.get('title'),
        'season_episode_str': season_episode_str,
        'season_number': season_number,
        'episode_number': episode_number,
        'poster_url': show_info.get('cached_poster_url'),
        'event_timestamp': raw_timestamp,
        'formatted_timestamp': formatted_timestamp,
        'progress_percent': source_info.get('progress_percent') if is_currently_watching else None,
        'episode_detail_url': episode_detail_url,
        'is_currently_watching': is_currently_watching,
        'is_next_unwatched': is_next_unwatched,
        'overview': source_info.get('overview', '')
    }
@main_bp.route('/show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>')
@login_required
def episode_detail(tmdb_id, season_number, episode_number):
    """
    Displays the detail page for a single TV episode.

    It fetches metadata for the episode, its parent season, and its parent show
    from the database to provide a comprehensive view. This includes details
    like air date, summary, and a link back to the main show page.

    Args:
        tmdb_id (int): The TMDB ID of the parent show.
        season_number (int): The season number of the episode.
        episode_number (int): The episode number.

    Returns:
        A rendered HTML template for the episode detail page, or a 404 error
        if the show or episode cannot be found.
    """
    db = database.get_db()

    # Fetch show, season, and episode details in one go if possible
    show_row = db.execute('SELECT id, title, tmdb_id, tvdb_id, poster_url, fanart_url FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        abort(404)
    show_dict = dict(show_row)
    # Use consistent names for cached URLs as expected by the new template.
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id']) # Optional for episode page bg
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    show_id = show_dict['id']
    show_tvdb_id = show_dict.get('tvdb_id')
    show_tmdb_id = show_dict.get('tmdb_id')
    show_title = show_dict.get('title')
    season_row = db.execute('SELECT id FROM sonarr_seasons WHERE show_id=? AND season_number=?', (show_id, season_number)).fetchone()
    if not season_row:
        abort(404)

    # Fetch all columns for the episode
    episode_row = db.execute('SELECT * FROM sonarr_episodes WHERE season_id=? AND episode_number=?', (season_row['id'], episode_number)).fetchone()
    if not episode_row:
        abort(404)

    episode_dict = dict(episode_row)

    # Fetch previous and next episodes for navigation
    prev_episode = None
    next_episode = None
    
    # Get previous episode (highest episode number less than current)
    prev_row = db.execute(
        'SELECT episode_number, title FROM sonarr_episodes WHERE season_id=? AND episode_number < ? ORDER BY episode_number DESC LIMIT 1',
        (season_row['id'], episode_number)
    ).fetchone()
    if prev_row:
        prev_episode = dict(prev_row)
    
    # Get next episode (lowest episode number greater than current)
    next_row = db.execute(
        'SELECT episode_number, title FROM sonarr_episodes WHERE season_id=? AND episode_number > ? ORDER BY episode_number ASC LIMIT 1',
        (season_row['id'], episode_number)
    ).fetchone()
    if next_row:
        next_episode = dict(next_row)

    # Try all possible IDs for cast lookup
    episode_characters = []
    # 1. Sonarr TVDB ID
    if show_tvdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tvdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 2. Sonarr TMDB ID
    if not episode_characters and show_tmdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tmdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 3. Try Plex webhook IDs from most recent plex_activity_log for this episode
    if not episode_characters:
        # Try to find the most recent plex_activity_log for this show/season/episode
        # We'll match by show title and season/episode string (season_episode)
        season_episode_str = f"S{str(season_number).zfill(2)}E{str(episode_number).zfill(2)}"
        plex_row = db.execute(
            'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? AND season_episode = ? ORDER BY event_timestamp DESC LIMIT 1',
            (show_title, season_episode_str)
        ).fetchone()
        plex_tmdb_id = None
        plex_tvdb_id = None
        if plex_row:
            import json
            try:
                payload = json.loads(plex_row['raw_payload'])
                guids = payload.get('Metadata', {}).get('Guid', [])
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            plex_tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            plex_tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tvdb_id = None
            except Exception:
                pass
        # 3a. Plex TVDB ID
        if plex_tvdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tvdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]
        # 3b. Plex TMDB ID
        if not episode_characters and plex_tmdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tmdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]

    # Format air date
    if episode_dict.get('air_date_utc'):
        try:
            # Ensure Z is handled for UTC parsing if present
            air_date_str = episode_dict['air_date_utc']
            if 'Z' in air_date_str.upper() and not '+' in air_date_str and not '-' in air_date_str[10:]: # Simple check for Zulu time
                 air_date_str = air_date_str.upper().replace('Z', '+00:00')

            air_dt = datetime.datetime.fromisoformat(air_date_str)
            episode_dict['formatted_air_date'] = air_dt.strftime('%B %d, %Y')
        except ValueError as e:
            current_app.logger.warning(f"Could not parse air_date_utc '{episode_dict['air_date_utc']}' for episode: {e}")
            episode_dict['formatted_air_date'] = episode_dict['air_date_utc'] # Fallback
    else:
        episode_dict['formatted_air_date'] = 'N/A'

    # Ensure 'is_available' based on 'has_file'
    episode_dict['is_available'] = episode_dict.get('has_file', False)

    # Add runtime if available (example field name, adjust if different in your schema)
    # episode_dict['runtime_minutes'] = episode_dict.get('runtime', None)


    # Debug episode_characters before rendering
    current_app.logger.info(f"[DEBUG] Episode {tmdb_id} S{season_number}E{episode_number} found {len(episode_characters)} characters:")
    for char in episode_characters:
        current_app.logger.info(f"[DEBUG] Character: ID={char.get('id')}, Name={char.get('character_name')}, Actor={char.get('actor_name')}")
    
    return render_template('episode_detail.html',
                           show=show_dict,
                           episode=episode_dict,
                           season_number=season_number,
                           episode_characters=episode_characters,
                           prev_episode=prev_episode,
                           next_episode=next_episode)

@main_bp.route('/character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:character_id>')
def character_detail(show_id, season_number, episode_number, character_id):
    """
    Display character detail page showing actor information and other appearances.
    """
    db = database.get_db()

    # Get character information
    character = db.execute('''
        SELECT ec.*
        FROM episode_characters ec
        WHERE ec.id = ?
        LIMIT 1
    ''', (character_id,)).fetchone()

    if not character:
        flash('Character not found.', 'danger')
        return redirect(url_for('main.episode_detail', tmdb_id=show_id, season_number=season_number, episode_number=episode_number))

    # Get show information
    show = db.execute('SELECT title, overview, year FROM sonarr_shows WHERE tmdb_id = ?', (show_id,)).fetchone()
    show_title = show['title'] if show else "Unknown Show"

    # Get all episodes this character appears in for this show
    character_episodes = db.execute('''
        SELECT DISTINCT ec.season_number, ec.episode_number, se.title, se.air_date_utc
        FROM episode_characters ec
        LEFT JOIN sonarr_episodes se ON ec.episode_number = se.episode_number
        LEFT JOIN sonarr_seasons ss ON se.season_id = ss.id AND ec.season_number = ss.season_number
        LEFT JOIN sonarr_shows sshow ON ss.show_id = sshow.id
        WHERE ec.show_tmdb_id = ?
        AND ec.character_name = ?
        AND sshow.tmdb_id = ?
        ORDER BY ec.season_number, ec.episode_number
    ''', (show_id, character['character_name'], show_id)).fetchall()

    # Get other shows this actor appears in (same actor name)
    other_shows = []
    if character['actor_name']:
        other_shows = db.execute('''
            SELECT DISTINCT ss.tmdb_id, ss.title, ec.character_name, COUNT(DISTINCT ec.episode_number) as episode_count
            FROM episode_characters ec
            JOIN sonarr_shows ss ON ec.show_tmdb_id = ss.tmdb_id
            WHERE ec.actor_name = ?
            AND ss.tmdb_id != ?
            GROUP BY ss.tmdb_id, ss.title, ec.character_name
            ORDER BY episode_count DESC
            LIMIT 10
        ''', (character['actor_name'], show_id)).fetchall()

    # Try to get TMDB person ID from show_cast table for external links
    tmdb_person_id = None
    tvmaze_person_id = character.get('actor_id')
    if character.get('actor_name'):
        cast_row = db.execute(
            'SELECT tmdb_person_id, person_id FROM show_cast WHERE actor_name = ? AND tmdb_person_id IS NOT NULL LIMIT 1',
            (character['actor_name'],)
        ).fetchone()
        if cast_row:
            tmdb_person_id = cast_row['tmdb_person_id']
            if not tvmaze_person_id:
                tvmaze_person_id = cast_row['person_id']

    return render_template('character_detail.html',
                           show_id=show_id,
                           season_number=season_number,
                           episode_number=episode_number,
                           character_id=character_id,
                           character=character,
                           show_title=show_title,
                           character_episodes=character_episodes,
                           other_shows=other_shows,
                           tmdb_person_id=tmdb_person_id,
                           tvmaze_person_id=tvmaze_person_id)

@main_bp.route('/report_issue/<string:media_type>/<int:media_id>', methods=['GET', 'POST'])
@login_required
def report_issue(media_type, media_id):
    db = database.get_db()
    if request.method == 'POST':
        issue_types = request.form.getlist('issue_type')
        comment = request.form.get('comment', '')
        show_id = request.form.get('show_id')
        title = request.form.get('title', '')
        cursor = db.execute(
            'INSERT INTO issue_reports (user_id, media_type, media_id, show_id, title, issue_type, comment) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (session.get('user_id'), media_type, media_id, show_id, title, ','.join(issue_types), comment)
        )
        report_id = cursor.lastrowid
        db.commit()

        # NOTE: Admin notifications disabled - admins can view reports on dedicated admin page
        # Issue reports no longer create in-app notifications to avoid clutter
        # Pushover notifications (below) still sent for immediate awareness

        # Send Pushover notification to admins
        try:
            from ...utils import send_pushover_notification

            # Build notification message
            push_title = f"Issue Report: {title}"
            push_message = f"User reported: {', '.join(issue_types)}"
            if comment:
                push_message += f"\n\nComment: {comment[:200]}"

            # Send with Sonarr/Radarr link if available
            url_title = "View in Sonarr" if media_type == 'episode' else "View in Radarr" if service_link else None
            success, error = send_pushover_notification(
                title=push_title,
                message=push_message,
                url=service_link,
                url_title=url_title,
                priority=1  # Requires confirmation from admin (high priority)
            )

            if success:
                current_app.logger.info(f"Pushover notification sent for issue report {report_id}")
            elif error and error != "Pushover not configured":
                current_app.logger.error(f"Failed to send Pushover for issue {report_id}: {error}")

        except Exception as e:
            current_app.logger.error(f"Error sending Pushover notification: {e}", exc_info=True)
            # Don't fail the request if Pushover fails - notification is optional

        flash('Issue reported. Thank you!', 'success')
        return redirect(url_for('main.home'))

    issues = [
        'Wrong language', 'No audio', 'Audio out of sync', 'Bad video quality',
        'Wrong episode playing', 'Missing subtitles', 'Other'
    ]
    show_id = request.args.get('show_id', '')
    title = request.args.get('title', '')
    return render_template('report_issue.html', media_type=media_type, media_id=media_id, show_id=show_id, title=title, issues=issues)

# ============================================================================
# USER PROFILE ROUTES
# ============================================================================

# ── Household member routes ───────────────────────────────────────────────────

@main_bp.route('/help')
def help():
    """Display user manual and help documentation"""
    return render_template('help.html')

@main_bp.route('/discover')
def discover():
    """Display upcoming, popular, and recommended content"""
    db = database.get_db()
    settings = db.execute('SELECT jellyseer_url FROM settings LIMIT 1').fetchone()
    jellyseer_url = settings['jellyseer_url'] if settings and settings['jellyseer_url'] else None

    # Popular shows — ranked by unique member count, then play count
    popular_shows = db.execute('''
        SELECT
            s.id, s.tmdb_id, s.title, s.year, s.poster_url,
            COUNT(DISTINCT pal.plex_username) as member_count,
            COUNT(*) as play_count
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
        WHERE pal.event_type = 'media.scrobble'
            AND pal.media_type = 'episode'
            AND pal.event_timestamp >= datetime('now', '-30 days')
        GROUP BY s.id
        HAVING member_count >= 2
        ORDER BY member_count DESC, play_count DESC
        LIMIT 12
    ''').fetchall()

    popular_movies = db.execute('''
        SELECT
            m.id, m.tmdb_id, m.title, m.year, m.poster_url,
            COUNT(DISTINCT pal.plex_username) as member_count,
            COUNT(*) as play_count
        FROM plex_activity_log pal
        JOIN radarr_movies m ON pal.tmdb_id = m.tmdb_id
        WHERE pal.event_type = 'media.scrobble'
            AND pal.media_type = 'movie'
            AND pal.event_timestamp >= datetime('now', '-30 days')
        GROUP BY m.id
        ORDER BY member_count DESC, play_count DESC
        LIMIT 12
    ''').fetchall()

    # Binge Watch — shows where someone watched 4+ episodes in a 24h window
    binge_shows = db.execute('''
        SELECT
            s.id, s.tmdb_id, s.title, s.year, s.poster_url,
            COUNT(DISTINCT pal.plex_username) as binger_count,
            MAX(ep_count) as max_episodes_binged
        FROM sonarr_shows s
        JOIN (
            SELECT tmdb_id, plex_username,
                   COUNT(*) as ep_count,
                   DATE(event_timestamp) as watch_date
            FROM plex_activity_log
            WHERE event_type = 'media.scrobble'
                AND media_type = 'episode'
                AND event_timestamp >= datetime('now', '-30 days')
            GROUP BY tmdb_id, plex_username, DATE(event_timestamp)
            HAVING ep_count >= 4
        ) pal ON s.tmdb_id = pal.tmdb_id
        GROUP BY s.id
        ORDER BY binger_count DESC, max_episodes_binged DESC
        LIMIT 12
    ''').fetchall()

    # Watching Live — episodes watched within 48h of air date by 2+ members
    watching_live = db.execute('''
        SELECT
            s.id, s.tmdb_id, s.title, s.year, s.poster_url,
            COUNT(DISTINCT pal.plex_username) as live_member_count,
            COUNT(DISTINCT ep.id) as live_episode_count
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
        JOIN sonarr_episodes ep ON ep.show_id = s.id
            AND ep.season_number = CAST(SUBSTR(pal.season_episode, 2, INSTR(pal.season_episode, 'E') - 2) AS INTEGER)
            AND ep.episode_number = CAST(SUBSTR(pal.season_episode, INSTR(pal.season_episode, 'E') + 1) AS INTEGER)
        WHERE pal.event_type = 'media.scrobble'
            AND pal.media_type = 'episode'
            AND pal.event_timestamp >= datetime('now', '-30 days')
            AND ep.air_date_utc IS NOT NULL
            AND JULIANDAY(pal.event_timestamp) - JULIANDAY(ep.air_date_utc) BETWEEN 0 AND 2
        GROUP BY s.id
        HAVING live_member_count >= 2
        ORDER BY live_member_count DESC, live_episode_count DESC
        LIMIT 12
    ''').fetchall()

    # Late Night — shows predominantly watched between 10pm-3am (server time)
    late_night = db.execute('''
        SELECT
            s.id, s.tmdb_id, s.title, s.year, s.poster_url,
            COUNT(*) as play_count,
            COUNT(DISTINCT pal.plex_username) as member_count
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
        WHERE pal.event_type = 'media.scrobble'
            AND pal.media_type = 'episode'
            AND pal.event_timestamp >= datetime('now', '-30 days')
            AND (CAST(strftime('%H', pal.event_timestamp) AS INTEGER) >= 22
                 OR CAST(strftime('%H', pal.event_timestamp) AS INTEGER) < 3)
        GROUP BY s.id
        HAVING play_count >= 3
        ORDER BY play_count DESC
        LIMIT 12
    ''').fetchall()

    # Early Bird — shows predominantly watched between 5am-10am
    early_bird = db.execute('''
        SELECT
            s.id, s.tmdb_id, s.title, s.year, s.poster_url,
            COUNT(*) as play_count,
            COUNT(DISTINCT pal.plex_username) as member_count
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
        WHERE pal.event_type = 'media.scrobble'
            AND pal.media_type = 'episode'
            AND pal.event_timestamp >= datetime('now', '-30 days')
            AND CAST(strftime('%H', pal.event_timestamp) AS INTEGER) BETWEEN 5 AND 9
        GROUP BY s.id
        HAVING play_count >= 3
        ORDER BY play_count DESC
        LIMIT 12
    ''').fetchall()

    community_picks = db.execute('''
        WITH all_recommendations AS (
            SELECT
                ur.user_id AS recommender_user_id,
                ur.media_type,
                ur.media_id,
                ur.title,
                ur.created_at
            FROM user_recommendations ur

            UNION ALL

            SELECT
                rs.from_user_id AS recommender_user_id,
                rs.media_type,
                rs.media_id,
                rs.title,
                rs.created_at
            FROM recommendation_shares rs
        )
        SELECT
            ar.media_type,
            ar.media_id,
            COALESCE(s.title, m.title, MAX(ar.title)) AS title,
            COALESCE(s.tmdb_id, m.tmdb_id) AS tmdb_id,
            COALESCE(s.poster_url, m.poster_url) AS poster_url,
            COALESCE(s.year, m.year) AS year,
            COUNT(*) AS recommendation_count,
            COUNT(DISTINCT ar.recommender_user_id) AS recommender_count,
            MAX(ar.created_at) AS latest_recommended_at
        FROM all_recommendations ar
        LEFT JOIN sonarr_shows s ON ar.media_type = 'show' AND ar.media_id = s.id
        LEFT JOIN radarr_movies m ON ar.media_type = 'movie' AND ar.media_id = m.id
        GROUP BY ar.media_type, ar.media_id
        ORDER BY recommendation_count DESC, recommender_count DESC, latest_recommended_at DESC
        LIMIT 12
    ''').fetchall()

    # Recommendations sent to the current user
    received_recs = []
    user_id = session.get('user_id')
    if user_id:
        received_recs = db.execute('''
            SELECT
                rs.id, rs.media_type, rs.media_id, rs.title, rs.note,
                rs.is_read, rs.created_at,
                u.username as from_username, u.profile_photo_url as from_photo,
                s.tmdb_id as show_tmdb_id, s.poster_url as show_poster_url, s.year as show_year,
                m.tmdb_id as movie_tmdb_id, m.poster_url as movie_poster_url, m.year as movie_year
            FROM recommendation_shares rs
            JOIN users u ON rs.from_user_id = u.id
            LEFT JOIN sonarr_shows s ON rs.media_type = 'show' AND rs.media_id = s.id
            LEFT JOIN radarr_movies m ON rs.media_type = 'movie' AND rs.media_id = m.id
            WHERE rs.to_user_id = ?
            ORDER BY rs.created_at DESC
            LIMIT 24
        ''', (user_id,)).fetchall()

    return render_template('discover.html',
                           jellyseer_url=jellyseer_url,
                           popular_shows=popular_shows,
                           popular_movies=popular_movies,
                           binge_shows=binge_shows,
                           watching_live=watching_live,
                           late_night=late_night,
                           early_bird=early_bird,
                           community_picks=community_picks,
                           received_recs=received_recs)

@main_bp.route('/api/summary/feedback', methods=['POST'])
@login_required
def summary_feedback():
    """Submit a thumbs up/down rating or problem report on an AI summary."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json() or {}
    summary_type = data.get('summary_type')   # episode, season, show
    show_id      = data.get('show_id')
    season_number = data.get('season_number')
    episode_id   = data.get('episode_id')
    rating       = data.get('rating')          # 1, -1, or None
    report_type  = data.get('report_type')     # inaccurate, outdated, spoilers, other
    notes        = data.get('notes', '').strip()

    if not summary_type:
        return jsonify({'success': False, 'error': 'summary_type required'}), 400
    if rating not in (1, -1, None):
        return jsonify({'success': False, 'error': 'rating must be 1, -1, or null'}), 400

    db = database.get_db()
    db.execute('''
        INSERT INTO summary_feedback
            (user_id, summary_type, show_id, season_number, episode_id, rating, report_type, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, summary_type, show_id, season_number, episode_id, rating, report_type, notes or None))
    db.commit()

    return jsonify({'success': True})


@main_bp.route('/api/generate-show-summary', methods=['POST'])
@login_required
def generate_show_summary_route():
    """Generate or regenerate a show summary for the current user."""
    from app.summary_services import generate_show_summary
    
    data = request.get_json()
    tmdb_id = data.get('tmdb_id')
    
    if not tmdb_id:
        return jsonify({"error": "tmdb_id required"}), 400
    
    try:
        success, error = generate_show_summary(int(tmdb_id))
    except Exception as e:
        current_app.logger.error(f"Error generating show summary for tmdb_id={tmdb_id}: {e}", exc_info=True)
        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500
    
    if success:
        return jsonify({
            "status": "completed",
            "message": f"Show summary generated successfully"
        })
    else:
        return jsonify({
            "status": "failed",
            "error": error or "Unknown error"
        }), 500


@main_bp.route('/api/generate-season-summary', methods=['POST'])
@login_required
def generate_season_summary_route():
    """Generate or regenerate a season summary for the current user."""
    from app.summary_services import generate_season_summary
    
    data = request.get_json()
    tmdb_id = data.get('tmdb_id')
    season_number = data.get('season_number')
    
    if not tmdb_id or season_number is None:
        return jsonify({"error": "tmdb_id and season_number required"}), 400
    
    success, error = generate_season_summary(int(tmdb_id), int(season_number))
    
    if success:
        return jsonify({
            "status": "completed",
            "message": f"Season {season_number} summary generated successfully"
        })
    else:
        return jsonify({
            "status": "failed",
            "error": error or "Unknown error"
        }), 500


# ========================================
# SOCIAL / PUBLIC PROFILES
# ========================================

@main_bp.route('/members')
@login_required
def members():
    """Community page showing all Plex members and whether they have ShowNotes accounts."""
    db = database.get_db()
    member_filter = request.args.get('filter', 'all')
    sort_key = request.args.get('sort', 'recently_active')

    valid_filters = {'all', 'shownotes', 'plex_only'}
    valid_sorts = {'alphabetical', 'most_active', 'recently_active'}
    if member_filter not in valid_filters:
        member_filter = 'all'
    if sort_key not in valid_sorts:
        sort_key = 'recently_active'

    rows = db.execute(
        '''
        WITH household_activity AS (
            SELECT
                hm.id AS member_id,
                hm.user_id,
                hm.display_name AS member_display_name,
                hm.avatar_url AS member_avatar_url,
                hm.avatar_color AS member_avatar_color,
                u.username,
                u.plex_username,
                u.bio,
                u.profile_photo_url,
                u.profile_show_profile,
                COUNT(pal.id) AS event_count,
                SUM(CASE
                    WHEN pal.event_type IN ('media.play', 'media.scrobble', 'watched') THEN 1
                    ELSE 0
                END) AS play_count,
                COUNT(DISTINCT CASE
                    WHEN pal.media_type = 'episode' THEN pal.show_title
                    ELSE pal.title
                END) AS title_count,
                MAX(pal.event_timestamp) AS last_seen
            FROM household_members hm
            JOIN users u ON hm.user_id = u.id AND u.is_active = 1
            LEFT JOIN plex_activity_log pal
                ON u.plex_username = pal.plex_username
            GROUP BY hm.id
        ),
        user_without_household AS (
            SELECT
                NULL AS member_id,
                u.id AS user_id,
                u.username,
                u.plex_username,
                u.bio,
                u.profile_photo_url,
                u.profile_show_profile,
                NULL AS member_display_name,
                NULL AS member_avatar_url,
                NULL AS member_avatar_color,
                COUNT(pal.id) AS event_count,
                SUM(CASE
                    WHEN pal.event_type IN ('media.play', 'media.scrobble', 'watched') THEN 1
                    ELSE 0
                END) AS play_count,
                COUNT(DISTINCT CASE
                    WHEN pal.media_type = 'episode' THEN pal.show_title
                    ELSE pal.title
                END) AS title_count,
                MAX(pal.event_timestamp) AS last_seen
            FROM users u
            LEFT JOIN plex_activity_log pal
                ON u.plex_username = pal.plex_username
            WHERE u.is_active = 1
              AND u.id NOT IN (SELECT DISTINCT user_id FROM household_members)
            GROUP BY u.id
        ),
        plex_only_activity AS (
            SELECT
                pal.plex_username,
                COUNT(*) AS event_count,
                SUM(CASE
                    WHEN pal.event_type IN ('media.play', 'media.scrobble', 'watched') THEN 1
                    ELSE 0
                END) AS play_count,
                COUNT(DISTINCT CASE
                    WHEN pal.media_type = 'episode' THEN pal.show_title
                    ELSE pal.title
                END) AS title_count,
                MAX(pal.event_timestamp) AS last_seen
            FROM plex_activity_log pal
            WHERE COALESCE(TRIM(pal.plex_username), '') <> ''
              AND pal.plex_username NOT IN (SELECT DISTINCT plex_username FROM users WHERE is_active = 1 AND plex_username IS NOT NULL)
            GROUP BY pal.plex_username
        )
        SELECT
            ha.member_id,
            ha.user_id,
            ha.username,
            ha.plex_username,
            ha.bio,
            ha.profile_photo_url,
            ha.profile_show_profile,
            ha.member_display_name,
            ha.member_avatar_url,
            ha.member_avatar_color,
            ha.event_count,
            ha.play_count,
            ha.title_count,
            ha.last_seen
        FROM household_activity ha
        UNION ALL
        SELECT
            uwh.member_id,
            uwh.user_id,
            uwh.username,
            uwh.plex_username,
            uwh.bio,
            uwh.profile_photo_url,
            uwh.profile_show_profile,
            uwh.member_display_name,
            uwh.member_avatar_url,
            uwh.member_avatar_color,
            uwh.event_count,
            uwh.play_count,
            uwh.title_count,
            uwh.last_seen
        FROM user_without_household uwh
        UNION ALL
        SELECT
            NULL AS member_id,
            NULL AS user_id,
            NULL AS username,
            poa.plex_username,
            NULL AS bio,
            NULL AS profile_photo_url,
            NULL AS profile_show_profile,
            NULL AS member_display_name,
            NULL AS member_avatar_url,
            NULL AS member_avatar_color,
            poa.event_count,
            poa.play_count,
            poa.title_count,
            poa.last_seen
        FROM plex_only_activity poa
        '''
    ).fetchall()
    row_dicts = [dict(row) for row in rows]

    def _member_avatar_color(name):
        if not name:
            return MEMBER_AVATAR_COLORS[0]
        total = sum(ord(ch) for ch in name.lower())
        return MEMBER_AVATAR_COLORS[total % len(MEMBER_AVATAR_COLORS)]

    members_data = []
    for row in row_dicts:
        has_shownotes_account = bool(row['user_id'])
        has_public_profile = bool(has_shownotes_account and row['profile_show_profile'])
        display_name = (
            row['member_display_name']
            or row['username']
            or row['plex_username']
        )
        avatar_url = row['member_avatar_url'] or row['profile_photo_url']

        members_data.append({
            'plex_username': row['plex_username'],
            'display_name': display_name,
            'avatar_url': avatar_url,
            'avatar_color': row['member_avatar_color'] or _member_avatar_color(display_name),
            'bio': row['bio'],
            'username': row['username'],
            'event_count': row['event_count'] or 0,
            'play_count': row['play_count'] or 0,
            'title_count': row['title_count'] or 0,
            'last_seen': row['last_seen'],
            'has_shownotes_account': has_shownotes_account,
            'has_public_profile': has_public_profile,
            'profile_url': (
                url_for('main.public_profile', username=row['username'])
                if has_public_profile else None
            ),
        })

    if member_filter == 'shownotes':
        members_data = [m for m in members_data if m['has_shownotes_account']]
    elif member_filter == 'plex_only':
        members_data = [m for m in members_data if not m['has_shownotes_account']]

    if sort_key == 'alphabetical':
        members_data.sort(key=lambda m: (m['display_name'].lower(), m['plex_username'].lower()))
    elif sort_key == 'most_active':
        members_data.sort(
            key=lambda m: (-m['play_count'], -(m['event_count']), m['display_name'].lower())
        )
    else:
        members_data.sort(
            key=lambda m: (
                m['last_seen'] is not None,
                str(m['last_seen']) if m['last_seen'] else '',
                m['play_count'],
                m['display_name'].lower(),
            ),
            reverse=True
        )

    totals = {
        'all': len(row_dicts),
        'shownotes': sum(1 for row in row_dicts if row['user_id']),
        'plex_only': sum(1 for row in row_dicts if not row['user_id']),
        'plays': sum((row['play_count'] or 0) for row in row_dicts),
    }

    filter_options = [
        {
            'label': 'All',
            'value': 'all',
            'count': totals['all'],
            'active': member_filter == 'all',
            'url': url_for('main.members', filter='all', sort=sort_key),
        },
        {
            'label': 'ShowNotes users',
            'value': 'shownotes',
            'count': totals['shownotes'],
            'active': member_filter == 'shownotes',
            'url': url_for('main.members', filter='shownotes', sort=sort_key),
        },
        {
            'label': 'Plex only',
            'value': 'plex_only',
            'count': totals['plex_only'],
            'active': member_filter == 'plex_only',
            'url': url_for('main.members', filter='plex_only', sort=sort_key),
        },
    ]

    sort_options = [
        {
            'label': 'Recently active',
            'value': 'recently_active',
            'active': sort_key == 'recently_active',
            'url': url_for('main.members', filter=member_filter, sort='recently_active'),
        },
        {
            'label': 'Most active',
            'value': 'most_active',
            'active': sort_key == 'most_active',
            'url': url_for('main.members', filter=member_filter, sort='most_active'),
        },
        {
            'label': 'Alphabetical',
            'value': 'alphabetical',
            'active': sort_key == 'alphabetical',
            'url': url_for('main.members', filter=member_filter, sort='alphabetical'),
        },
    ]

    return render_template(
        'members.html',
        members=members_data,
        filter_options=filter_options,
        sort_options=sort_options,
        member_filter=member_filter,
        sort_key=sort_key,
        total_member_count=totals['all'],
        shownotes_member_count=totals['shownotes'],
        plex_only_member_count=totals['plex_only'],
        total_play_count=totals['plays'],
    )


def _build_public_profile_context(db, viewed_user, member_id=None):
    """Shared logic for building public profile context for a user/member."""
    uid = viewed_user['id']

    # Favorites — scoped to the specific member if given, otherwise default member
    favorites = []
    if viewed_user['profile_show_favorites']:
        if member_id:
            favorites = db.execute('''
                SELECT s.id as show_db_id, s.tmdb_id, s.title, s.year, s.status,
                       s.poster_url, s.overview, uf.added_at
                FROM user_favorites uf
                JOIN sonarr_shows s ON s.id = uf.show_id
                WHERE uf.user_id = ? AND uf.member_id = ? AND uf.is_dropped = 0
                ORDER BY uf.added_at DESC
                LIMIT 20
            ''', (uid, member_id)).fetchall()
        else:
            favorites = db.execute('''
                SELECT s.id as show_db_id, s.tmdb_id, s.title, s.year, s.status,
                       s.poster_url, s.overview, uf.added_at
                FROM user_favorites uf
                JOIN sonarr_shows s ON s.id = uf.show_id
                JOIN household_members hm ON hm.id = uf.member_id AND hm.is_default = 1
                WHERE uf.user_id = ? AND uf.is_dropped = 0
                ORDER BY uf.added_at DESC
                LIMIT 20
            ''', (uid,)).fetchall()

    # Public lists — not member-scoped
    lists = []
    if viewed_user.get('profile_show_lists', 1):
        lists = db.execute('''
            SELECT id, name, description, updated_at,
                   (SELECT COUNT(*) FROM user_list_items WHERE list_id = user_lists.id) as item_count
            FROM user_lists
            WHERE user_id = ? AND is_public = 1
            ORDER BY updated_at DESC
        ''', (uid,)).fetchall()

    # Watch stats — account-level (Plex doesn't distinguish sub-profiles)
    watch_stats = None
    if viewed_user['profile_show_stats']:
        watch_stats = db.execute('''
            SELECT
                COUNT(DISTINCT CASE WHEN event_type IN ('media.play','media.scrobble') THEN show_title END) as unique_shows,
                COUNT(CASE WHEN event_type = 'media.scrobble' THEN 1 END) as completed_episodes,
                ROUND(SUM(CASE WHEN event_type = 'media.scrobble' THEN duration_ms ELSE 0 END) / 3600000.0, 1) as total_hours
            FROM plex_activity_log
            WHERE plex_username = ?
        ''', (viewed_user.get('plex_username', ''),)).fetchone()

    # Recent activity — account-level
    recent_activity = []
    if viewed_user['profile_show_activity']:
        recent_activity = db.execute('''
            SELECT show_title, title as episode_title, season_episode,
                   event_type, event_timestamp
            FROM plex_activity_log
            WHERE plex_username = ? AND event_type IN ('media.play','media.scrobble')
            ORDER BY event_timestamp DESC
            LIMIT 10
        ''', (viewed_user.get('plex_username', ''),)).fetchall()

    return dict(favorites=favorites, lists=lists, watch_stats=watch_stats, recent_activity=recent_activity)


@main_bp.route('/members/<username>')
@login_required
def public_profile(username):
    """Public profile page — default member of a user account."""
    db = database.get_db()
    viewed_user = db.execute(
        'SELECT * FROM users WHERE username = ? AND is_active = 1', (username,)
    ).fetchone()
    if not viewed_user:
        abort(404)
    if not viewed_user['profile_show_profile']:
        flash('This profile is private.', 'info')
        return redirect(url_for('main.members'))

    viewed_user = dict(viewed_user)
    dm = db.execute(
        'SELECT id, avatar_url, avatar_color, display_name FROM household_members WHERE user_id = ? AND is_default = 1',
        (viewed_user['id'],)
    ).fetchone()
    viewed_user['member_id'] = dm['id'] if dm else None
    viewed_user['avatar_url'] = dm['avatar_url'] if dm else None
    viewed_user['avatar_color'] = (dm['avatar_color'] if dm else None) or '#0ea5e9'
    viewed_user['display_name'] = dm['display_name'] if dm else viewed_user['username']
    viewed_user['plex_member_since'] = viewed_user.get('plex_joined_at') or viewed_user.get('created_at')
    viewed_user['is_self'] = (session.get('user_id') == viewed_user['id'])
    viewed_user['is_subprofile'] = False
    viewed_user['sub_profiles'] = db.execute(
        'SELECT id, display_name, avatar_url, avatar_color FROM household_members WHERE user_id=? AND is_default=0',
        (viewed_user['id'],)
    ).fetchall()

    ctx = _build_public_profile_context(db, viewed_user, member_id=viewed_user['member_id'])
    stats = _get_profile_stats(db)
    return render_template('public_profile.html', viewed_user=viewed_user, **ctx, **stats)


@main_bp.route('/members/<username>/<int:member_id>')
@login_required
def public_subprofile(username, member_id):
    """Public profile page for a specific household sub-profile."""
    db = database.get_db()
    viewed_user = db.execute(
        'SELECT * FROM users WHERE username = ? AND is_active = 1', (username,)
    ).fetchone()
    if not viewed_user:
        abort(404)
    if not viewed_user['profile_show_profile']:
        flash('This profile is private.', 'info')
        return redirect(url_for('main.members'))

    member = db.execute(
        'SELECT * FROM household_members WHERE id = ? AND user_id = ? AND is_default = 0',
        (member_id, viewed_user['id'])
    ).fetchone()
    if not member:
        abort(404)

    viewed_user = dict(viewed_user)
    viewed_user['member_id'] = member['id']
    viewed_user['avatar_url'] = member['avatar_url']
    viewed_user['avatar_color'] = member['avatar_color'] or '#0ea5e9'
    viewed_user['display_name'] = member['display_name']
    viewed_user['plex_member_since'] = viewed_user.get('plex_joined_at') or viewed_user.get('created_at')
    viewed_user['is_self'] = (session.get('user_id') == viewed_user['id'] and session.get('member_id') == member_id)
    viewed_user['is_subprofile'] = True
    viewed_user['parent_username'] = username
    viewed_user['sub_profiles'] = []  # not shown on sub-profile pages

    ctx = _build_public_profile_context(db, viewed_user, member_id=member_id)
    stats = _get_profile_stats(db)
    return render_template('public_profile.html', viewed_user=viewed_user, **ctx, **stats)
