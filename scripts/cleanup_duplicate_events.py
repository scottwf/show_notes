#!/usr/bin/env python3
"""
Cleanup script to remove duplicate Plex webhook events from plex_activity_log table.

This script identifies and removes duplicate events where Plex sent the same webhook twice.
It keeps the first occurrence (lowest ID) of each duplicate group.
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.database import get_db

def cleanup_duplicates():
    """Remove duplicate events from plex_activity_log."""
    app = create_app()

    with app.app_context():
        db = get_db()

        print("=" * 80)
        print("Plex Activity Log - Duplicate Cleanup Script")
        print("=" * 80)

        # Count total records before cleanup
        total_before = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']
        print(f"\nTotal records before cleanup: {total_before:,}")

        # Find duplicates - group by key fields and count
        print("\nFinding duplicate groups...")
        duplicates_query = '''
            SELECT
                session_key,
                event_type,
                rating_key,
                view_offset_ms,
                datetime(event_timestamp) as event_ts,
                COUNT(*) as dup_count,
                GROUP_CONCAT(id ORDER BY id) as all_ids
            FROM plex_activity_log
            GROUP BY
                COALESCE(session_key, 'null'),
                event_type,
                COALESCE(rating_key, 'null'),
                COALESCE(view_offset_ms, 0),
                datetime(event_timestamp)
            HAVING COUNT(*) > 1
        '''

        duplicate_groups = db.execute(duplicates_query).fetchall()

        if not duplicate_groups:
            print("\n✓ No duplicates found! Database is clean.")
            return

        total_duplicates = sum(row['dup_count'] - 1 for row in duplicate_groups)
        print(f"Found {len(duplicate_groups)} duplicate groups")
        print(f"Total duplicate records to delete: {total_duplicates:,}")

        # Show some examples
        print("\nExample duplicates:")
        for i, row in enumerate(duplicate_groups[:5], 1):
            ids = row['all_ids'].split(',')
            print(f"  {i}. Event: {row['event_type']}, Time: {row['event_ts']}, "
                  f"Count: {row['dup_count']}, IDs: {', '.join(ids[:3])}{'...' if len(ids) > 3 else ''}")

        if len(duplicate_groups) > 5:
            print(f"  ... and {len(duplicate_groups) - 5} more groups")

        # Confirm deletion
        print(f"\n⚠️  This will DELETE {total_duplicates:,} duplicate records.")
        print("The first occurrence (lowest ID) of each duplicate will be kept.")
        response = input("\nProceed with cleanup? (yes/no): ").strip().lower()

        if response != 'yes':
            print("\n✗ Cleanup cancelled.")
            return

        # Delete duplicates
        print("\nDeleting duplicates...")
        deleted_count = 0

        for row in duplicate_groups:
            # Get all IDs for this duplicate group
            all_ids = [int(id_str) for id_str in row['all_ids'].split(',')]

            # Keep the first (lowest) ID, delete the rest
            ids_to_delete = all_ids[1:]

            if ids_to_delete:
                # Delete the duplicates
                placeholders = ','.join('?' * len(ids_to_delete))
                db.execute(f'DELETE FROM plex_activity_log WHERE id IN ({placeholders})', ids_to_delete)
                deleted_count += len(ids_to_delete)

        db.commit()

        # Count total records after cleanup
        total_after = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']

        print(f"\n✓ Cleanup complete!")
        print(f"  Records before: {total_before:,}")
        print(f"  Records deleted: {deleted_count:,}")
        print(f"  Records after: {total_after:,}")
        print(f"  Expected after: {total_before - total_duplicates:,}")

        if total_after == total_before - total_duplicates:
            print("\n✓ Verification passed! All duplicates removed successfully.")
        else:
            print("\n⚠️  Warning: Record count mismatch. Please review the results.")

if __name__ == '__main__':
    try:
        cleanup_duplicates()
    except KeyboardInterrupt:
        print("\n\n✗ Cleanup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
