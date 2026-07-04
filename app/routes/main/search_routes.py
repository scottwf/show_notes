from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app
)
from flask_login import login_required

from ... import database
from . import main_bp


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
