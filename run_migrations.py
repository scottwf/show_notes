#!/usr/bin/env python3
"""Run all database migrations in order"""

import os
import subprocess
import glob

migrations_dir = 'app/migrations'
migration_files = sorted(glob.glob(os.path.join(migrations_dir, '*.py')))

print(f"\nRunning {len(migration_files)} migrations...\n")

for migration in migration_files:
    if '__pycache__' in migration or '__init__' in migration:
        continue

    filename = os.path.basename(migration)
    print(f"▶️  {filename}")

    result = subprocess.run(['python3', migration], capture_output=True, text=True)

    if result.returncode != 0:
        if 'already exists' in result.stderr or 'duplicate column' in result.stderr:
            print(f"   ✓ (already exists)")
        else:
            print(f"   ⚠️  {result.stderr.strip()[:100]}")
    else:
        if result.stdout:
            print(f"   ✓ {result.stdout.strip()[:50]}")

print("\n✅ Migrations complete!\n")
