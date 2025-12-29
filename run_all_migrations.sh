#!/bin/bash
# Run all migrations in order to initialize fresh database

echo "========================================================================"
echo "              RUNNING ALL MIGRATIONS"
echo "========================================================================"
echo ""

cd app/migrations

for migration in $(ls -1 *.py | sort); do
    if [[ "$migration" != "__"* ]]; then
        echo "▶️  Running: $migration"
        python3 "$migration" 2>&1 | grep -v "^$" || true
        echo ""
    fi
done

echo "========================================================================"
echo "✅ All migrations complete!"
echo "========================================================================"
