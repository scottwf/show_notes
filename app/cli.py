import click
from flask.cli import AppGroup, with_appcontext
import time
import os
import requests
from . import database # Assuming database.py is in the same directory or app package
from flask import current_app

image_cli = AppGroup('image', help='Image processing commands.')

def get_required_api_key(service_name):
    # Helper to get API key, adapted from image_proxy logic if needed
    # This is a placeholder, actual API key retrieval might need more context
    # or be part of the image_url itself if it's a signed URL.
    # For now, let's assume direct image URLs from Sonarr/Radarr don't always need API keys
    # in the URL itself, but the proxy fetches them if needed.
    # The worker will need to replicate the proxy's fetching logic.
    settings = database.get_db().execute(
        'SELECT radarr_url, sonarr_url, radarr_api_key, sonarr_api_key FROM settings LIMIT 1'
    ).fetchone()
    if service_name == 'sonarr' and settings and settings['sonarr_api_key']:
        return settings['sonarr_api_key'], settings['sonarr_url']
    elif service_name == 'radarr' and settings and settings['radarr_api_key']:
        return settings['radarr_api_key'], settings['radarr_url']
    return None, None

@image_cli.command('process-queue')
@with_appcontext
@click.option('--limit', default=10, help='Number of images to process in this run.')
@click.option('--delay', default=2, help='Delay in seconds between processing each image.')
@click.option('--max-attempts', default=3, help='Max attempts for a failed image.')
def process_image_queue(limit, delay, max_attempts):
    """Processes images from the image_cache_queue."""
    click.echo(f"Starting image queue processing: limit={limit}, delay={delay}, max_attempts={max_attempts}")

    db = database.get_db()

    # Fetch tasks: status 'pending' OR ('failed' AND attempts < max_attempts)
    # Order by created_at to process older items first.
    sql_fetch = f"""
        SELECT id, item_type, item_db_id, image_url, image_kind, target_filename, attempts
        FROM image_cache_queue
        WHERE status = 'pending' OR (status = 'failed' AND attempts < ?)
        ORDER BY created_at ASC
        LIMIT ?
    """

    try:
        tasks = db.execute(sql_fetch, (max_attempts, limit)).fetchall()
    except Exception as e:
        click.echo(f"Error fetching tasks from queue: {e}")
        return

    if not tasks:
        click.echo("No pending images in the queue to process.")
        return

    click.echo(f"Found {len(tasks)} images to process.")

    cache_dir_base = os.path.join(current_app.static_folder, 'poster_cache') # Matches image_proxy
    os.makedirs(cache_dir_base, exist_ok=True)

    for task in tasks:
        task_id = task['id']
        image_url = task['image_url']
        target_filename = task['target_filename']
        item_type = task['item_type'] # 'show' or 'movie'

        click.echo(f"Processing task ID {task_id}: {image_url} -> {target_filename}")

        # Update status to 'processing' and increment attempts
        try:
            db.execute(
                "UPDATE image_cache_queue SET status = 'processing', attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (task_id,)
            )
            db.commit()
        except Exception as e:
            click.echo(f"Error updating task {task_id} to processing: {e}")
            db.rollback()
            continue # Skip to next task

        success = False
        try:
            # Determine if API key is needed based on image_url domain (simplified)
            headers = {}
            api_key, service_base_url = None, None

            # This logic needs to be robust. If image_url is from TMDB, no key.
            # If it's a relative /media_cover/... from Sonarr/Radarr, it needs base_url prepended and API key.
            # The image_url stored in queue should ideally be the full, directly fetchable URL.
            # The sync functions store 'final_poster_url' which should be absolute.

            # Let's refine how API keys are added, similar to image_proxy
            # We need to fetch Sonarr/Radarr base URLs from settings to compare
            # This part is crucial and needs to be correct.

            # Assuming image_url in queue is already the absolute URL that image_proxy would receive.
            # Now, replicate image_proxy's logic for adding API key if the URL matches service base.
            # (This was simplified in placeholder get_required_api_key, let's make it more direct here)

            settings = db.execute('SELECT radarr_url, sonarr_url, radarr_api_key, sonarr_api_key FROM settings LIMIT 1').fetchone()
            radarr_base = settings['radarr_url'].rstrip('/') if settings and settings['radarr_url'] else None
            sonarr_base = settings['sonarr_url'].rstrip('/') if settings and settings['sonarr_url'] else None

            if sonarr_base and image_url.startswith(sonarr_base) and settings['sonarr_api_key']:
                headers['X-Api-Key'] = settings['sonarr_api_key']
                click.echo(f"Using Sonarr API key for {image_url}")
            elif radarr_base and image_url.startswith(radarr_base) and settings['radarr_api_key']:
                headers['X-Api-Key'] = settings['radarr_api_key']
                click.echo(f"Using Radarr API key for {image_url}")

            response = requests.get(image_url, stream=True, headers=headers, timeout=20) # Increased timeout for downloads
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            image_path = os.path.join(cache_dir_base, target_filename)

            with open(image_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            click.echo(f"Successfully downloaded and cached {target_filename}")
            success = True

        except requests.exceptions.RequestException as e:
            click.echo(f"Failed to download {image_url}: {e}")
        except IOError as e:
            click.echo(f"Failed to save image {target_filename}: {e}")
        except Exception as e:
            click.echo(f"An unexpected error occurred while processing {image_url}: {e}")

        # Update status to 'complete' or 'failed'
        new_status = 'complete' if success else 'failed'
        try:
            db.execute(
                "UPDATE image_cache_queue SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_status, task_id)
            )
            db.commit()
            click.echo(f"Task ID {task_id} marked as {new_status}.")
        except Exception as e:
            click.echo(f"Error updating task {task_id} to {new_status}: {e}")
            db.rollback()

        if tasks.index(task) < len(tasks) - 1: # Don't sleep after the last task
            click.echo(f"Waiting for {delay} seconds...")
            time.sleep(delay)

    click.echo("Image queue processing finished.")

def init_app(app):
    """Register CLI commands with the Flask app."""
    app.cli.add_command(image_cli)
