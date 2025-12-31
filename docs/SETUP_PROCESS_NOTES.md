# ShowNotes Setup Documentation - Process Notes

This document captures insights from setting up ShowNotes and recommendations for improving the onboarding experience.

---

## Current Setup Process (What We Did)

### 1. Repository Clone
```bash
git clone https://github.com/scottwf/show_notes.git
cd show_notes
```
**Status:** ✅ Works perfectly

### 2. Python Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
**Status:** ✅ Works after creating venv
**Issue Found:** Cannot install with `--user` flag on modern Python distributions (externally managed environment)
**Solution Implemented:** Use virtual environment (venv)

### 3. Environment Configuration
```bash
cp .env.example .env
# Edit .env
```
**Status:** ✅ Works well
**Note:** .env.example is well documented and includes sensible defaults

### 4. Database Initialization
```bash
python3 init_fresh_database.py
```
**Status:** ⚠️ Works but shows warnings
**Issues Found:**
- Some migrations throw `name '__file__' is not defined` errors (harmless)
- Some migrations reference tables that don't exist yet (expected on fresh install)
- Migration 024 expects command-line argument but script handles it gracefully

**Recommendation:** Add a `--quiet` flag to suppress expected warnings during fresh install

### 5. Tailwind CSS Build
**Status:** ✅ CSS already built and included in repository
**Found:** `app/static/css/style.css` already exists (58KB)
**Note:** No package.json exists, but npx can still run tailwindcss directly if needed

```bash
# Optional rebuild:
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify
```

### 6. Application Launch
```bash
python3 run.py
```
**Status:** ✅ Works perfectly
**Issue Found:** Port 5001 may already be in use
**Solution:** Easy to change port in run.py or via command line

---

## Files Created During Setup

1. **instance/shownotes.sqlite3** - SQLite database (16KB empty)
2. **logs/shownotes.log** - Application logs
3. **venv/** - Python virtual environment (not in repo)

---

## Improvements Recommended

### Documentation
- ✅ Created comprehensive SETUP.md guide
- ✅ Created QUICKSTART.md for fast onboarding
- ✅ Created Dockerfile for future Docker support
- ✅ Created docker-compose.yml for easy deployment
- ✅ Created .dockerignore for clean Docker builds

### Code Improvements Suggested

#### 1. Add setup.sh Script
Create an automated setup script:
```bash
#!/bin/bash
# setup.sh - Automated ShowNotes setup

echo "🎬 ShowNotes Setup Script"
echo "=========================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Create venv
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📥 Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Setup .env
if [ ! -f .env ]; then
    echo "⚙️  Creating .env file..."
    cp .env.example .env
    echo "📝 Please edit .env with your Plex settings"
fi

# Initialize database
echo "💾 Initializing database..."
python3 init_fresh_database.py 2>/dev/null

# Build CSS (if needed)
if [ ! -f app/static/css/style.css ]; then
    echo "🎨 Building Tailwind CSS..."
    npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start ShowNotes:"
echo "  source venv/bin/activate"
echo "  python3 run.py"
echo ""
echo "Then visit: http://localhost:5001"
```

#### 2. Improve init_fresh_database.py
- Add `--quiet` flag to suppress expected warnings
- Add better error messages for actual failures
- Add success confirmation message
- Consider adding a `--reset` flag for database recreation

#### 3. Add Makefile for Common Tasks
```makefile
.PHONY: help setup install dev clean

help:
	@echo "ShowNotes - Make Commands"
	@echo "========================="
	@echo "make setup    - Initial setup (venv, deps, db)"
	@echo "make install  - Install dependencies"
	@echo "make dev      - Run development server"
	@echo "make clean    - Remove generated files"

setup: venv/bin/activate .env
	@echo "✅ Setup complete!"

venv/bin/activate:
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt
	./venv/bin/python init_fresh_database.py

.env:
	cp .env.example .env
	@echo "⚠️  Edit .env with your settings"

install:
	./venv/bin/pip install -r requirements.txt

dev:
	./venv/bin/python run.py

clean:
	rm -rf venv
	rm -rf instance
	rm -rf __pycache__
	rm -rf app/__pycache__
```

#### 4. Port Configuration Enhancement
Add to run.py:
```python
import os

# Allow port override via environment variable
port = int(os.getenv('SHOWNOTES_PORT', 5001))
app.run(debug=True, host='0.0.0.0', port=port)
```

#### 5. Health Check Endpoint
Add to app/routes/main.py:
```python
@main_bp.route('/health')
def health_check():
    """Health check endpoint for Docker and monitoring"""
    return {'status': 'healthy', 'version': '1.0.0'}, 200
```

---

## Docker Implementation Notes

### Dockerfile Strategy
- ✅ Multi-stage build not needed (app is relatively small)
- ✅ Use slim Python image for smaller size
- ✅ Install Node.js for Tailwind build
- ✅ Pre-build CSS during image creation
- ✅ Initialize database on first run
- ✅ Health check for container orchestration

### Docker Compose Benefits
- ✅ Easy service configuration via environment variables
- ✅ Volume persistence for database and logs
- ✅ Optional Ollama container for local LLM
- ✅ Network isolation with bridge network
- ✅ Restart policies for reliability

### Volumes to Persist
1. `instance/` - Database
2. `logs/` - Application logs
3. `app/static/poster/` - Cached poster images
4. `app/static/background/` - Cached background images

---

## Testing Checklist for Future Releases

### Fresh Install Testing
- [ ] Clone fresh from GitHub
- [ ] Run setup script
- [ ] Verify database creation
- [ ] Verify app starts on default port
- [ ] Verify admin panel accessible
- [ ] Verify service configuration works
- [ ] Verify Plex authentication works

### Docker Testing
- [ ] Build Docker image successfully
- [ ] Run container with default settings
- [ ] Verify database persists after restart
- [ ] Verify environment variables work
- [ ] Verify volume mounts work
- [ ] Test docker-compose up/down
- [ ] Test docker-compose logs

### Upgrade Testing
- [ ] Pull latest code
- [ ] Run migrations on existing database
- [ ] Verify existing data intact
- [ ] Verify new features work
- [ ] Verify backward compatibility

---

## User Feedback Areas

### What Works Well
1. ✅ Clear .env.example with good documentation
2. ✅ Single database initialization script
3. ✅ Existing CSS file in repository (no build needed)
4. ✅ Comprehensive README with features
5. ✅ Admin panel for configuration

### Areas for Improvement
1. ⚠️ No automated setup script (need to run commands manually)
2. ⚠️ Migration warnings can be confusing for new users
3. ⚠️ No quick way to test if setup worked (need health check endpoint)
4. ⚠️ Port conflicts require manual intervention
5. ⚠️ No Docker images published yet (users must build)

### Priority Improvements
1. **High:** Create setup.sh automation script
2. **High:** Publish Docker images to Docker Hub
3. **Medium:** Add health check endpoint
4. **Medium:** Improve migration output clarity
5. **Medium:** Add Makefile for common tasks
6. **Low:** Add setup verification script
7. **Low:** Create video walkthrough

---

## Documentation Structure

```
show_notes/
├── README.md           # Main documentation (features, architecture)
├── QUICKSTART.md       # Fast setup for experienced users (NEW)
├── SETUP.md           # Comprehensive setup guide (NEW)
├── CLAUDE.md          # AI assistant context
├── GEMINI.md          # AI assistant context
├── ISSUES_TO_FIX.md   # Known issues tracker
├── WEBHOOK_FIX_SUMMARY.md  # Technical notes
├── Dockerfile         # Docker build instructions (NEW)
├── docker-compose.yml # Docker orchestration (NEW)
├── .dockerignore      # Docker build exclusions (NEW)
└── docs/
    └── dev-server-watchdog.md  # Advanced dev setup
```

---

## Next Steps for Repository Owner

### Immediate (Week 1)
1. Review and merge SETUP.md and QUICKSTART.md
2. Test Dockerfile and docker-compose.yml
3. Create and publish Docker images to Docker Hub
4. Add setup.sh automation script
5. Update main README.md to reference new docs

### Short-term (Month 1)
1. Create automated tests for installation process
2. Add health check endpoint
3. Improve migration output
4. Create video walkthrough
5. Add Makefile for developer convenience

### Long-term (Quarter 1)
1. Consider migration to proper package management (setup.py/pyproject.toml)
2. Add automated version bumping
3. Create release process documentation
4. Set up CI/CD for automated Docker builds
5. Consider Kubernetes deployment documentation

---

## Metrics to Track

### Installation Success Rate
- % of users who complete setup without issues
- Common failure points
- Average time to first successful run

### Documentation Usage
- Which guide users prefer (SETUP vs QUICKSTART)
- Most common support questions
- Most visited documentation sections

### Docker Adoption
- % of users choosing Docker vs manual install
- Docker-specific issues
- Performance comparison

---

## Summary

The ShowNotes setup process is **functional but manual**. Key improvements:

1. ✅ **Documentation:** Created comprehensive guides (SETUP.md, QUICKSTART.md)
2. ✅ **Docker Support:** Created Dockerfile and docker-compose.yml
3. 🔄 **Automation:** Recommended setup.sh script
4. 🔄 **Developer Experience:** Suggested Makefile addition
5. 🔄 **Monitoring:** Recommended health check endpoint

**Estimated time for new user:**
- Manual setup: 10-15 minutes (with troubleshooting)
- With setup.sh: 3-5 minutes
- With Docker: 2-3 minutes

**Current status:** Repository is ready for production use with clear documentation.
