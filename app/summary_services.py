"""
Summary Services Module

Provides LLM-based season recap and show summary generation.
Uses episode data from Sonarr to build grounded prompts, and respects
model knowledge cutoff dates to avoid hallucination about recent content.

Key functions:
- get_summarizable_seasons(): Find seasons eligible for summarization
- generate_season_summary(): Generate a recap for one season
- generate_show_summary(): Synthesize a whole-show summary from season recaps
- process_summary_queue(): Scheduler entry point for off-hours generation
- get_season_summary() / get_show_summary(): Retrieve summaries for display
"""
import time
import logging
from datetime import datetime
from flask import current_app
from .database import get_db, get_setting


def get_summarizable_seasons():
    """
    Find seasons that are eligible for LLM summarization.

    A season is summarizable when:
    - Season number > 0 (skip specials)
    - All episodes in the season have files (fully available)
    - The last episode aired before the configured knowledge cutoff date
    - No completed summary exists for the current provider/model combo

    Returns:
        list of dicts with keys: tmdb_id, show_title, season_number, episode_count, last_air_date
    """
    db = get_db()
    provider = get_setting('preferred_llm_provider')
    cutoff_date = get_setting('llm_knowledge_cutoff_date')

    if not provider or provider == 'none' or provider == '':
        current_app.logger.info("No LLM provider configured, no seasons to summarize")
        return []

    if not cutoff_date:
        current_app.logger.info("No knowledge cutoff date configured, no seasons to summarize")
        return []

    # Determine current model name
    if provider == 'ollama':
        model = get_setting('ollama_model_name') or 'llama2'
    elif provider == 'openai':
        model = get_setting('openai_model_name') or 'gpt-3.5-turbo'
    else:
        return []

    rows = db.execute("""
        SELECT s.tmdb_id, s.title as show_title, ss.season_number,
               ss.episode_count, ss.episode_file_count,
               MAX(e.air_date_utc) as last_air_date
        FROM sonarr_seasons ss
        JOIN sonarr_shows s ON s.id = ss.show_id
        JOIN sonarr_episodes e ON e.season_id = ss.id
        LEFT JOIN season_summaries sm ON sm.tmdb_id = s.tmdb_id
            AND sm.season_number = ss.season_number
            AND sm.llm_provider = ? AND sm.llm_model = ?
            AND sm.status = 'completed'
        WHERE ss.season_number > 0
            AND ss.episode_count > 0
            AND ss.episode_file_count = ss.episode_count
            AND sm.id IS NULL
        GROUP BY ss.id
        HAVING last_air_date IS NOT NULL AND last_air_date < ?
        ORDER BY s.title, ss.season_number
    """, (provider, model, cutoff_date)).fetchall()

    return [dict(row) for row in rows]


def build_season_recap_prompt(tmdb_id, season_number):
    """
    Build an LLM prompt for generating a season recap.

    Uses episode titles and overviews from the database as grounding context
    so the LLM has factual anchors for its summary.

    Returns:
        tuple: (prompt_text, show_title) or (None, None) if data not found
    """
    db = get_db()

    show = db.execute(
        "SELECT title, overview FROM sonarr_shows WHERE tmdb_id = ?", (tmdb_id,)
    ).fetchone()
    if not show:
        return None, None

    season = db.execute("""
        SELECT ss.id FROM sonarr_seasons ss
        JOIN sonarr_shows s ON s.id = ss.show_id
        WHERE s.tmdb_id = ? AND ss.season_number = ?
    """, (tmdb_id, season_number)).fetchone()
    if not season:
        return None, None

    episodes = db.execute("""
        SELECT episode_number, title, overview
        FROM sonarr_episodes
        WHERE season_id = ?
        ORDER BY episode_number
    """, (season['id'],)).fetchall()

    if not episodes:
        return None, None

    # Build episode listing
    episode_lines = []
    for ep in episodes:
        overview = ep['overview'] or 'No synopsis available.'
        episode_lines.append(f"{ep['episode_number']}. \"{ep['title']}\" - {overview}")

    episodes_text = "\n".join(episode_lines)

    prompt = f"""You are a TV critic writing a comprehensive season recap for viewers who want to refresh their memory before a new season.

Show: {show['title']}
Season: {season_number}

Show overview: {show['overview'] or 'N/A'}

Episodes in this season:
{episodes_text}

Write a detailed recap of Season {season_number} covering:
- Major plot developments and story arcs
- Key character arcs and turning points
- Important themes and how they developed

Guidelines:
- Write as a narrative recap, not episode-by-episode
- Assume the reader has watched this season but needs a refresher
- Include spoilers freely since this is a recap
- Keep it under 600 words
- Use markdown formatting with ## headers for sections
- Do not include episode numbers or titles in the recap itself"""

    return prompt, show['title']


def generate_season_summary(tmdb_id, season_number):
    """
    Generate an LLM summary for a specific season.

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    from .llm_services import get_llm_response

    db = get_db()
    provider = get_setting('preferred_llm_provider')

    if not provider or provider in ('none', ''):
        return False, "No LLM provider configured"

    if provider == 'ollama':
        model = get_setting('ollama_model_name') or 'llama2'
    elif provider == 'openai':
        model = get_setting('openai_model_name') or 'gpt-3.5-turbo'
    else:
        return False, f"Unknown provider: {provider}"

    prompt, show_title = build_season_recap_prompt(tmdb_id, season_number)
    if not prompt:
        return False, f"Could not build prompt for tmdb_id={tmdb_id} season={season_number}"

    # Upsert a 'generating' status row
    db.execute("""
        INSERT INTO season_summaries (tmdb_id, show_title, season_number, llm_provider, llm_model, prompt_text, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'generating', CURRENT_TIMESTAMP)
        ON CONFLICT(tmdb_id, season_number, llm_provider, llm_model) DO UPDATE SET
            status = 'generating', prompt_text = excluded.prompt_text, updated_at = CURRENT_TIMESTAMP
    """, (tmdb_id, show_title, season_number, provider, model, prompt))
    db.commit()

    current_app.logger.info(f"Generating summary for '{show_title}' Season {season_number} with {provider}/{model}")

    response_text, error = get_llm_response(prompt, llm_model_name=model, provider=provider)

    if error:
        db.execute("""
            UPDATE season_summaries SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE tmdb_id = ? AND season_number = ? AND llm_provider = ? AND llm_model = ?
        """, (error, tmdb_id, season_number, provider, model))
        db.commit()
        current_app.logger.error(f"Summary generation failed for '{show_title}' S{season_number}: {error}")
        return False, error

    db.execute("""
        UPDATE season_summaries SET
            summary_text = ?, raw_llm_response = ?, status = 'completed',
            error_message = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE tmdb_id = ? AND season_number = ? AND llm_provider = ? AND llm_model = ?
    """, (response_text, response_text, tmdb_id, season_number, provider, model))
    db.commit()

    current_app.logger.info(f"Summary completed for '{show_title}' Season {season_number}")
    return True, None


def generate_show_summary(tmdb_id):
    """
    Generate a whole-show summary from existing completed season summaries.
    Only runs when all summarizable seasons have completed recaps.

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    from .llm_services import get_llm_response

    db = get_db()
    provider = get_setting('preferred_llm_provider')

    if not provider or provider in ('none', ''):
        return False, "No LLM provider configured"

    if provider == 'ollama':
        model = get_setting('ollama_model_name') or 'llama2'
    elif provider == 'openai':
        model = get_setting('openai_model_name') or 'gpt-3.5-turbo'
    else:
        return False, f"Unknown provider: {provider}"

    show = db.execute("SELECT title, overview FROM sonarr_shows WHERE tmdb_id = ?", (tmdb_id,)).fetchone()
    if not show:
        return False, f"Show not found for tmdb_id={tmdb_id}"

    # Get all completed season summaries for this show
    summaries = db.execute("""
        SELECT season_number, summary_text FROM season_summaries
        WHERE tmdb_id = ? AND llm_provider = ? AND llm_model = ? AND status = 'completed'
        ORDER BY season_number
    """, (tmdb_id, provider, model)).fetchall()

    # Manual show generation should not fail just because season summaries
    # have not been generated yet. Generate eligible seasons first, then retry.
    if not summaries:
        cutoff_date = get_setting('llm_knowledge_cutoff_date')
        if not cutoff_date:
            return False, "No completed season summaries and no knowledge cutoff date configured"

        eligible_seasons = db.execute("""
            SELECT ss.season_number
            FROM sonarr_seasons ss
            JOIN sonarr_shows s ON s.id = ss.show_id
            JOIN sonarr_episodes e ON e.season_id = ss.id
            LEFT JOIN season_summaries sm ON sm.tmdb_id = s.tmdb_id
                AND sm.season_number = ss.season_number
                AND sm.llm_provider = ? AND sm.llm_model = ?
                AND sm.status = 'completed'
            WHERE s.tmdb_id = ?
                AND ss.season_number > 0
                AND ss.episode_count > 0
                AND ss.episode_file_count = ss.episode_count
                AND sm.id IS NULL
            GROUP BY ss.id
            HAVING MAX(e.air_date_utc) IS NOT NULL AND MAX(e.air_date_utc) < ?
            ORDER BY ss.season_number
        """, (provider, model, tmdb_id, cutoff_date)).fetchall()

        if not eligible_seasons:
            # Manual button fallback: if cutoff-based eligibility finds nothing,
            # try any season that has at least one downloaded episode file.
            eligible_seasons = db.execute("""
                SELECT ss.season_number
                FROM sonarr_seasons ss
                JOIN sonarr_shows s ON s.id = ss.show_id
                LEFT JOIN season_summaries sm ON sm.tmdb_id = s.tmdb_id
                    AND sm.season_number = ss.season_number
                    AND sm.llm_provider = ? AND sm.llm_model = ?
                    AND sm.status = 'completed'
                WHERE s.tmdb_id = ?
                    AND ss.season_number > 0
                    AND ss.episode_count > 0
                    AND ss.episode_file_count > 0
                    AND sm.id IS NULL
                ORDER BY ss.season_number
            """, (provider, model, tmdb_id)).fetchall()

        if not eligible_seasons:
            return False, "No completed season summaries to synthesize and no seasons with episode files found"

        first_error = None
        for season in eligible_seasons:
            success, error = generate_season_summary(tmdb_id, int(season['season_number']))
            if not success and not first_error:
                first_error = error

        summaries = db.execute("""
            SELECT season_number, summary_text FROM season_summaries
            WHERE tmdb_id = ? AND llm_provider = ? AND llm_model = ? AND status = 'completed'
            ORDER BY season_number
        """, (tmdb_id, provider, model)).fetchall()

        if not summaries:
            return False, first_error or "Season summary generation did not produce any completed summaries"

    season_texts = []
    for s in summaries:
        season_texts.append(f"### Season {s['season_number']}\n{s['summary_text']}")

    all_seasons = "\n\n".join(season_texts)

    prompt = f"""You are a TV critic writing a comprehensive series overview.

Show: {show['title']}
Show overview: {show['overview'] or 'N/A'}

Here are the individual season recaps:

{all_seasons}

Write a high-level series summary that covers:
- The overall story arc across all seasons
- How the main characters evolved
- Major themes of the series

Guidelines:
- This is a synthesis, not a repetition of season recaps
- Keep it under 400 words
- Use markdown formatting
- Spoilers are fine since this summarizes completed content"""

    # Upsert generating status
    db.execute("""
        INSERT INTO show_summaries (tmdb_id, show_title, llm_provider, llm_model, prompt_text, status, updated_at)
        VALUES (?, ?, ?, ?, ?, 'generating', CURRENT_TIMESTAMP)
        ON CONFLICT(tmdb_id, llm_provider, llm_model) DO UPDATE SET
            status = 'generating', prompt_text = excluded.prompt_text, updated_at = CURRENT_TIMESTAMP
    """, (tmdb_id, show['title'], provider, model, prompt))
    db.commit()

    response_text, error = get_llm_response(prompt, llm_model_name=model, provider=provider)

    if error:
        db.execute("""
            UPDATE show_summaries SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE tmdb_id = ? AND llm_provider = ? AND llm_model = ?
        """, (error, tmdb_id, provider, model))
        db.commit()
        return False, error

    db.execute("""
        UPDATE show_summaries SET
            summary_text = ?, raw_llm_response = ?, status = 'completed',
            error_message = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE tmdb_id = ? AND llm_provider = ? AND llm_model = ?
    """, (response_text, response_text, tmdb_id, provider, model))
    db.commit()

    current_app.logger.info(f"Show summary completed for '{show['title']}'")
    return True, None


def process_summary_queue(app):
    """
    Scheduler entry point: process pending summaries within the configured time window.

    - Checks if current time is within the quiet hours window
    - Processes one season at a time with configurable delay between calls
    - Stops when the window closes or queue is empty
    """
    with app.app_context():
        enabled = get_setting('summary_enabled')
        if not enabled:
            current_app.logger.debug("Summary generation is disabled")
            return

        start_hour = get_setting('summary_schedule_start_hour') or 2
        end_hour = get_setting('summary_schedule_end_hour') or 6
        delay_seconds = get_setting('summary_delay_seconds') or 30

        now = datetime.now()
        if not _is_within_window(now.hour, start_hour, end_hour):
            current_app.logger.debug(f"Outside summary window ({start_hour}:00-{end_hour}:00), skipping")
            return

        current_app.logger.info("Starting summary generation queue processing")
        seasons = get_summarizable_seasons()

        if not seasons:
            current_app.logger.info("No seasons need summarization")
            return

        processed = 0
        for season_info in seasons:
            # Re-check window before each generation
            now = datetime.now()
            if not _is_within_window(now.hour, start_hour, end_hour):
                current_app.logger.info(f"Exiting summary window after processing {processed} seasons")
                break

            success, error = generate_season_summary(
                season_info['tmdb_id'], season_info['season_number']
            )

            if success:
                processed += 1
                try:
                    from .system_logger import syslog, SystemLogger
                    syslog.success(SystemLogger.SYNC,
                        f"Generated summary for {season_info['show_title']} S{season_info['season_number']}",
                        {'tmdb_id': season_info['tmdb_id'], 'season': season_info['season_number']})
                except Exception:
                    pass
            else:
                current_app.logger.warning(
                    f"Failed to summarize {season_info['show_title']} S{season_info['season_number']}: {error}")

            # Delay between calls to avoid overloading GPU
            if season_info != seasons[-1]:
                time.sleep(delay_seconds)

        current_app.logger.info(f"Summary queue processing complete: {processed}/{len(seasons)} seasons processed")


def _is_within_window(current_hour, start_hour, end_hour):
    """Check if current_hour falls within the start-end window (handles midnight wrapping)."""
    if start_hour <= end_hour:
        return start_hour <= current_hour < end_hour
    else:
        # Window wraps midnight (e.g., 22:00 - 06:00)
        return current_hour >= start_hour or current_hour < end_hour


def get_season_summary(tmdb_id, season_number):
    """
    Retrieve a completed season summary for display.
    Returns the most recently completed summary regardless of provider/model.

    Returns:
        dict or None
    """
    db = get_db()
    row = db.execute("""
        SELECT summary_text, llm_provider, llm_model, updated_at
        FROM season_summaries
        WHERE tmdb_id = ? AND season_number = ? AND status = 'completed'
        ORDER BY updated_at DESC LIMIT 1
    """, (tmdb_id, season_number)).fetchone()

    return dict(row) if row else None


def get_show_summary(tmdb_id):
    """
    Retrieve a completed show summary for display.

    Returns:
        dict or None
    """
    db = get_db()
    row = db.execute("""
        SELECT summary_text, llm_provider, llm_model, updated_at
        FROM show_summaries
        WHERE tmdb_id = ? AND status = 'completed'
        ORDER BY updated_at DESC LIMIT 1
    """, (tmdb_id,)).fetchone()

    return dict(row) if row else None


def get_summary_queue_status():
    """
    Get summary queue statistics for the admin UI.

    Returns:
        dict with pending_count, completed_count, failed_count, total_shows
    """
    db = get_db()
    provider = get_setting('preferred_llm_provider') or ''
    model = ''
    if provider == 'ollama':
        model = get_setting('ollama_model_name') or ''
    elif provider == 'openai':
        model = get_setting('openai_model_name') or ''

    completed = db.execute(
        "SELECT COUNT(*) as cnt FROM season_summaries WHERE status = 'completed'"
    ).fetchone()['cnt']

    failed = db.execute(
        "SELECT COUNT(*) as cnt FROM season_summaries WHERE status = 'failed'"
    ).fetchone()['cnt']

    generating = db.execute(
        "SELECT COUNT(*) as cnt FROM season_summaries WHERE status = 'generating'"
    ).fetchone()['cnt']

    # Count summarizable seasons (pending work)
    pending = len(get_summarizable_seasons()) if provider else 0

    last_generated = db.execute(
        "SELECT updated_at FROM season_summaries WHERE status = 'completed' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    return {
        'pending_count': pending,
        'completed_count': completed,
        'failed_count': failed,
        'generating_count': generating,
        'last_generated_at': last_generated['updated_at'] if last_generated else None,
        'current_provider': provider,
        'current_model': model,
    }
