import os
import sqlite3 # Keep for sqlite3.Error
import re
from glob import glob
from flask import current_app
from .database import get_db # Assuming database.py is in the same directory (app/)

# SUBS_DIR will be relative to the instance path or configured
# For now, assuming bazarr_subtitles is at the project root (one level above app)
# This might need adjustment based on actual deployment structure or configuration
# SUBS_DIR = os.path.join(os.path.dirname(current_app.root_path), 'bazarr_subtitles')
# Let's stick to the original relative path from the file, but note it might need config
SUBS_DIR = os.path.join(os.path.dirname(__file__), '../bazarr_subtitles')


SRT_PATTERN = re.compile(r'\d+\s+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s+\n((?:.+\n?)+?)(?=\n\d+|\Z)', re.MULTILINE)


def parse_srt(srt_text):
    entries = []
    matches = SRT_PATTERN.finditer(srt_text)
    for match in matches:
        start, end, text = match.groups()
        # Remove speaker prefix if present (e.g. "[Walter]: Hello!")
        line = text.strip().replace('\n', ' ')
        speaker = None
        if ':' in line and line.index(':') < 30:
            maybe_speaker, rest = line.split(':', 1)
            if re.match(r'^[\w\s\-\[\]\(\)]+$', maybe_speaker):
                speaker = maybe_speaker.strip(' []()')
                line = rest.strip()
        entries.append({'start': start, 'end': end, 'speaker': speaker, 'line': line})
    return entries

def insert_subtitles(db, show_tmdb_id, season_number, episode_number, entries):
    """Inserts subtitle entries into the database."""
    # `created_at` has a DEFAULT CURRENT_TIMESTAMP in the table schema
    sql = """
        INSERT INTO subtitles (show_tmdb_id, season_number, episode_number, start_time, end_time, speaker, line, search_blob)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    c = db.cursor()
    try:
        for entry in entries:
            search_blob = entry['line'].lower() # Or more sophisticated blob creation
            c.execute(sql, (
                show_tmdb_id,
                season_number,
                episode_number,
                entry['start'],
                entry['end'],
                entry.get('speaker'), # Use .get() in case speaker is None
                entry['line'],
                search_blob
            ))
        db.commit()
    except sqlite3.Error as e:
        db.rollback() # Rollback on error
        current_app.logger.error(f"Database error inserting subtitles for TMDB ID {show_tmdb_id} S{season_number}E{episode_number}: {e}")
        raise # Re-raise the exception if you want calling code to handle it

def get_show_title(db, show_tmdb_id):
    """Fetches show title from sonarr_shows using tmdb_id."""
    c = db.cursor()
    try:
        c.execute("SELECT title FROM sonarr_shows WHERE tmdb_id = ?", (show_tmdb_id,))
        row = c.fetchone()
        return row['title'] if row else None
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching title for TMDB ID {show_tmdb_id}: {e}")
        return None

def process_all_subtitles():
    """
    Processes all subtitle files found in SUBS_DIR, parses them,
    and inserts the data into the database.
    This function is intended to be called from within the Flask app context.
    """
    db = get_db()
    logger = current_app.logger

    # Adjust SUBS_DIR if it needs to be dynamic based on app config
    # For example: configured_subs_dir = current_app.config.get('SUBS_DIR', SUBS_DIR)
    # For now, we use the module-level SUBS_DIR
    # If SUBS_DIR needs current_app context (e.g. for root_path), define it here.
    # For this refactor, we'll assume the initial definition of SUBS_DIR is okay,
    # or it will be configured externally.
    # A more robust way for SUBS_DIR:
    # subs_dir_path = os.path.join(os.path.dirname(current_app.root_path), 'bazarr_subtitles')
    # if not os.path.isdir(subs_dir_path):
    #    logger.warning(f"Subtitles directory not found: {subs_dir_path}")
    #    return

    logger.info("Starting subtitle processing...")
    # Example path: /bazarr_subtitles/<tmdb_id_show_folder>/Season 01/<show_title> - S01E01.en.srt
    for show_dir_path in glob(os.path.join(SUBS_DIR, '*')):
        if not os.path.isdir(show_dir_path):
            continue

        show_tmdb_id_str = os.path.basename(show_dir_path)
        try:
            show_tmdb_id = int(show_tmdb_id_str)
        except ValueError:
            logger.warning(f"Skipping directory {show_dir_path}: Name '{show_tmdb_id_str}' is not a valid TMDB ID.")
            continue

        show_title = get_show_title(db, show_tmdb_id)
        if not show_title:
            logger.warning(f"Skipping TMDB ID {show_tmdb_id} (directory: {show_tmdb_id_str}): Show title not found in sonarr_shows.")
            continue

        logger.info(f"Processing show: {show_title} (TMDB ID: {show_tmdb_id})")

        for season_dir_path in glob(os.path.join(show_dir_path, 'Season*')):
            if not os.path.isdir(season_dir_path):
                continue

            season_match = re.search(r'\d+', os.path.basename(season_dir_path))
            if not season_match:
                logger.warning(f"Skipping season directory {season_dir_path}: Could not parse season number.")
                continue
            season_number = int(season_match.group(0))

            for srt_file_path in glob(os.path.join(season_dir_path, '*.srt')):
                logger.debug(f"Processing file: {srt_file_path}")

                # Extract episode number from filename (e.g., S01E02)
                episode_match = re.search(r'S(\d+)E(\d+)', os.path.basename(srt_file_path), re.IGNORECASE)
                if not episode_match:
                    logger.warning(f"Skipping file {srt_file_path}: No episode number found in filename.")
                    continue

                # season_from_file = int(episode_match.group(1)) # Could be used for validation
                episode_number = int(episode_match.group(2))

                try:
                    with open(srt_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        srt_text = f.read()
                except Exception as e:
                    logger.error(f"Error reading SRT file {srt_file_path}: {e}")
                    continue

                if not srt_text.strip():
                    logger.info(f"Skipping empty SRT file: {srt_file_path}")
                    continue

                entries = parse_srt(srt_text)
                if entries:
                    try:
                        insert_subtitles(db, show_tmdb_id, season_number, episode_number, entries)
                        logger.info(f"Inserted {len(entries)} subtitle lines for {show_title} S{season_number:02d}E{episode_number:02d}")
                    except sqlite3.Error:
                        # Error already logged by insert_subtitles
                        logger.error(f"Failed to insert subtitles for {show_title} S{season_number:02d}E{episode_number:02d} from file {srt_file_path}")
                else:
                    logger.info(f"No subtitle entries parsed from {srt_file_path}")

    logger.info("Subtitle processing finished.")
