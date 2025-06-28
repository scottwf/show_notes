import sqlite3
import os

TMDB_ID = 69478
DB_PATH = "instance/shownotes.sqlite3"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get show DB id and tvdb_id
    c.execute("SELECT id, tvdb_id FROM sonarr_shows WHERE tmdb_id = ?", (TMDB_ID,))
    row = c.fetchone()
    if not row:
        print("Show not found in sonarr_shows.")
        return
    show_id = row["id"]
    tvdb_id = row["tvdb_id"]

    # Delete episodes
    c.execute("DELETE FROM sonarr_episodes WHERE season_id IN (SELECT id FROM sonarr_seasons WHERE show_id = ?)", (show_id,))
    # Delete seasons
    c.execute("DELETE FROM sonarr_seasons WHERE show_id = ?", (show_id,))
    # Delete show
    c.execute("DELETE FROM sonarr_shows WHERE id = ?", (show_id,))
    # Optionally, delete from activity log
    if tvdb_id:
        c.execute("DELETE FROM plex_activity_log WHERE grandparent_rating_key = ?", (str(tvdb_id),))
    conn.commit()
    conn.close()
    print("Database cleanup complete.")

    # Delete cached images
    cache_dirs = [
        "app/static/posters/",
        "app/static/background/",
        "app/static/img_cache/posters/",
        "app/static/img_cache/backgrounds/"
    ]
    for d in cache_dirs:
        for prefix in [f"show_poster_{TMDB_ID}", f"show_fanart_{TMDB_ID}"]:
            for ext in ["", ".jpg", ".jpeg", ".png", ".webp"]:
                path = os.path.join(d, prefix + ext)
                if os.path.exists(path):
                    os.remove(path)
                    print(f"Deleted {path}")

if __name__ == "__main__":
    main()