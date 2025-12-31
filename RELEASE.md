# Release Management Guide

This guide explains how to create releases and safely upgrade ShowNotes installations.

## Overview

ShowNotes uses:
- **Semantic Versioning** (MAJOR.MINOR.PATCH)
- **Tagged GitHub Releases** for stable versions
- **Database Migrations** for schema changes
- **Upgrade Script** for safe deployments

## Version Numbering

- **MAJOR** (1.x.x): Breaking changes, major new features
- **MINOR** (x.1.x): New features, backwards compatible
- **PATCH** (x.x.1): Bug fixes, minor improvements
- **-dev** suffix: Development/unreleased code

**Examples:**
- `1.0.0` - First stable release
- `1.1.0` - Added personal recommendations feature
- `1.1.1` - Fixed notification bug
- `1.2.0-dev` - Development version, not released yet

## Creating a Release

### 1. Prepare the Release

```bash
# Update VERSION file
echo "1.0.0" > VERSION

# Update CHANGELOG (create if needed)
cat >> CHANGELOG.md <<EOF

## [1.0.0] - $(date +%Y-%m-%d)

### Added
- Initial stable release
- User profiles with custom lists
- Watch progress tracking
- Problem reporting system

### Fixed
- Toast notification styling
- Episode progress tracking

EOF

# Commit version bump
git add VERSION CHANGELOG.md
git commit -m "Release v1.0.0"
```

### 2. Create Git Tag

```bash
# Create annotated tag
git tag -a v1.0.0 -m "Release version 1.0.0

Initial stable release with:
- User profiles and social features
- Toast notifications
- Plex OAuth integration
- Real-time watch tracking"

# Push tag to GitHub
git push origin v1.0.0
```

### 3. Create GitHub Release

1. Go to https://github.com/scottwf/show_notes/releases
2. Click "Draft a new release"
3. Select the tag (v1.0.0)
4. Title: "ShowNotes v1.0.0"
5. Copy release notes from CHANGELOG.md
6. Attach any installation guides/assets
7. Click "Publish release"

### 4. Bump Development Version

```bash
# After release, bump VERSION for continued development
echo "1.1.0-dev" > VERSION
git add VERSION
git commit -m "Bump version to 1.1.0-dev"
git push
```

## Upgrading Between Releases

### For Administrators

#### Pre-Upgrade Checklist

- [ ] Backup database: `cp instance/shownotes.sqlite3 instance/shownotes.sqlite3.backup`
- [ ] Note current version: `cat VERSION`
- [ ] Stop Flask server: `sudo systemctl stop shownotes`
- [ ] Pull latest code: `git fetch --tags && git checkout v1.1.0`

#### Run Upgrade

```bash
# Check what will be done
python3 upgrade.py --status
python3 upgrade.py --dry-run

# Run upgrade
python3 upgrade.py

# Restart server
sudo systemctl restart shownotes
```

#### Post-Upgrade Verification

1. Check server started: `sudo systemctl status shownotes`
2. Visit application in browser
3. Verify profile page loads
4. Check Admin > Event Logs for errors
5. Test key features (login, watch tracking, etc.)

### Troubleshooting Failed Upgrades

**If upgrade fails:**

1. **Don't panic** - database is unchanged if migration failed
2. Check error message from upgrade script
3. Review migration file that failed
4. Restore backup if needed:
   ```bash
   cp instance/shownotes.sqlite3.backup instance/shownotes.sqlite3
   ```
5. Report issue on GitHub
6. Revert to previous version:
   ```bash
   git checkout v1.0.0
   sudo systemctl restart shownotes
   ```

## Migration System

### How It Works

1. Each migration has a number (001, 002, etc.)
2. `schema_migrations` table tracks what's applied
3. Upgrade script only runs pending migrations
4. Migrations are idempotent (safe to run multiple times)

### Creating a New Migration

```bash
# Find next migration number
ls -1 app/migrations/*.py | tail -1  # Shows last migration

# Create new migration
cat > app/migrations/055_add_feature.py <<'EOF'
"""
Migration 055: Add new feature

Description of what this migration does.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Your SQL changes here
        cur.execute('''
            ALTER TABLE users ADD COLUMN new_field TEXT
        ''')

        conn.commit()
        print("✓ Added new_field to users table")

    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("✓ Column already exists")
        else:
            conn.rollback()
            raise
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
EOF

# Test migration
python3 app/migrations/055_add_feature.py
```

### Migration Best Practices

1. **Test on a copy first** - Never test on production database
2. **Use IF NOT EXISTS** - Makes migrations idempotent
3. **Handle errors gracefully** - Check for duplicate columns/tables
4. **Add data migration** - If changing schema, migrate existing data
5. **Document changes** - Clear description at top of file

## Development vs Production

### Testing Instance (Your Current Setup)

- Runs latest `main` branch code
- Pull changes anytime: `git pull`
- Can break things - that's okay!
- Test new features here first

### Production Instance (User-Facing)

- Runs tagged releases only
- Deploy process:
  ```bash
  git fetch --tags
  git checkout v1.0.0
  python3 upgrade.py
  sudo systemctl restart shownotes
  ```
- Only upgrade when release is stable
- Users don't see broken features

## Release Workflow Example

### Scenario: Adding Horizontal Scroll Feature

1. **Development (Testing Instance)**
   ```bash
   # Work on feature in main branch
   git checkout main
   # Code, test, commit changes
   # Create migration if needed
   git push
   ```

2. **Testing Phase**
   - Use feature on testing instance
   - Fix bugs, iterate
   - Document changes

3. **Release (Production)**
   ```bash
   # Update version
   echo "1.1.0" > VERSION

   # Create release tag
   git tag -a v1.1.0 -m "Add horizontal scroll section"
   git push origin v1.1.0

   # Create GitHub release
   # ...
   ```

4. **Deploy to Production**
   ```bash
   # On production server
   git fetch --tags
   git checkout v1.1.0
   python3 upgrade.py
   sudo systemctl restart shownotes
   ```

5. **Continue Development**
   ```bash
   # Back on testing instance
   echo "1.2.0-dev" > VERSION
   git commit -m "Bump to 1.2.0-dev"
   ```

## Rollback Procedure

If a release has critical issues:

```bash
# 1. Stop server
sudo systemctl stop shownotes

# 2. Restore database backup
cp instance/shownotes.sqlite3.backup instance/shownotes.sqlite3

# 3. Revert to previous release
git checkout v1.0.0

# 4. Restart server
sudo systemctl restart shownotes

# 5. Investigate issue, fix, create patch release
```

## Quick Reference

```bash
# Check migration status
python3 upgrade.py --status

# Dry run upgrade
python3 upgrade.py --dry-run

# Run upgrade
python3 upgrade.py

# Create release
git tag -a v1.0.0 -m "Release message"
git push origin v1.0.0

# Deploy production
git fetch --tags && git checkout v1.0.0 && python3 upgrade.py
```

## Support

- **Issues**: https://github.com/scottwf/show_notes/issues
- **Docs**: Check `/docs` directory
- **Logs**: Admin > Event Logs in web UI
