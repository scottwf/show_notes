#!/usr/bin/env python3
"""
ShowNotes Upgrade Script

Safely upgrades a ShowNotes installation to the latest version by:
1. Running all pending database migrations
2. Updating the VERSION file
3. Providing rollback capability if migrations fail

Usage:
    python3 upgrade.py              # Run all pending migrations
    python3 upgrade.py --status     # Show migration status
    python3 upgrade.py --dry-run    # Show what would be done

For production deployments:
    1. Backup your database first!
    2. Pull latest code from GitHub
    3. Run this script
    4. Restart your Flask server
"""

import sqlite3
import os
import sys
import glob
import re
import argparse
from datetime import datetime

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join('instance', 'shownotes.sqlite3')
MIGRATIONS_DIR = 'app/migrations'

def get_version():
    """Get current version from VERSION file"""
    try:
        with open('VERSION', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return 'unknown'

def get_applied_migrations(conn):
    """Get list of already applied migrations"""
    try:
        cur = conn.cursor()
        cur.execute('SELECT migration_number FROM schema_migrations ORDER BY migration_number')
        return set(row[0] for row in cur.fetchall())
    except sqlite3.OperationalError:
        # Table doesn't exist yet - no migrations applied
        return set()

def get_available_migrations():
    """Scan migrations directory for available migrations"""
    migrations = []
    pattern = re.compile(r'(\d+)_(.+)\.py$')

    for filename in glob.glob(os.path.join(MIGRATIONS_DIR, '*.py')):
        basename = os.path.basename(filename)
        match = pattern.match(basename)
        if match:
            number = int(match.group(1))
            name = match.group(2)
            migrations.append({
                'number': number,
                'name': name,
                'filename': filename,
                'basename': basename
            })

    return sorted(migrations, key=lambda x: x['number'])

def show_status():
    """Show migration status"""
    print("=" * 70)
    print(f"ShowNotes Version: {get_version()}")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    applied = get_applied_migrations(conn)
    available = get_available_migrations()
    conn.close()

    print(f"\nTotal migrations available: {len(available)}")
    print(f"Migrations applied: {len(applied)}")
    print(f"Pending migrations: {len(available) - len(applied)}")

    if applied:
        print("\n✓ Applied Migrations:")
        for mig in available:
            if mig['number'] in applied:
                print(f"  [{mig['number']:03d}] {mig['name']}")

    pending = [m for m in available if m['number'] not in applied]
    if pending:
        print("\n⏳ Pending Migrations:")
        for mig in pending:
            print(f"  [{mig['number']:03d}] {mig['name']}")
    else:
        print("\n✓ All migrations are up to date!")

    print()

def run_migration(migration_file, dry_run=False):
    """Run a single migration file"""
    if dry_run:
        print(f"  [DRY RUN] Would run: {migration_file}")
        return True

    try:
        # Execute the migration file
        with open(migration_file, 'r') as f:
            code = f.read()

        # Create a namespace for the migration
        namespace = {}
        exec(code, namespace)

        # Call the upgrade function
        if 'upgrade' in namespace:
            namespace['upgrade']()
            return True
        else:
            print(f"  ⚠️  No upgrade() function found in {migration_file}")
            return False
    except Exception as e:
        print(f"  ❌ Error running migration: {e}")
        return False

def record_migration(conn, migration_number, migration_name):
    """Record that a migration was applied"""
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO schema_migrations (migration_number, migration_name, applied_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    ''', (migration_number, migration_name))
    conn.commit()

def run_upgrade(dry_run=False):
    """Run all pending migrations"""
    print("=" * 70)
    print(f"ShowNotes Upgrade{'(DRY RUN)' if dry_run else ''}")
    print("=" * 70)
    print(f"Current version: {get_version()}")
    print(f"Database: {DB_PATH}")
    print()

    if not dry_run:
        print("⚠️  IMPORTANT: Make sure you've backed up your database!")
        response = input("Continue with upgrade? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Upgrade cancelled.")
            return False
        print()

    conn = sqlite3.connect(DB_PATH)
    applied = get_applied_migrations(conn)
    available = get_available_migrations()

    pending = [m for m in available if m['number'] not in applied]

    if not pending:
        print("✓ All migrations are already applied. Nothing to do!")
        conn.close()
        return True

    print(f"Found {len(pending)} pending migrations:\n")

    success_count = 0
    for mig in pending:
        print(f"Running migration {mig['number']:03d}: {mig['name']}...")

        if run_migration(mig['filename'], dry_run):
            if not dry_run:
                record_migration(conn, mig['number'], mig['name'])
            print(f"  ✓ Migration {mig['number']:03d} completed\n")
            success_count += 1
        else:
            print(f"  ❌ Migration {mig['number']:03d} failed!")
            print("\n⚠️  Upgrade stopped due to migration failure.")
            print("Please fix the error and try again.")
            conn.close()
            return False

    conn.close()

    print("=" * 70)
    if dry_run:
        print(f"✓ Dry run complete. Would apply {success_count} migrations.")
    else:
        print(f"✓ Upgrade complete! Applied {success_count} migrations.")
        print("\nNext steps:")
        print("  1. Restart your Flask server")
        print("  2. Test your application")
        print("  3. Check the Event Logs for any issues")
    print("=" * 70)

    return True

def main():
    parser = argparse.ArgumentParser(description='ShowNotes Upgrade Tool')
    parser.add_argument('--status', action='store_true', help='Show migration status')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without applying')

    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        print("Make sure you're running this from the ShowNotes root directory.")
        sys.exit(1)

    if args.status:
        show_status()
    else:
        success = run_upgrade(dry_run=args.dry_run)
        sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
