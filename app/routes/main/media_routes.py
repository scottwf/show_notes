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
    _build_admin_service_links,
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
