import requests
import json
from flask import current_app, url_for
from . import database
from .utils import _trigger_image_cache

def get_all_radarr_movies():
    """
    Fetches a list of all movies from the configured Radarr instance.

    Communicates with the Radarr API to retrieve the complete movie library.

    Returns:
        list or None: A list of dictionaries, where each dictionary represents a movie.
                      Returns None if Radarr is not configured or an error occurs.
    """
    radarr_url = None
    radarr_api_key = None
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
        radarr_api_key = database.get_setting('radarr_api_key')

    if not radarr_url or not radarr_api_key:
        current_app.logger.error("get_all_radarr_movies: Radarr URL or API key not configured.")
        return None

    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"
    headers = {"X-Api-Key": radarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_all_radarr_movies: Timeout connecting to Radarr at {endpoint}")
        return None
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_all_radarr_movies: Connection error connecting to Radarr at {endpoint}")
        return None
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_all_radarr_movies: HTTP error fetching Radarr movies: {e}. Response: {e.response.text if e.response else 'No response'}")
        return None
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_all_radarr_movies: Generic error fetching Radarr movies: {e}")
        return None
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_all_radarr_movies: Error decoding Radarr movies JSON response: {e}")
        return None


def sync_radarr_library():
    """
    Synchronizes the entire Radarr library with the local database.

    This function mirrors the functionality of `sync_sonarr_library` but for movies:
    1.  Fetches all movies from the Radarr API.
    2.  Iterates through each movie and "upserts" its data into the `radarr_movies` table.
    3.  Queues poster and fanart images for background caching.
    4.  Removes any movies from the local database that no longer exist in Radarr.

    This is typically triggered manually from the admin panel.

    Returns:
        int: The number of movies that were successfully processed and synced.
    """
    current_app.logger.info("Starting Radarr library synchronization with new details...")
    movies_synced_count = 0
    movies_added_count = 0
    movies_updated_count = 0

    all_radarr_movies = get_all_radarr_movies()
    if not all_radarr_movies:
        current_app.logger.warning("sync_radarr_library: No movies returned from Radarr or Radarr not configured.")
        with current_app.app_context():
            conn = database.get_db_connection()
            try:
                database.update_sync_status(conn, 'radarr', 'failed' if not database.get_setting('radarr_url') else 'success_no_data')
            finally:
                conn.close()
        return {'status': 'warning', 'message': 'No movies returned from Radarr or Radarr not configured.', 'synced': 0, 'added': 0, 'updated': 0}

    radarr_url = None
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
        conn = database.get_db_connection()
    
    try:
        cursor = conn.cursor()
        for movie_data in all_radarr_movies:
            radarr_movie_id = movie_data.get('id')
            if not radarr_movie_id:
                current_app.logger.warning(f"sync_radarr_library: Movie data missing 'id'. Skipping. Data: {movie_data.get('title', 'N/A')}")
                continue

            # Extract poster and fanart URLs
            poster_url = None
            fanart_url = None
            if movie_data.get('images'):
                for image in movie_data['images']:
                    # Prefer remoteUrl (absolute) over url (relative)
                    img_src = image.get('remoteUrl') or image.get('url')
                    if img_src and img_src.startswith('/') and radarr_url:
                        img_src = f"{radarr_url.rstrip('/')}{img_src}"
                    
                    if image.get('coverType') == 'poster':
                        poster_url = img_src
                    elif image.get('coverType') == 'fanart':
                        fanart_url = img_src

            # Safely extract nested rating info
            ratings_data = movie_data.get('ratings', {})
            imdb_rating_info = ratings_data.get('imdb', {})
            tmdb_rating_info = ratings_data.get('tmdb', {})
            rt_rating_info = ratings_data.get('rottenTomatoes', {})

            # Safely extract original language name
            original_language_obj = movie_data.get('originalLanguage', {})
            original_language_name = original_language_obj.get('name')

            # Convert genres list to JSON string
            genres_list = movie_data.get('genres', [])
            genres_json = json.dumps(genres_list) if genres_list else None

            movie_to_insert = {
                'radarr_id': radarr_movie_id,
                'title': movie_data.get('title'),
                'year': movie_data.get('year'),
                'tmdb_id': movie_data.get('tmdbId'),
                'imdb_id': movie_data.get('imdbId'),
                'overview': movie_data.get('overview'),
                'poster_url': poster_url,
                'fanart_url': fanart_url,
                'release_date': movie_data.get('releaseDate'), # Or physicalRelease / digitalRelease if preferred
                'original_language_name': original_language_name,
                'studio': movie_data.get('studio'),
                'runtime': movie_data.get('runtime'),
                'status': movie_data.get('status'),
                'genres': genres_json,
                'certification': movie_data.get('certification'),
                'popularity': movie_data.get('popularity'),
                'original_title': movie_data.get('originalTitle'),
                'ratings_imdb_value': imdb_rating_info.get('value'),
                'ratings_imdb_votes': imdb_rating_info.get('votes'),
                'ratings_tmdb_value': tmdb_rating_info.get('value'),
                'ratings_tmdb_votes': tmdb_rating_info.get('votes'),
                'ratings_rottenTomatoes_value': rt_rating_info.get('value'),
                'ratings_rottenTomatoes_votes': rt_rating_info.get('votes'),
                # Ensure all columns from migration 005 are covered
            }

            # Check if movie exists
            cursor.execute("SELECT id FROM radarr_movies WHERE radarr_id = ?", (radarr_movie_id,))
            existing_movie = cursor.fetchone()

            # Construct columns and placeholders for insert/update dynamically
            # This ensures that if a key is None from Radarr, it's inserted as NULL
            # (assuming the DB column allows NULLs, which they should for optional fields)
            
            db_columns = list(movie_to_insert.keys())
            db_values = [movie_to_insert.get(col) for col in db_columns]

            if existing_movie:
                set_clause = ", ".join([f"{col} = ?" for col in db_columns if col != 'radarr_id'])
                sql_query = f"UPDATE radarr_movies SET {set_clause} WHERE radarr_id = ?"
                
                # Prepare values for update: all values except radarr_movie_id, then radarr_movie_id at the end for WHERE clause
                update_values_list = [movie_to_insert.get(col) for col in db_columns if col != 'radarr_id']
                update_values_list.append(radarr_movie_id)
                
                cursor.execute(sql_query, tuple(update_values_list))
                if cursor.rowcount > 0:
                    movies_updated_count += 1
                movie_db_id = existing_movie[0] # Get ID if exists
            else:
                placeholders = ', '.join(['?'] * len(db_columns))
                sql_query = f"INSERT INTO radarr_movies ({', '.join(db_columns)}) VALUES ({placeholders}) RETURNING id" # Added RETURNING id
                cursor.execute(sql_query, tuple(db_values))
                result = cursor.fetchone()
                if result and result[0]:
                    movie_db_id = result[0]
                    movies_added_count += 1
                else:
                    current_app.logger.error(f"sync_radarr_library: Failed to get ID for new movie Radarr ID {radarr_movie_id}. Skipping image queue for this movie.")
                    conn.rollback() # Rollback this movie's transaction
                    continue # Skip to next movie
            
            movies_synced_count += 1

            # Trigger image caching directly (only if we have a request context)
            movie_tmdb_id = movie_to_insert.get('tmdb_id')
            if movie_db_id and movie_tmdb_id:
                try:
                    if poster_url:
                        proxy_poster_url = url_for('main.image_proxy', type='poster', id=movie_tmdb_id)
                        _trigger_image_cache(proxy_poster_url, item_title_for_logging=f"Poster for {movie_to_insert.get('title')}")
                    if fanart_url:
                        proxy_fanart_url = url_for('main.image_proxy', type='background', id=movie_tmdb_id)
                        _trigger_image_cache(proxy_fanart_url, item_title_for_logging=f"Fanart for {movie_to_insert.get('title')}")
                except RuntimeError as e:
                    # Skip image caching if we're outside a request context (e.g., webhook background thread)
                    current_app.logger.debug(f"Skipping image caching for movie '{movie_to_insert.get('title')}' - no request context: {e}")
            elif not movie_tmdb_id:
                 current_app.logger.warning(f"Skipping image trigger for movie '{movie_to_insert.get('title')}' due to missing TMDB ID.")

        conn.commit()
        database.update_sync_status(conn, 'radarr', 'success')
        current_app.logger.info(f"Radarr library synchronization finished. Synced: {movies_synced_count}, Added: {movies_added_count}, Updated: {movies_updated_count}")
        return {'status': 'success', 'message': 'Radarr library synced successfully.', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}

    except sqlite3.Error as e:
        current_app.logger.error(f"sync_radarr_library: Database error during Radarr sync: {e}")
        if conn: conn.rollback()
        temp_conn_for_status = None
        try:
            with current_app.app_context():
                 temp_conn_for_status = database.get_db_connection()
            database.update_sync_status(temp_conn_for_status, 'radarr', 'failed_db_error')
        except Exception as e_status:
            current_app.logger.error(f"sync_radarr_library: Failed to update sync status after DB error: {e_status}")
        finally:
            if temp_conn_for_status: temp_conn_for_status.close()
        return {'status': 'error', 'message': f'Database error: {e}', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}
    except Exception as e:
        current_app.logger.error(f"sync_radarr_library: An unexpected error occurred during Radarr sync: {e}")
        if conn: conn.rollback()
        temp_conn_for_status_unexpected = None
        try:
            with current_app.app_context():
                 temp_conn_for_status_unexpected = database.get_db_connection()
            database.update_sync_status(temp_conn_for_status_unexpected, 'radarr', 'failed_unexpected_error')
        except Exception as e_status_unexpected:
            current_app.logger.error(f"sync_radarr_library: Failed to update sync status after unexpected error: {e_status_unexpected}")
        finally:
            if temp_conn_for_status_unexpected: temp_conn_for_status_unexpected.close()
        return {'status': 'error', 'message': f'Unexpected error: {e}', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}
    finally:
        if conn:
            conn.close()

# --- Jinja Filters ---
import datetime

