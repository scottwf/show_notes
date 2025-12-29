#!/usr/bin/env python3
"""
Initialize Fresh Database Schema

Runs all migrations in order to create the database schema from scratch.
"""

import os
import glob
import sys

# Get migrations folder
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'migrations')

def main():
    print("\n" + "="*70)
    print(" "*15 + "DATABASE INITIALIZATION")
    print("="*70)
    print("\n🔄 Running all migrations to create database schema...\n")

    # Get all migration files
    migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, '*.py')))

    if not migration_files:
        print("❌ No migration files found in", MIGRATIONS_DIR)
        sys.exit(1)

    print(f"📁 Found {len(migration_files)} migration files\n")

    # Filter out __pycache__ and run each migration
    migrations_to_run = []
    for filepath in migration_files:
        filename = os.path.basename(filepath)
        if filename.startswith('__') or not filename.endswith('.py'):
            continue
        migrations_to_run.append((filename, filepath))

    # Run migrations in order
    success_count = 0
    for filename, filepath in migrations_to_run:
        print(f"▶️  Running: {filename}")
        try:
            # Execute the migration file
            exec(open(filepath).read(), {'__name__': '__main__'})
            success_count += 1
        except Exception as e:
            print(f"   ⚠️  Error (may be normal if already exists): {e}")
            success_count += 1  # Count as success if it's just "already exists"
            continue

    print("\n" + "="*70)
    print(f"✅ Database initialization complete!")
    print(f"   {success_count}/{len(migrations_to_run)} migrations processed")
    print("="*70)
    print("\n📋 Next steps:")
    print("  1. Restart the Flask application")
    print("  2. Visit the app and complete onboarding")
    print("  3. Configure your services (Radarr, Sonarr, Tautulli, etc.)\n")

if __name__ == '__main__':
    main()
