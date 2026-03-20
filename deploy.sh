#!/bin/bash
# ShowNotes Docker Deployment Script
# Usage: ./deploy.sh [--fresh]
#   --fresh: Force rebuild with no cache

set -e

# --- Configuration ---
COMPOSE_DIR="/home/docker/compose/shownotes"
APPDATA_DIR="/home/docker/appdata/shownotes"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
EXPECTED_UID=1000
EXPECTED_GID=1000

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; }

# --- Parse args ---
NO_CACHE=""
if [ "$1" = "--fresh" ]; then
    NO_CACHE="--no-cache"
    info "Fresh build requested (no cache)"
fi

# --- Pre-flight checks ---
echo ""
echo "========================================="
echo "  ShowNotes Deploy"
echo "========================================="
echo ""

# Check Docker is available
if ! command -v docker &> /dev/null; then
    error "Docker not found. Install Docker first."
    exit 1
fi

# --- Create directories ---
info "Ensuring directories exist..."
mkdir -p "$APPDATA_DIR"/{logs,static/{poster,background,cast,uploads}}
mkdir -p "$COMPOSE_DIR"

# --- Copy compose and env files ---
info "Syncing compose files to $COMPOSE_DIR..."
cp "$SOURCE_DIR/docker-compose.yml" "$COMPOSE_DIR/docker-compose.yml"
cp "$SOURCE_DIR/Dockerfile" "$COMPOSE_DIR/Dockerfile"

# Copy .env.example if no .env exists yet
if [ ! -f "$COMPOSE_DIR/.env" ]; then
    warn "No .env found in $COMPOSE_DIR — copying .env.example"
    cp "$SOURCE_DIR/.env.example" "$COMPOSE_DIR/.env"
    warn "Edit $COMPOSE_DIR/.env before first run!"
fi

# Sync the full source tree so Docker build context has everything
info "Syncing source code to $COMPOSE_DIR..."
rsync -a --delete \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='instance' \
    --exclude='logs' \
    --exclude='node_modules' \
    --exclude='.env' \
    --exclude='app/static/poster' \
    --exclude='app/static/background' \
    --exclude='app/static/cast' \
    --exclude='app/static/uploads' \
    "$SOURCE_DIR/" "$COMPOSE_DIR/"

# --- Fix permissions on app data ---
info "Fixing permissions on $APPDATA_DIR..."

fix_ownership() {
    local path="$1"
    local current_uid current_gid
    current_uid=$(stat -c '%u' "$path" 2>/dev/null)
    current_gid=$(stat -c '%g' "$path" 2>/dev/null)

    if [ "$current_uid" != "$EXPECTED_UID" ] || [ "$current_gid" != "$EXPECTED_GID" ]; then
        warn "Fixing ownership on $path (was $current_uid:$current_gid)"
        if [ -w "$path" ] || [ "$(id -u)" = "0" ]; then
            chown "$EXPECTED_UID:$EXPECTED_GID" "$path"
        else
            sudo chown "$EXPECTED_UID:$EXPECTED_GID" "$path"
        fi
    fi
}

# Fix database file if it exists
if [ -f "$APPDATA_DIR/shownotes.sqlite3" ]; then
    fix_ownership "$APPDATA_DIR/shownotes.sqlite3"
fi

# Fix data directories
for dir in "$APPDATA_DIR" "$APPDATA_DIR/logs" \
           "$APPDATA_DIR/static" "$APPDATA_DIR/static/poster" \
           "$APPDATA_DIR/static/background" "$APPDATA_DIR/static/cast" \
           "$APPDATA_DIR/static/uploads"; do
    if [ -d "$dir" ]; then
        fix_ownership "$dir"
    fi
done

# --- Run migrations ---
info "Running database migrations..."
if [ -f "$APPDATA_DIR/shownotes.sqlite3" ]; then
    for migration in "$SOURCE_DIR"/app/migrations/[0-9]*.py; do
        if [ -f "$migration" ]; then
            migration_name=$(basename "$migration")
            info "  Running $migration_name..."
            SHOWNOTES_DB="$APPDATA_DIR/shownotes.sqlite3" python3 "$migration" 2>&1 | sed 's/^/    /'
        fi
    done
else
    info "  No existing database — schema will be created on first run"
fi

# --- Build and deploy ---
cd "$COMPOSE_DIR"

if docker compose ps -a --services 2>/dev/null | grep -qx "shownotes"; then
    info "Stopping existing shownotes container (if running)..."
    docker compose stop shownotes 2>/dev/null || true
    info "Removing existing shownotes container..."
    docker compose rm -f shownotes 2>/dev/null || true
else
    info "No existing shownotes container found."
fi

info "Building Docker image..."
docker compose build $NO_CACHE shownotes 2>&1 | tail -5

info "Starting shownotes container..."
docker compose up -d --force-recreate shownotes

# --- Verify ---
echo ""
info "Waiting for container to start..."
sleep 3

if docker compose ps | grep -q "running"; then
    info "Container is running!"
    echo ""
    # Show last few log lines
    docker compose logs --tail=10 2>&1 | tail -10
    echo ""
    PORT=$(grep -oP '"\K\d+(?=:5003")' "$COMPOSE_DIR/docker-compose.yml" 2>/dev/null || echo "5003")
    info "ShowNotes is available at http://$(hostname -I | awk '{print $1}'):${PORT}"
else
    error "Container failed to start. Check logs:"
    docker compose logs --tail=20
    exit 1
fi

echo ""
echo "========================================="
echo "  Deploy complete"
echo "========================================="
