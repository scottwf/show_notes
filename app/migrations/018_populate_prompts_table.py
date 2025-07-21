import sqlite3
import os
import sys
import inspect

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import prompts, prompt_builder

def upgrade(conn):
    cursor = conn.cursor()

    # From prompts.py
    for var_name, var_value in inspect.getmembers(prompts):
        if isinstance(var_value, str) and "PROMPT" in var_name.upper():
            cursor.execute("INSERT OR IGNORE INTO prompts (name, prompt) VALUES (?, ?)", (var_name, var_value))

    # From prompt_builder.py
    for name, func in inspect.getmembers(prompt_builder, inspect.isfunction):
        if name.startswith('build_'):
            docstring = inspect.getdoc(func)
            if docstring:
                cursor.execute("INSERT OR IGNORE INTO prompts (name, prompt) VALUES (?, ?)", (name, docstring))

    conn.commit()

if __name__ == '__main__':
    INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
    DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))
    conn = sqlite3.connect(DB_PATH)
    upgrade(conn)
    conn.close()
