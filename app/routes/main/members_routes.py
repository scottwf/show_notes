from flask import (
    render_template, request, redirect, url_for, session, flash, abort
)
from flask_login import login_required

from ... import database
from . import main_bp
from ._shared import _get_profile_stats, MEMBER_AVATAR_COLORS


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
