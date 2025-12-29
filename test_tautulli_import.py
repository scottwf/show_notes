#!/usr/bin/env python3
"""
Test script to trigger Tautulli wipe and fresh import
"""

from app import create_app
from app.database import get_db
from app.utils import sync_tautulli_watch_history
from app.system_logger import syslog, SystemLogger

def main():
    app = create_app()

    with app.app_context():
        db = get_db()

        # Get count before wiping
        old_count = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']
        print(f"\n📊 Current watch history records: {old_count:,}")

        # Confirm before proceeding
        response = input(f"\n⚠️  This will DELETE all {old_count:,} records and import fresh from Tautulli. Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cancelled.")
            return

        print("\n🗑️  Wiping existing watch history...")
        syslog.info(SystemLogger.SYNC, f"Test script: Wiping {old_count} existing watch history records")

        # Wipe all existing data
        db.execute('DELETE FROM plex_activity_log')
        db.commit()

        print("✅ Watch history wiped\n")
        syslog.success(SystemLogger.SYNC, "Test script: Watch history wiped, starting fresh import")

        print("📥 Starting full Tautulli import...")
        print("   (This may take several minutes for large history)")
        print("   Watch for batch progress messages...\n")

        # Do full import
        count = sync_tautulli_watch_history(full_import=True)

        print(f"\n✅ Import complete!")
        print(f"   Old records: {old_count:,}")
        print(f"   New records: {count:,}")

        # Verify final count
        final_count = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']
        print(f"   Final total: {final_count:,}")

        syslog.success(SystemLogger.SYNC, f"Test script: Fresh Tautulli import completed: {count} events imported", {
            'old_count': old_count,
            'new_count': count,
            'final_count': final_count
        })

        print("\n✨ Done! Check Admin > Event Logs for detailed progress.")

if __name__ == '__main__':
    main()
