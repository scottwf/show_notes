import sqlite3
import os
import sys

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def get_db_connection():
    # Ensure instance folder exists (optional, but good practice for migrations)
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
        print(f"Created instance folder: {INSTANCE_FOLDER_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row['name'] for row in cursor.fetchall()]
    return column_name in columns

def migrate():
    print("Running migration: 005_add_details_to_radarr_movies.py")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        table_name = 'radarr_movies'
        columns_to_add = [
            # Existing, potentially renamed for clarity/consistency:
            ('release_date', 'TEXT'),                  # from MovieResource.releaseDate
            ('original_language_name', 'TEXT'),      # from MovieResource.originalLanguage.name
            ('studio', 'TEXT'),                        # from MovieResource.studio
            ('runtime', 'INTEGER'),                    # from MovieResource.runtime
            ('ratings_tmdb_value', 'REAL'),            # from MovieResource.ratings.tmdb.value
            ('ratings_tmdb_votes', 'INTEGER'),         # from MovieResource.ratings.tmdb.votes
            ('ratings_imdb_value', 'REAL'),            # from MovieResource.ratings.imdb.value
            ('ratings_imdb_votes', 'INTEGER'),         # from MovieResource.ratings.imdb.votes

            # New additions from MovieResource exploration:
            ('overview', 'TEXT'),                      # from MovieResource.overview
            ('status', 'TEXT'),                        # from MovieResource.status
            ('genres', 'TEXT'),                        # from MovieResource.genres (store as JSON string)
            ('certification', 'TEXT'),                 # from MovieResource.certification
            ('ratings_rottenTomatoes_value', 'REAL'),  # from MovieResource.ratings.rottenTomatoes.value
            ('ratings_rottenTomatoes_votes', 'INTEGER'),# from MovieResource.ratings.rottenTomatoes.votes
            ('original_title', 'TEXT'),                # from MovieResource.originalTitle
            ('popularity', 'REAL')                     # from MovieResource.popularity
        ]

        for col_name, col_type in columns_to_add:
            if not column_exists(cursor, table_name, col_name):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                print(f"Added column '{col_name}' to '{table_name}' table.")
            else:
                print(f"Column '{col_name}' already exists in '{table_name}' table.")

        conn.commit()
        print(f"Migration 005 completed successfully. Details added to {table_name}.")

    except sqlite3.Error as e:
        print(f"SQLite error during migration 005: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during migration 005: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print("Starting migration 005_add_details_to_radarr_movies...")
    migrate()
    print("Migration 005_add_details_to_radarr_movies finished.")
