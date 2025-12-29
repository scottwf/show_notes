#!/usr/bin/env python3
"""
Database Reset Script - Complete Fresh Start

This script:
1. Backs up the current database
2. Deletes the database file
3. Recreates the database by running the app initialization
4. This will trigger onboarding on next app start

WARNING: This will DELETE ALL DATA including:
- Users and authentication
- Shows, episodes, movies
- Watch history
- Settings and API keys
- Favorites and profiles
- Everything!
"""

import os
import shutil
from datetime import datetime

# Paths
INSTANCE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
DB_PATH = os.path.join(INSTANCE_FOLDER, 'shownotes.sqlite3')
BACKUP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_backups')

def main():
    print("\n" + "="*70)
    print(" "*15 + "DATABASE RESET SCRIPT")
    print("="*70)
    print("\n⚠️  WARNING: This will PERMANENTLY DELETE all data!")
    print("\nThis includes:")
    print("  • All user accounts and authentication")
    print("  • All shows, seasons, and episodes")
    print("  • All movies")
    print("  • All watch history from Plex/Tautulli")
    print("  • All settings and API configurations")
    print("  • All user profiles, favorites, and history")
    print("  • Cast information and character data")
    print("  • Event logs")
    print("  • EVERYTHING\n")

    # Check if database exists
    if not os.path.exists(DB_PATH):
        print(f"✅ No database found at {DB_PATH}")
        print("   Database is already clean. Next app start will trigger onboarding.\n")
        return

    # Show current database size
    db_size = os.path.getsize(DB_PATH)
    db_size_mb = db_size / (1024 * 1024)
    print(f"📊 Current database: {db_size_mb:.2f} MB\n")

    # Confirmation
    response = input("Type 'DELETE EVERYTHING' to continue: ")
    if response != "DELETE EVERYTHING":
        print("\n❌ Cancelled. No changes made.\n")
        return

    print("\n🔄 Starting database reset...\n")

    # Create backup folder
    os.makedirs(BACKUP_FOLDER, exist_ok=True)

    # Backup current database
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_FOLDER, f'shownotes_backup_{timestamp}.sqlite3')

    try:
        print(f"💾 Creating backup: {backup_path}")
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ Backup created successfully\n")
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        print("   Aborting reset to preserve data.\n")
        return

    # Delete the database
    try:
        print(f"🗑️  Deleting database: {DB_PATH}")
        os.remove(DB_PATH)
        print("✅ Database deleted\n")
    except Exception as e:
        print(f"❌ Failed to delete database: {e}\n")
        return

    # Delete cached images
    static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'static')
    cache_folders = [
        os.path.join(static_folder, 'posters'),
        os.path.join(static_folder, 'backgrounds'),
        os.path.join(static_folder, 'cast')
    ]

    for folder in cache_folders:
        if os.path.exists(folder):
            try:
                print(f"🗑️  Clearing cache: {folder}")
                for file in os.listdir(folder):
                    file_path = os.path.join(folder, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                print(f"✅ Cache cleared: {folder}")
            except Exception as e:
                print(f"⚠️  Failed to clear {folder}: {e}")

    print("\n" + "="*70)
    print("✅ Database reset complete!")
    print("="*70)
    print(f"\n📁 Backup saved to: {backup_path}")
    print("\n📋 Next steps:")
    print("  1. Restart the Flask application")
    print("  2. Visit the app in your browser")
    print("  3. You will be redirected to onboarding")
    print("  4. Create admin account and configure services")
    print("  5. Use Admin > Tasks to sync Sonarr/Radarr libraries")
    print("  6. Use Admin > Tasks > 'Wipe & Fresh Import' to import Tautulli history\n")

if __name__ == '__main__':
    main()
