# Release Management Guide

How to create releases and upgrade ShowNotes installations.

## Version Numbering

Semantic Versioning (MAJOR.MINOR.PATCH):
- **MAJOR** (1.x.x): Breaking changes, major features
- **MINOR** (x.1.x): New features, backwards compatible
- **PATCH** (x.x.1): Bug fixes, improvements
- **-dev** suffix: Development/unreleased code

## Creating a Release

### 1. Prepare

```bash
# Update VERSION file
echo "1.0.0" > VERSION

# Update CHANGELOG
cat >> CHANGELOG.md <<EOF

## [1.0.0] - $(date +%Y-%m-%d)

### Added
- Feature descriptions

### Fixed
- Bug fix descriptions
EOF

git add VERSION CHANGELOG.md
git commit -m "Release v1.0.0"
```

### 2. Tag

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

### 3. GitHub Release

1. Go to repository releases page
2. Draft new release from tag
3. Copy CHANGELOG notes
4. Publish

### 4. Bump Dev Version

```bash
echo "1.1.0-dev" > VERSION
git add VERSION
git commit -m "Bump version to 1.1.0-dev"
git push
```

## Upgrading

### Pre-Upgrade Checklist

- [ ] Backup database: `cp instance/shownotes.sqlite3 instance/shownotes.sqlite3.backup`
- [ ] Note current version: `cat VERSION`
- [ ] Stop service: `sudo systemctl stop shownotes`

### Upgrade Steps

```bash
# Pull latest code
git pull origin main

# Activate venv
source .venv/bin/activate

# Update dependencies
pip install -r requirements.txt --upgrade

# Rebuild CSS if needed
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify

# Restart service
sudo systemctl start shownotes
```

### Rollback

```bash
# Stop service
sudo systemctl stop shownotes

# Restore database
cp instance/shownotes.sqlite3.backup instance/shownotes.sqlite3

# Checkout previous version
git checkout v1.0.0

# Restart
sudo systemctl start shownotes
```

## Docker Updates

```bash
# Pull new image
docker-compose pull

# Restart container
docker-compose up -d
```

## Migration Safety

Database schema is managed via `init_db()` in `app/database.py` for fresh installations. Migrations have been consolidated into the main schema. For existing installations, pull the latest code and restart the application.

Always test upgrades on a non-production instance first and backup your database before upgrading.
