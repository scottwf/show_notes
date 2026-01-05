"""
Migration script to add rating columns to sonarr_shows and sonarr_episodes tables.
"""

def upgrade(db_conn):
    """
    Applies the database schema upgrade.
    Adds rating columns to sonarr_shows and sonarr_episodes.
    """
    cursor = db_conn.cursor()

    # Add columns to sonarr_shows
    # Check if columns exist first to make script idempotent (optional for linear migrations)
    cursor.execute("PRAGMA table_info(sonarr_shows)")
    existing_columns_shows = [row[1] for row in cursor.fetchall()]

    show_cols_to_add = {
        "ratings_imdb_value": "REAL",
        "ratings_imdb_votes": "INTEGER",
        "ratings_tmdb_value": "REAL",
        "ratings_tmdb_votes": "INTEGER",
        "ratings_metacritic_value": "REAL",
        "metacritic_id": "TEXT"
    }

    for col_name, col_type in show_cols_to_add.items():
        if col_name not in existing_columns_shows:
            cursor.execute(f"ALTER TABLE sonarr_shows ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name} to sonarr_shows")
        else:
            print(f"Column {col_name} already exists in sonarr_shows")

    # Add columns to sonarr_episodes
    cursor.execute("PRAGMA table_info(sonarr_episodes)")
    existing_columns_episodes = [row[1] for row in cursor.fetchall()]

    episode_cols_to_add = {
        "ratings_imdb_value": "REAL",
        "ratings_imdb_votes": "INTEGER",
        "ratings_tmdb_value": "REAL",
        "ratings_tmdb_votes": "INTEGER",
        "imdb_id": "TEXT"
    }

    for col_name, col_type in episode_cols_to_add.items():
        if col_name not in existing_columns_episodes:
            cursor.execute(f"ALTER TABLE sonarr_episodes ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name} to sonarr_episodes")
        else:
            print(f"Column {col_name} already exists in sonarr_episodes")

    db_conn.commit()
    print("Migration 015: Ratings columns added successfully to sonarr_shows and sonarr_episodes.")

def downgrade(db_conn):
    """
    Reverts the database schema upgrade.
    This is generally not recommended for columns with data,
    but provided for completeness if data loss is acceptable.
    A more robust downgrade would involve backing up data.
    """
    # For simplicity, we're not implementing a full column drop with sqlite's
    # typical workaround (create new table, copy data, drop old, rename new).
    # This downgrade is mostly a placeholder.
    print("Downgrade for 015_add_ratings_to_media.py is not fully implemented to prevent data loss.")
    print("If you need to revert, you'll need to manually manage dropping these columns from")
    print("sonarr_shows: ratings_imdb_value, ratings_imdb_votes, ratings_tmdb_value, ratings_tmdb_votes, ratings_metacritic_value, metacritic_id")
    print("sonarr_episodes: ratings_imdb_value, ratings_imdb_votes, ratings_tmdb_value, ratings_tmdb_votes, imdb_id")
    # db_conn.commit() # No changes to commit for this placeholder
    pass
