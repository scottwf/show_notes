#!/usr/bin/env python3
"""
Trigger initial library syncs after onboarding
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.utils import sync_radarr_library, sync_sonarr_library, sync_tautulli_watch_history

def main():
    print("\n" + "="*70)
    print(" "*20 + "INITIAL LIBRARY SYNC")
    print("="*70)
    print()

    app = create_app()

    with app.app_context():
        # Sync Radarr
        print("▶️  Starting Radarr library sync...")
        try:
            result = sync_radarr_library()
            print(f"✅ Radarr sync complete: {result}")
        except Exception as e:
            print(f"❌ Radarr sync failed: {e}")

        print()

        # Sync Sonarr
        print("▶️  Starting Sonarr library sync...")
        try:
            result = sync_sonarr_library()
            print(f"✅ Sonarr sync complete: {result}")
        except Exception as e:
            print(f"❌ Sonarr sync failed: {e}")

        print()

        # Sync Tautulli (limited import)
        print("▶️  Starting Tautulli history import (last 1000 records)...")
        try:
            result = sync_tautulli_watch_history(full_import=False, max_records=1000)
            print(f"✅ Tautulli import complete: {result}")
        except Exception as e:
            print(f"❌ Tautulli import failed: {e}")

    print()
    print("="*70)
    print("✅ Initial sync complete!")
    print("="*70)
    print()

if __name__ == '__main__':
    main()
