import os
import sqlite3
import re
from glob import glob

DB_PATH = os.path.join(os.path.dirname(__file__), '../data/shownotes.db')
SUBS_DIR = os.path.join(os.path.dirname(__file__), '../bazarr_subtitles')  # Update if your Bazarr subtitles are elsewhere

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

def insert_subtitles(show_id, season, episode, entries):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for entry in entries:
        c.execute('''INSERT INTO subtitles (show_id, season, episode, start_time, end_time, speaker, line, search_blob)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (show_id, season, episode, entry['start'], entry['end'], entry['speaker'], entry['line'], entry['line'].lower()))
    conn.commit()
    conn.close()

TARGET_SHOWS = [
    "For All Mankind",
    "The Last of Us",
    "Righteous Gemstones"
]

def get_show_title(show_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT show_title FROM show_metadata WHERE show_id = ?", (show_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def is_target_show(title):
    if not title:
        return False
    title = title.lower()
    return any(target.lower() in title for target in TARGET_SHOWS)

def main():
    # Example: /bazarr_subtitles/<show_id>/Season 01/<show_title> - S01E01.en.srt
    for show_dir in glob(os.path.join(SUBS_DIR, '*')):
        show_id = os.path.basename(show_dir)
        show_title = get_show_title(show_id)
        if not is_target_show(show_title):
            print(f"Skipping show_id {show_id} (title: {show_title}) - not in target list.")
            continue
        for season_dir in glob(os.path.join(show_dir, 'Season*')):
            season = int(re.search(r'\d+', os.path.basename(season_dir)).group(0))
            for srt_file in glob(os.path.join(season_dir, '*.srt')):
                # Extract episode number from filename (S01E02)
                m = re.search(r'S(\d+)E(\d+)', os.path.basename(srt_file), re.IGNORECASE)
                if not m:
                    print(f"Skipping {srt_file}: no episode number found.")
                    continue
                ep_num = int(m.group(2))
                with open(srt_file, 'r', encoding='utf-8', errors='ignore') as f:
                    srt_text = f.read()
                entries = parse_srt(srt_text)
                insert_subtitles(show_id, season, ep_num, entries)
                print(f"Inserted {len(entries)} lines for show {show_id} ({show_title}) S{season:02d}E{ep_num:02d}")

if __name__ == '__main__':
    main()
