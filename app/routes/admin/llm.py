import os
import glob
import time
import secrets
import socket
import requests
from openai import OpenAI
from flask import (
    render_template, request, redirect, url_for, session, jsonify, flash,
    current_app, Response, stream_with_context, abort
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from functools import wraps

from ... import database
from ...database import get_db, close_db, get_setting, set_setting, update_sync_status
from ...utils import (
    sync_sonarr_library, sync_radarr_library,
    test_sonarr_connection, test_radarr_connection, test_bazarr_connection, test_ollama_connection,
    test_sonarr_connection_with_params, test_radarr_connection_with_params,
    test_bazarr_connection_with_params, test_ollama_connection_with_params,
    test_pushover_notification_with_params,
    send_ntfy_notification,
    sync_tautulli_watch_history,
    test_tautulli_connection, test_tautulli_connection_with_params,
    test_jellyseer_connection, test_jellyseer_connection_with_params,
    test_thetvdb_connection, test_thetvdb_connection_with_params,
    get_ollama_models,
    convert_utc_to_user_timezone, get_user_timezone,
    get_jellyseer_user_requests,
)
from ...parse_subtitles import process_all_subtitles
from . import admin_bp, admin_required, ADMIN_SEARCHABLE_ROUTES

@admin_bp.route('/api/ollama-models')
@login_required
@admin_required
def ollama_models_api():
    """API endpoint to fetch available Ollama models"""
    import requests
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL parameter required"}), 400

    try:
        response = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            model_names = [model.get('name') for model in models if model.get('name')]
            return jsonify({"models": model_names})
        else:
            return jsonify({"error": f"Ollama server returned status {response.status_code}"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "Connection timeout"}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Ollama server"}), 500
    except Exception as e:
        current_app.logger.error(f"Error fetching Ollama models: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/test-ollama-models')
@login_required
@admin_required
def test_ollama_models_route():
    """Debug route to test Ollama model fetching"""
    models = get_ollama_models()
    return jsonify({"models": models, "count": len(models)})

@admin_bp.route('/api/summary-queue-status')
@login_required
@admin_required
def summary_queue_status():
    """API endpoint to get summary generation queue status."""
    from app.summary_services import get_summary_queue_status
    return jsonify(get_summary_queue_status())

@admin_bp.route('/api/trigger-summary-generation', methods=['POST'])
@login_required
@admin_required
def trigger_summary_generation():
    """Manually trigger summary generation in a background thread."""
    import threading
    from app.summary_services import process_summary_queue

    app = current_app._get_current_object()

    def run_summaries():
        process_summary_queue(app)

    thread = threading.Thread(target=run_summaries)
    thread.daemon = True
    thread.start()
    return jsonify({"status": "started", "message": "Summary generation started in background"})

@admin_bp.route('/api/generate-season-summary', methods=['POST'])
@login_required
@admin_required
def generate_single_season_summary():
    """Generate summary for a specific show/season immediately."""
    from app.summary_services import generate_season_summary
    tmdb_id = request.json.get('tmdb_id')
    season_number = request.json.get('season_number')
    if not tmdb_id or season_number is None:
        return jsonify({"error": "tmdb_id and season_number required"}), 400

    success, error = generate_season_summary(int(tmdb_id), int(season_number))
    if success:
        return jsonify({"status": "completed", "message": f"Summary generated for tmdb_id={tmdb_id} S{season_number}"})
    else:
        return jsonify({"status": "failed", "error": error}), 500

@admin_bp.route('/api/latest-episode')
@login_required
@admin_required
def get_latest_episode():
    """
    API endpoint to get the latest aired episode for a show.
    """
    tmdb_id = request.args.get('tmdb_id')
    if not tmdb_id:
        return jsonify({'error': 'TMDB ID is required'}), 400

    try:
        db = get_db()
        
        # Get the latest aired episode for this show (only episodes that have actually aired)
        # We need to join through the seasons table to get season numbers
        latest_episode = db.execute('''
            SELECT s.season_number, e.episode_number, e.air_date_utc
            FROM sonarr_episodes e
            JOIN sonarr_seasons s ON e.season_id = s.id
            JOIN sonarr_shows sh ON s.show_id = sh.id
            WHERE sh.tmdb_id = ? 
            AND e.air_date_utc IS NOT NULL 
            AND e.air_date_utc != ''
            AND e.air_date_utc <= datetime('now')
            ORDER BY s.season_number DESC, e.episode_number DESC
            LIMIT 1
        ''', (tmdb_id,)).fetchone()
        
        if latest_episode:
            return jsonify({
                'season': latest_episode['season_number'],
                'episode': latest_episode['episode_number'],
                'air_date': latest_episode['air_date_utc']
            })
        else:
            # If no aired episodes found, get the latest episode regardless of air date
            latest_episode = db.execute('''
                SELECT s.season_number, e.episode_number
                FROM sonarr_episodes e
                JOIN sonarr_seasons s ON e.season_id = s.id
                JOIN sonarr_shows sh ON s.show_id = sh.id
                WHERE sh.tmdb_id = ? 
                ORDER BY s.season_number DESC, e.episode_number DESC
                LIMIT 1
            ''', (tmdb_id,)).fetchone()
            
            if latest_episode:
                return jsonify({
                    'season': latest_episode['season_number'],
                    'episode': latest_episode['episode_number'],
                    'air_date': None
                })
            else:
                return jsonify({'error': 'No episodes found for this show'}), 404
                
    except Exception as e:
        current_app.logger.error(f"Error fetching latest episode: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/get-character-info', methods=['POST'])
@login_required
@admin_required
def get_character_info():
    """
    API endpoint to get character information from the database for testing.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    character_name = data.get('character', '')
    show_title = data.get('show', '')
    season = data.get('season', 1)
    episode = data.get('episode', 1)

    if not character_name or not show_title:
        return jsonify({'error': 'Character and show are required'}), 400

    db = get_db()
    
    try:
        # First, find the show by title
        show_row = db.execute('SELECT tmdb_id, title, year, overview FROM sonarr_shows WHERE title LIKE ?', (f'%{show_title}%',)).fetchone()
        
        if not show_row:
            current_app.logger.warning(f"Show not found for title: {show_title}")
            return jsonify({'error': 'Show not found', 'searched_title': show_title}), 404
        
        show_tmdb_id = show_row['tmdb_id']
        current_app.logger.info(f"Found show: {show_row['title']} (TMDB ID: {show_tmdb_id})")
        
        # Find the character by name and show
        character_row = db.execute('''
            SELECT ec.actor_name, ec.character_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            AND ec.character_name LIKE ?
            LIMIT 1
        ''', (show_tmdb_id, season, episode, f'%{character_name}%')).fetchone()
        
        # Also check what characters exist for this show/episode for debugging
        all_characters = db.execute('''
            SELECT ec.character_name, ec.actor_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            LIMIT 10
        ''', (show_tmdb_id, season, episode)).fetchall()
        
        result = {
            'character_name': character_name,
            'show_title': show_title,
            'season': season,
            'episode': episode,
            'actor_name': None,
            'show_year': show_row['year'],
            'show_overview': show_row['overview'],
            'debug_info': {
                'searched_character': character_name,
                'found_show': show_row['title'],
                'show_tmdb_id': show_tmdb_id,
                'available_characters': [{'name': c['character_name'], 'actor': c['actor_name']} for c in all_characters]
            }
        }
        
        if character_row:
            result['actor_name'] = character_row['actor_name']
            current_app.logger.info(f"Found character: {character_row['character_name']} played by {character_row['actor_name']}")
        else:
            current_app.logger.warning(f"Character not found: {character_name} in {show_title} S{season}E{episode}")
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching character info: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/replace-variables', methods=['POST'])
@login_required
@admin_required
def replace_variables():
    """
    API endpoint to replace variables in a prompt with sample data for testing.
    """
    data = request.get_json()
    if not data or 'prompt_text' not in data:
        return jsonify({'error': 'Missing prompt_text'}), 400

    prompt_text = data['prompt_text']
    
    # Sample data for variable replacement (using single brackets)
    sample_data = {
        '{character}': data.get('character', 'John Doe'),
        '{show}': data.get('show', 'Breaking Bad'),
        '{season}': str(data.get('season', 2)),
        '{episode}': str(data.get('episode', 5)),
        '{actor}': data.get('actor', 'Bryan Cranston'),
        '{year}': str(data.get('year', 2008)),
        '{genre}': data.get('genre', 'Drama'),
        '{overview}': data.get('overview', 'A high school chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.'),
        '{episode_title}': data.get('episode_title', 'The One Where Walter Gets Angry'),
        '{episode_overview}': data.get('episode_overview', 'Walter confronts his family about his secret life while dealing with the consequences of his actions.'),
        '{air_date}': data.get('air_date', 'March 15, 2009'),
        '{other_characters}': data.get('other_characters', 'Jesse Pinkman, Skyler White, Hank Schrader')
    }

    # Replace variables in the prompt
    replaced_prompt = prompt_text
    for variable, replacement in sample_data.items():
        replaced_prompt = replaced_prompt.replace(variable, replacement)

    return jsonify({
        'original_prompt': prompt_text,
        'replaced_prompt': replaced_prompt,
        'variables_found': [var for var in sample_data.keys() if var in prompt_text]
    })

@admin_bp.route('/api/prompt-history/<int:prompt_id>')
@login_required
@admin_required
def get_prompt_history(prompt_id):
    """
    API endpoint to retrieve the version history for a specific prompt.
    """
    db = get_db()
    try:
        history_rows = db.execute(
            'SELECT * FROM prompt_history WHERE prompt_id = ? ORDER BY timestamp DESC',
            (prompt_id,)
        ).fetchall()

        history = [dict(row) for row in history_rows]

        return jsonify(history)
    except Exception as e:
        current_app.logger.error(f"Error fetching history for prompt_id {prompt_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

@admin_bp.route('/api/characters-for-show')
@login_required
@admin_required
def api_characters_for_show():
    """
    API endpoint to get all unique character names for a given show.
    Accepts a 'tmdb_id' query parameter.
    First tries episode_characters table, then falls back to Plex activity log.
    """
    show_tmdb_id = request.args.get('tmdb_id')
    if not show_tmdb_id:
        return jsonify({'error': 'tmdb_id parameter is required'}), 400

    db = get_db()
    try:
        # First, try to get characters from episode_characters table
        characters = db.execute(
            "SELECT DISTINCT character_name FROM episode_characters WHERE show_tmdb_id = ?",
            (show_tmdb_id,)
        ).fetchall()

        character_names = [row['character_name'] for row in characters if row['character_name']]
        
        # If no characters found in episode_characters, try Plex activity log fallback
        if not character_names:
            # Get show title from sonarr_shows
            show_row = db.execute('SELECT title FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id,)).fetchone()
            if show_row:
                show_title = show_row['title']
                
                # Get the most recent Plex activity log entry for this show
                plex_row = db.execute(
                    'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? ORDER BY event_timestamp DESC LIMIT 1',
                    (show_title,)
                ).fetchone()
                
                if plex_row:
                    import json
                    try:
                        payload = json.loads(plex_row['raw_payload'])
                        metadata = payload.get('Metadata', {})
                        roles = metadata.get('Role', [])
                        
                        # Extract character names from Plex data
                        plex_characters = []
                        for role in roles:
                            character_name = role.get('role')
                            if character_name:
                                plex_characters.append(character_name)
                        
                        character_names = plex_characters
                        current_app.logger.info(f"Found {len(character_names)} characters from Plex data for show {show_title}")
                        
                    except (json.JSONDecodeError, KeyError) as e:
                        current_app.logger.error(f"Error parsing Plex data for show {show_title}: {e}")

        return jsonify(character_names)

    except Exception as e:
        current_app.logger.error(f"Error fetching characters for show {show_tmdb_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

# ============================================================================
# API USAGE
# ============================================================================




def _get_show_summaries_schema_mode(db):
    """Return the summary schema mode used by show_summaries."""
    try:
        columns = {
            row['name']
            for row in db.execute("PRAGMA table_info(show_summaries)").fetchall()
        }
    except Exception:
        return 'missing'

    if {'show_id', 'season_number', 'episode_number'}.issubset(columns):
        return 'episode'
    if {'tmdb_id', 'show_title'}.issubset(columns):
        return 'legacy'
    return 'unknown'

@admin_bp.route('/ai')
@login_required
@admin_required
def ai_settings():
    """AI admin page with settings, prompts, generate, and logs tabs."""
    db = get_db()

    # Load current settings
    settings_row = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    settings = dict(settings_row) if settings_row else {}

    # Load prompts
    prompts = db.execute('SELECT * FROM llm_prompts ORDER BY id').fetchall()

    # Load shows for generate tab
    shows = db.execute(
        'SELECT id, title, season_count, status FROM sonarr_shows ORDER BY title'
    ).fetchall()

    summary_schema_mode = _get_show_summaries_schema_mode(db)

    # Summary counts per show
    if summary_schema_mode == 'episode':
        summary_counts = db.execute('''
            SELECT
                s.id as show_id,
                s.title,
                SUM(CASE WHEN sm.episode_number IS NOT NULL THEN 1 ELSE 0 END) as episode_count,
                SUM(CASE WHEN sm.episode_number IS NULL AND sm.season_number IS NOT NULL THEN 1 ELSE 0 END) as season_count
            FROM show_summaries sm
            JOIN sonarr_shows s ON sm.show_id = s.id
            GROUP BY sm.show_id
            ORDER BY s.title
        ''').fetchall()
    elif summary_schema_mode == 'legacy':
        summary_counts = db.execute('''
            SELECT
                NULL as show_id,
                show_title as title,
                COUNT(*) as episode_count,
                0 as season_count
            FROM show_summaries
            GROUP BY tmdb_id, show_title
            ORDER BY show_title
        ''').fetchall()
    else:
        summary_counts = []

    feedback_map = {}
    try:
        feedback_rows = db.execute('''
            SELECT
                summary_type,
                show_id,
                COALESCE(season_number, 0) as season_number,
                SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as upvotes,
                SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as downvotes,
                SUM(CASE WHEN report_type IS NOT NULL THEN 1 ELSE 0 END) as reports
            FROM summary_feedback
            GROUP BY summary_type, show_id, COALESCE(season_number, 0)
        ''').fetchall()
        feedback_map = {
            (row['summary_type'], row['show_id'], row['season_number']): row
            for row in feedback_rows
        }
    except Exception:
        feedback_map = {}

    summary_records = []
    if summary_schema_mode == 'episode':
        try:
            unified_summary_rows = db.execute('''
                SELECT
                    sm.id,
                    sm.show_id,
                    s.tmdb_id,
                    s.title,
                    sm.season_number,
                    sm.episode_number,
                    ep.id AS episode_id,
                    ep.title AS episode_title,
                    sm.status,
                    sm.provider,
                    sm.model,
                    sm.summary_text,
                    sm.error_message,
                    sm.created_at,
                    sm.updated_at
                FROM show_summaries sm
                JOIN sonarr_shows s ON s.id = sm.show_id
                LEFT JOIN sonarr_episodes ep
                    ON ep.show_id = sm.show_id
                   AND ep.season_number = sm.season_number
                   AND ep.episode_number = sm.episode_number
                ORDER BY sm.updated_at DESC
            ''').fetchall()
            for row in unified_summary_rows:
                if row['season_number'] is None and row['episode_number'] is None:
                    summary_type = 'show'
                    summary_type_label = 'Series'
                    feedback = feedback_map.get(('show', row['show_id'], 0))
                elif row['episode_number'] is None:
                    summary_type = 'season'
                    summary_type_label = 'Season'
                    feedback = feedback_map.get(('season', row['show_id'], row['season_number']))
                else:
                    summary_type = 'episode'
                    summary_type_label = 'Episode'
                    feedback = None

                summary_records.append({
                    'record_key': f"{summary_type}-{row['id']}",
                    'summary_type': summary_type,
                    'summary_type_label': summary_type_label,
                    'show_id': row['show_id'],
                    'tmdb_id': row['tmdb_id'],
                    'title': row['title'] or f"Show #{row['show_id']}",
                    'season_number': row['season_number'],
                    'episode_number': row['episode_number'],
                    'episode_id': row['episode_id'],
                    'episode_title': row['episode_title'],
                    'status': row['status'],
                    'provider': row['provider'],
                    'model': row['model'],
                    'updated_at': row['updated_at'],
                    'created_at': row['created_at'],
                    'summary_text': row['summary_text'],
                    'error_message': row['error_message'],
                    'upvotes': feedback['upvotes'] if feedback else 0,
                    'downvotes': feedback['downvotes'] if feedback else 0,
                    'reports': feedback['reports'] if feedback else 0,
                })
        except Exception:
            pass
    else:
        try:
            show_summary_rows = db.execute('''
                SELECT
                    sh.id,
                    sh.tmdb_id,
                    COALESCE(s.id, NULL) as show_id,
                    COALESCE(s.title, sh.show_title) as title,
                    sh.status,
                    sh.llm_provider as provider,
                    sh.llm_model as model,
                    sh.summary_text,
                    sh.error_message,
                    sh.created_at,
                    sh.updated_at
                FROM show_summaries sh
                LEFT JOIN sonarr_shows s ON s.tmdb_id = sh.tmdb_id
                ORDER BY sh.updated_at DESC
            ''').fetchall()
            for row in show_summary_rows:
                feedback = feedback_map.get(('show', row['show_id'], 0))
                summary_records.append({
                    'record_key': f"show-{row['id']}",
                    'summary_type': 'show',
                    'summary_type_label': 'Series',
                    'show_id': row['show_id'],
                    'tmdb_id': row['tmdb_id'],
                    'title': row['title'] or f"TMDB #{row['tmdb_id']}",
                    'season_number': None,
                    'episode_number': None,
                    'episode_id': None,
                    'episode_title': None,
                    'status': row['status'],
                    'provider': row['provider'],
                    'model': row['model'],
                    'updated_at': row['updated_at'],
                    'created_at': row['created_at'],
                    'summary_text': row['summary_text'],
                    'error_message': row['error_message'],
                    'upvotes': feedback['upvotes'] if feedback else 0,
                    'downvotes': feedback['downvotes'] if feedback else 0,
                    'reports': feedback['reports'] if feedback else 0,
                })
        except Exception:
            pass

        try:
            season_summary_rows = db.execute('''
                SELECT
                    ss.id,
                    ss.tmdb_id,
                    COALESCE(s.id, NULL) as show_id,
                    COALESCE(s.title, ss.show_title) as title,
                    ss.season_number,
                    ss.status,
                    ss.llm_provider as provider,
                    ss.llm_model as model,
                    ss.summary_text,
                    ss.error_message,
                    ss.created_at,
                    ss.updated_at
                FROM season_summaries ss
                LEFT JOIN sonarr_shows s ON s.tmdb_id = ss.tmdb_id
                ORDER BY ss.updated_at DESC
            ''').fetchall()
            for row in season_summary_rows:
                feedback = feedback_map.get(('season', row['show_id'], row['season_number']))
                summary_records.append({
                    'record_key': f"season-{row['id']}",
                    'summary_type': 'season',
                    'summary_type_label': 'Season',
                    'show_id': row['show_id'],
                    'tmdb_id': row['tmdb_id'],
                    'title': row['title'] or f"TMDB #{row['tmdb_id']}",
                    'season_number': row['season_number'],
                    'episode_number': None,
                    'episode_id': None,
                    'episode_title': None,
                    'status': row['status'],
                    'provider': row['provider'],
                    'model': row['model'],
                    'updated_at': row['updated_at'],
                    'created_at': row['created_at'],
                    'summary_text': row['summary_text'],
                    'error_message': row['error_message'],
                    'upvotes': feedback['upvotes'] if feedback else 0,
                    'downvotes': feedback['downvotes'] if feedback else 0,
                    'reports': feedback['reports'] if feedback else 0,
                })
        except Exception:
            pass

    # API usage logs (most recent 100)
    logs = db.execute(
        'SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT 100'
    ).fetchall()

    # Log stats
    log_stats = db.execute('''
        SELECT
            (SELECT COUNT(*) FROM api_usage) as total_calls,
            (SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage) as total_cost,
            (SELECT COUNT(*) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')) as week_calls,
            (SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')) as week_cost
    ''').fetchone()

    return render_template('admin_ai.html',
                           settings=settings,
                           prompts=prompts,
                           shows=shows,
                           summary_counts=summary_counts,
                           summary_records=summary_records,
                           summary_schema_mode=summary_schema_mode,
                           logs=logs,
                           log_stats=log_stats)


@admin_bp.route('/ai/save-settings', methods=['POST'])
@login_required
@admin_required
def ai_save_settings():
    """Save AI/LLM provider settings."""
    fields = ['preferred_llm_provider', 'ollama_url', 'ollama_model_name',
              'openai_api_key', 'openai_model_name',
              'openrouter_api_key', 'openrouter_model_name',
              'gemini_api_key', 'gemini_model_name',
              'llm_knowledge_cutoff_date', 'summary_length']

    for field in fields:
        value = request.form.get(field, '').strip()
        set_setting(field, value if value else None)

    # Checkbox booleans
    set_setting('summary_only_watched',    '1' if request.form.get('summary_only_watched') else '0')
    set_setting('summary_show_disclaimer', '1' if request.form.get('summary_show_disclaimer') else '0')

    flash('AI settings saved successfully.', 'success')
    return redirect(url_for('admin.ai_settings'))


@admin_bp.route('/ai/save-prompt', methods=['POST'])
@login_required
@admin_required
def ai_save_prompt():
    """Save an edited prompt template."""
    prompt_key = request.form.get('prompt_key')
    prompt_template = request.form.get('prompt_template', '').strip()

    if not prompt_key or not prompt_template:
        flash('Prompt key and template are required.', 'error')
        return redirect(url_for('admin.ai_settings'))

    db = get_db()
    db.execute(
        'UPDATE llm_prompts SET prompt_template = ?, updated_at = CURRENT_TIMESTAMP WHERE prompt_key = ?',
        (prompt_template, prompt_key)
    )
    db.commit()
    flash(f'Prompt "{prompt_key}" saved.', 'success')
    return redirect(url_for('admin.ai_settings'))


@admin_bp.route('/ai/reset-prompt', methods=['POST'])
@login_required
@admin_required
def ai_reset_prompt():
    """Reset a prompt to its default template."""
    data = request.json
    prompt_key = data.get('prompt_key')

    defaults = {
        "episode_summary": """Write a concise summary (2-3 paragraphs) of {show_title} Season {season_number}, Episode {episode_number}: "{episode_title}".

Here is the episode description for context: {episode_overview}

Focus on the key plot developments, character moments, and how this episode connects to the larger season arc. Write in past tense as a recap for someone who has already watched the episode. Do not include spoiler warnings.""",
        "season_recap": """Write a comprehensive season recap (3-5 paragraphs) for {show_title} Season {season_number}.

Here are summaries of the individual episodes for reference:
{episode_summaries}

Provide an engaging recap that covers the major storylines, character development, and key turning points of the season. Write in past tense as a recap for someone who has already watched the season. End with how the season concludes and any cliffhangers or setups for the next season. Do not include spoiler warnings."""
    }

    if prompt_key not in defaults:
        return jsonify({'success': False, 'error': 'Unknown prompt key'})

    db = get_db()
    db.execute(
        'UPDATE llm_prompts SET prompt_template = ?, updated_at = CURRENT_TIMESTAMP WHERE prompt_key = ?',
        (defaults[prompt_key], prompt_key)
    )
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/ai/test-connection', methods=['POST'])
@login_required
@admin_required
def ai_test_connection():
    """Test connection to an LLM provider."""
    data = request.json
    service = data.get('service')

    if service == 'ollama':
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})
        try:
            resp = requests.get(url.rstrip('/') + '/api/tags', timeout=10)
            if resp.status_code == 200:
                models = [m.get('name') for m in resp.json().get('models', []) if m.get('name')]
                return jsonify({'success': True, 'models': models})
            return jsonify({'success': False, 'error': f'HTTP {resp.status_code}'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    elif service == 'openai':
        api_key = data.get('api_key', '').strip()
        if not api_key:
            return jsonify({'success': False, 'error': 'API key is required'})
        try:
            client = OpenAI(api_key=api_key)
            client.models.list()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    elif service == 'openrouter':
        api_key = data.get('api_key', '').strip()
        if not api_key:
            return jsonify({'success': False, 'error': 'API key is required'})
        try:
            resp = requests.get('https://openrouter.ai/api/v1/models',
                                headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
            if resp.status_code == 200:
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': f'HTTP {resp.status_code}'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    return jsonify({'success': False, 'error': 'Unknown service'})


@admin_bp.route('/ai/generate', methods=['POST'])
@login_required
@admin_required
def ai_generate():
    """Generate AI summaries for a show's episodes and seasons."""
    import time as time_mod
    from ..llm_services import generate_episode_summary, generate_season_recap
    db = get_db()

    if _get_show_summaries_schema_mode(db) != 'episode':
        return jsonify({
            'success': False,
            'error': 'This database still uses the legacy AI summary schema. The settings page can load, but manual generation requires the newer summary tables.'
        }), 400

    data = request.json
    show_id = data.get('show_id')
    target_season = data.get('season_number')

    if not show_id:
        return jsonify({'success': False, 'error': 'show_id is required'})

    show = db.execute('SELECT * FROM sonarr_shows WHERE id = ?', (show_id,)).fetchone()
    if not show:
        return jsonify({'success': False, 'error': 'Show not found'})

    # Get the active provider info for logging
    provider = get_setting('preferred_llm_provider')
    if not provider:
        return jsonify({'success': False, 'error': 'No LLM provider configured. Set one in Settings tab.'})

    model_setting = f'{provider}_model_name'
    model = get_setting(model_setting) or 'default'

    log_lines = []
    episode_count = 0
    season_count = 0

    # Get seasons (skip season 0 = specials)
    if target_season:
        seasons = db.execute(
            'SELECT * FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
            (show_id, target_season)
        ).fetchall()
    else:
        seasons = db.execute(
            'SELECT * FROM sonarr_seasons WHERE show_id = ? AND season_number > 0 ORDER BY season_number',
            (show_id,)
        ).fetchall()

    for season in seasons:
        sn = season['season_number']

        # Get episodes for this season
        episodes = db.execute('''
            SELECT * FROM sonarr_episodes
            WHERE show_id = ? AND season_number = ? AND episode_number > 0
            ORDER BY episode_number
        ''', (show_id, sn)).fetchall()

        if not episodes:
            log_lines.append(f"Season {sn}: No episodes found, skipping.")
            continue

        # Generate episode summaries
        episode_summary_texts = []
        for ep in episodes:
            # Check if summary already exists
            existing = db.execute(
                '''SELECT id FROM show_summaries
                   WHERE show_id = ? AND season_number = ? AND episode_number = ?
                     AND provider = ? AND model = ?''',
                (show_id, sn, ep['episode_number'], provider, model)
            ).fetchone()

            if existing:
                # Load existing for season recap context
                existing_text = db.execute(
                    'SELECT summary_text FROM show_summaries WHERE id = ?', (existing['id'],)
                ).fetchone()
                if existing_text:
                    episode_summary_texts.append(f"E{ep['episode_number']}: {existing_text['summary_text']}")
                log_lines.append(f"S{sn}E{ep['episode_number']}: Already exists, skipping.")
                continue

            log_lines.append(f"S{sn}E{ep['episode_number']}: Generating summary for \"{ep['title']}\"...")
            summary, error = generate_episode_summary(
                show['title'], sn, ep['episode_number'],
                ep['title'], ep['overview']
            )

            if error:
                log_lines.append(f"  Error: {error}")
                continue

            # Save to database
            db.execute(
                '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (show_id, sn, ep['episode_number'], summary, provider, model, 'episode_summary')
            )
            db.commit()
            episode_count += 1
            episode_summary_texts.append(f"E{ep['episode_number']}: {summary}")
            log_lines.append(f"  Done ({len(summary)} chars)")

            # Small delay to avoid rate limits
            time_mod.sleep(1)

        # Generate season recap if we have episode summaries
        existing_recap = db.execute(
            '''SELECT id FROM show_summaries
               WHERE show_id = ? AND season_number = ? AND episode_number IS NULL
                 AND provider = ? AND model = ?''',
            (show_id, sn, provider, model)
        ).fetchone()

        if existing_recap:
            log_lines.append(f"Season {sn} recap: Already exists, skipping.")
            continue

        if episode_summary_texts:
            log_lines.append(f"Season {sn}: Generating season recap...")
            recap_text = "\n\n".join(episode_summary_texts)
            recap, error = generate_season_recap(show['title'], sn, recap_text)

            if error:
                log_lines.append(f"  Error: {error}")
            else:
                db.execute(
                    '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                       VALUES (?, ?, NULL, ?, ?, ?, ?)''',
                    (show_id, sn, recap, provider, model, 'season_recap')
                )
                db.commit()
                season_count += 1
                log_lines.append(f"  Done ({len(recap)} chars)")
                time_mod.sleep(1)

    return jsonify({
        'success': True,
        'log': "\n".join(log_lines),
        'episode_count': episode_count,
        'season_count': season_count
    })


@admin_bp.route('/ai/delete-summaries', methods=['POST'])
@login_required
@admin_required
def ai_delete_summaries():
    """Delete all AI summaries for a show."""
    data = request.json
    show_id = data.get('show_id')
    if not show_id:
        return jsonify({'success': False, 'error': 'show_id required'})

    db = get_db()
    if _get_show_summaries_schema_mode(db) != 'episode':
        return jsonify({
            'success': False,
            'error': 'This database still uses the legacy AI summary schema. Bulk delete from the Generate tab is disabled until the summary tables are upgraded.'
        }), 400

    db.execute('DELETE FROM show_summaries WHERE show_id = ?', (show_id,))
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/ai/logs-data')
@login_required
@admin_required
def ai_logs_data():
    """Return API usage logs as JSON for AJAX refresh."""
    provider_filter = request.args.get('provider', '')
    db = get_db()

    if provider_filter:
        logs = db.execute(
            'SELECT * FROM api_usage WHERE provider = ? ORDER BY timestamp DESC LIMIT 100',
            (provider_filter,)
        ).fetchall()
    else:
        logs = db.execute('SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT 100').fetchall()

    return jsonify({
        'logs': [dict(row) for row in logs]
    })


# ============================================================================
# RECAP PIPELINE (subtitle-first, local model)
# ============================================================================

@admin_bp.route('/recap-pipeline')
@login_required
@admin_required
def recap_pipeline():
    """Renders the subtitle-first recap pipeline admin page."""
    from ..recap_pipeline import get_recap_pipeline_status

    db = get_db()
    status = get_recap_pipeline_status()

    # List all shows that have subtitles available
    shows_with_subs = db.execute("""
        SELECT s.tmdb_id, s.title,
               COUNT(DISTINCT sub.season_number || '-' || sub.episode_number) AS subtitle_episode_count
        FROM sonarr_shows s
        JOIN subtitles sub ON sub.show_tmdb_id = s.tmdb_id
        GROUP BY s.tmdb_id, s.title
        ORDER BY s.title
    """).fetchall()

    # Recent recaps
    recent_season_recaps = db.execute("""
        SELECT sr.id, s.title AS show_title, sr.season_number,
               sr.local_model, sr.openai_model_version, sr.status,
               sr.spoiler_cutoff_episode, sr.runtime_seconds,
               sr.openai_cost_usd, sr.updated_at,
               sr.error_message
        FROM season_recaps sr
        JOIN sonarr_shows s ON s.tmdb_id = sr.show_tmdb_id
        ORDER BY sr.updated_at DESC
        LIMIT 50
    """).fetchall()

    recent_episode_recaps = db.execute("""
        SELECT er.id, s.title AS show_title, er.season_number, er.episode_number,
               er.local_model, er.status, er.runtime_seconds, er.updated_at,
               er.error_message
        FROM episode_recaps er
        JOIN sonarr_shows s ON s.tmdb_id = er.show_tmdb_id
        ORDER BY er.updated_at DESC
        LIMIT 100
    """).fetchall()

    return render_template(
        'admin_recap_pipeline.html',
        title='Recap Pipeline',
        status=status,
        shows_with_subs=shows_with_subs,
        recent_season_recaps=recent_season_recaps,
        recent_episode_recaps=recent_episode_recaps,
    )


@admin_bp.route('/recap-pipeline/generate-season', methods=['POST'])
@login_required
@admin_required
def recap_pipeline_generate_season():
    """Trigger subtitle-first season recap generation."""
    from ..recap_pipeline import generate_season_recap

    tmdb_id = request.form.get('tmdb_id', type=int)
    season_number = request.form.get('season_number', type=int)
    spoiler_cutoff = request.form.get('spoiler_cutoff', type=int) or None
    local_model = request.form.get('local_model', 'gpt-oss:20b').strip() or 'gpt-oss:20b'
    openai_polish = bool(request.form.get('openai_polish'))
    force = bool(request.form.get('force'))

    if not tmdb_id or not season_number:
        flash('tmdb_id and season_number are required.', 'danger')
        return redirect(url_for('admin.recap_pipeline'))

    current_app.logger.info(
        f"Admin triggered season recap: tmdb={tmdb_id} S{season_number} "
        f"model={local_model} polish={openai_polish} force={force}"
    )

    recap, error = generate_season_recap(
        tmdb_id, season_number,
        spoiler_cutoff=spoiler_cutoff,
        local_model=local_model,
        openai_polish=openai_polish,
        force=force,
    )

    if error:
        flash(f'Season recap generation failed: {error}', 'danger')
    else:
        flash(f'Season recap generated successfully for season {season_number}.', 'success')

    return redirect(url_for('admin.recap_pipeline'))


@admin_bp.route('/recap-pipeline/generate-episode', methods=['POST'])
@login_required
@admin_required
def recap_pipeline_generate_episode():
    """Trigger subtitle-first episode recap generation."""
    from ..recap_pipeline import generate_episode_recap

    tmdb_id = request.form.get('tmdb_id', type=int)
    season_number = request.form.get('season_number', type=int)
    episode_number = request.form.get('episode_number', type=int)
    spoiler_cutoff = request.form.get('spoiler_cutoff', type=int) or None
    local_model = request.form.get('local_model', 'gpt-oss:20b').strip() or 'gpt-oss:20b'
    force = bool(request.form.get('force'))

    if not tmdb_id or not season_number or not episode_number:
        flash('tmdb_id, season_number, and episode_number are required.', 'danger')
        return redirect(url_for('admin.recap_pipeline'))

    current_app.logger.info(
        f"Admin triggered episode recap: tmdb={tmdb_id} S{season_number}E{episode_number} "
        f"model={local_model} force={force}"
    )

    summary, error = generate_episode_recap(
        tmdb_id, season_number, episode_number,
        spoiler_cutoff=spoiler_cutoff,
        local_model=local_model,
        force=force,
    )

    if error:
        flash(f'Episode recap generation failed: {error}', 'danger')
    else:
        flash(
            f'Episode recap generated for S{season_number:02d}E{episode_number:02d}.',
            'success',
        )

    return redirect(url_for('admin.recap_pipeline'))


@admin_bp.route('/recap-pipeline/season/<int:recap_id>', methods=['GET'])
@login_required
@admin_required
def recap_pipeline_view_season(recap_id):
    """View a single season recap."""
    db = get_db()
    row = db.execute("""
        SELECT sr.*, s.title AS show_title
        FROM season_recaps sr
        JOIN sonarr_shows s ON s.tmdb_id = sr.show_tmdb_id
        WHERE sr.id = ?
    """, (recap_id,)).fetchone()
    if not row:
        abort(404)
    return render_template(
        'admin_recap_pipeline.html',
        title='View Season Recap',
        view_recap=dict(row),
        status={}, shows_with_subs=[],
        recent_season_recaps=[], recent_episode_recaps=[],
    )
