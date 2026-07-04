from flask import render_template, url_for, abort
from flask_login import login_required

from ... import database
from . import main_bp
from ._shared import _build_admin_service_links


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
