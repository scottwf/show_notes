import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get existing columns
    cur.execute("PRAGMA table_info(sonarr_shows)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # TVMaze identifier
    if 'tvmaze_id' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN tvmaze_id INTEGER")
        print("✓ Added tvmaze_id column")

    # Date fields for year range
    if 'premiered' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN premiered TEXT")
        print("✓ Added premiered column")

    if 'ended' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN ended TEXT")
        print("✓ Added ended column")

    # Enhanced description
    if 'tvmaze_summary' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN tvmaze_summary TEXT")
        print("✓ Added tvmaze_summary column")

    # Metadata fields
    if 'genres' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN genres TEXT")
        print("✓ Added genres column")

    if 'network_name' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN network_name TEXT")
        print("✓ Added network_name column")

    if 'network_country' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN network_country TEXT")
        print("✓ Added network_country column")

    if 'runtime' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN runtime INTEGER")
        print("✓ Added runtime column")

    if 'tvmaze_rating' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN tvmaze_rating REAL")
        print("✓ Added tvmaze_rating column")

    # Tracking timestamp
    if 'tvmaze_enriched_at' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN tvmaze_enriched_at DATETIME")
        print("✓ Added tvmaze_enriched_at column")

    # Index for lookups
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_sonarr_shows_tvmaze_id
        ON sonarr_shows(tvmaze_id)
    """)
    print("✓ Created index on tvmaze_id")

    conn.commit()
    conn.close()
    print("\n✅ Migration 029 completed successfully")

if __name__ == '__main__':
    print("Running migration: 029_add_tvmaze_enrichment.py")
    upgrade()
