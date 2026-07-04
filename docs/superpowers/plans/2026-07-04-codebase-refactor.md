# Codebase Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dead subtitle/recap code and split the 2050-line `media_routes.py` into focused, single-responsibility files.

**Architecture:** Two sequential passes — first purge all subtitle/recap remnants cleanly, then restructure `media_routes.py` into five focused route files plus shared helpers. No behavior changes; all URLs stay identical.

**Tech Stack:** Python, Flask, SQLite — no new dependencies.

## Global Constraints

- All URLs must remain identical — no redirects, no renames
- Dev container must build and start cleanly after each task
- No feature changes — pure structural refactoring
- Working directory: `/home/scott/show_notes_dev`
- Container rebuild command: `cd /home/docker/compose/shownotes-dev && docker compose up -d --build`
- Container log check: `docker logs shownotes-dev --tail 20`
- Healthy log signature: `[INFO] Listening at: http://0.0.0.0:5003`

---

## File Map

### Task 1 — deletions
- Delete: `app/parse_subtitles.py`
- Delete: `app/recap_pipeline.py`
- Delete: `app/prompt_builder.py`
- Delete: `app/prompts.py`
- Delete: `app/templates/admin_recap_pipeline.html`
- Modify: `app/routes/admin/__init__.py` — remove import + nav entry
- Modify: `app/routes/admin/dashboard.py` — remove import
- Modify: `app/routes/admin/logs.py` — remove import
- Modify: `app/routes/admin/management.py` — remove import
- Modify: `app/routes/admin/settings.py` — remove import
- Modify: `app/routes/admin/sync_tasks.py` — remove import
- Modify: `app/routes/admin/llm.py` — remove import + 4 recap routes

### Task 2 — media_routes.py → home_routes.py
- Create: `app/routes/main/home_routes.py`
- Modify: `app/routes/main/media_routes.py` — remove home() and its helpers
- Modify: `app/routes/main/__init__.py` — add import

### Task 3 — media_routes.py → show_routes.py
- Create: `app/routes/main/show_routes.py`
- Modify: `app/routes/main/media_routes.py` — remove show/episode/character/summary routes
- Modify: `app/routes/main/_shared.py` — add 3 shared helpers
- Modify: `app/routes/main/__init__.py` — add import

### Task 4 — media_routes.py → movie_routes.py + search_routes.py
- Create: `app/routes/main/movie_routes.py`
- Create: `app/routes/main/search_routes.py`
- Modify: `app/routes/main/media_routes.py` — remove remaining routes (should now be empty)
- Modify: `app/routes/main/__init__.py` — add imports, remove media_routes import
- Delete: `app/routes/main/media_routes.py`

### Task 5 — media_routes.py → members_routes.py
- Note: members/ and public_profile routes are already removed in Task 4; this task extracts them from media_routes before deletion if not already done. Adjust sequencing as needed.
- Create: `app/routes/main/members_routes.py`
- Modify: `app/routes/main/__init__.py` — add import

---

## Task 1: Remove Dead Subtitle/Recap Code

**Files:**
- Delete: `app/parse_subtitles.py`
- Delete: `app/recap_pipeline.py`
- Delete: `app/prompt_builder.py`
- Delete: `app/prompts.py`
- Delete: `app/templates/admin_recap_pipeline.html`
- Modify: `app/routes/admin/__init__.py`
- Modify: `app/routes/admin/dashboard.py`
- Modify: `app/routes/admin/logs.py`
- Modify: `app/routes/admin/management.py`
- Modify: `app/routes/admin/settings.py`
- Modify: `app/routes/admin/sync_tasks.py`
- Modify: `app/routes/admin/llm.py`

**Interfaces:**
- Produces: clean admin route files with no subtitle/recap references

- [ ] **Step 1: Delete the five dead files**

```bash
rm app/parse_subtitles.py
rm app/recap_pipeline.py
rm app/prompt_builder.py
rm app/prompts.py
rm app/templates/admin_recap_pipeline.html
```

- [ ] **Step 2: Remove parse_subtitles import from all 6 admin route files**

In each of these files, find and delete the line `from ...parse_subtitles import process_all_subtitles`:

```
app/routes/admin/dashboard.py   (line ~33)
app/routes/admin/logs.py        (line ~33)
app/routes/admin/management.py  (line ~33)
app/routes/admin/settings.py    (line ~33)
app/routes/admin/sync_tasks.py  (line ~33)
app/routes/admin/llm.py         (line ~33)
```

Verify removal:
```bash
grep -r "parse_subtitles" app/routes/ --include="*.py"
# Expected: no output
```

- [ ] **Step 3: Remove recap nav entry from admin/__init__.py**

In `app/routes/admin/__init__.py`, find and delete this line (around line 100):
```python
    {'title': 'Recap Pipeline (Subtitle-First)', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.recap_pipeline')},
```

Also remove the `from ...parse_subtitles import process_all_subtitles` import from this file.

- [ ] **Step 4: Remove 4 recap routes from admin/llm.py**

In `app/routes/admin/llm.py`, delete the four route functions that start at approximately line 993 through end of file:
- `recap_pipeline` — `@admin_bp.route('/recap-pipeline')`
- `recap_pipeline_generate_season` — `@admin_bp.route('/recap-pipeline/generate-season', methods=['POST'])`
- `recap_pipeline_generate_episode` — `@admin_bp.route('/recap-pipeline/generate-episode', methods=['POST'])`
- `recap_pipeline_view_season` — `@admin_bp.route('/recap-pipeline/view/<int:recap_id>')`

Verify no recap references remain:
```bash
grep -rn "recap_pipeline\|parse_subtitles\|prompt_builder\|from app.prompts" app/ --include="*.py" | grep -v "__pycache__" | grep -v "migrations"
# Expected: no output
```

- [ ] **Step 5: Rebuild container and verify clean start**

```bash
cd /home/docker/compose/shownotes-dev && docker compose up -d --build 2>&1 | tail -10
docker logs shownotes-dev --tail 20
```

Expected in logs:
```
[INFO] Listening at: http://0.0.0.0:5003
```
No `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 6: Commit**

```bash
cd /home/scott/show_notes_dev
git add -A
git commit -m "refactor: remove dead subtitle/recap pipeline code"
```

---

## Task 2: Extract home_routes.py from media_routes.py

`home()` is lines 31–510 of `media_routes.py` — nearly 480 lines on its own. It handles the homepage with all its caching, premieres, calendar, and activity sections.

**Files:**
- Create: `app/routes/main/home_routes.py`
- Modify: `app/routes/main/media_routes.py` — remove home() block (lines 31–510)
- Modify: `app/routes/main/__init__.py` — add import

**Interfaces:**
- Produces: `home_routes.py` registering `main.home` on `GET /`

- [ ] **Step 1: Create home_routes.py**

Create `app/routes/main/home_routes.py`. Copy the entire `home()` function and its imports from `media_routes.py`. The file needs these imports (copy from the top of media_routes.py, taking only what home() uses — check references in lines 31–510):

```python
import threading
import datetime
from datetime import timezone
import sqlite3
import logging

from flask import render_template, request, redirect, url_for, session, jsonify, flash, current_app, abort
from flask_login import login_required, current_user

from ... import database
from ...data_transforms import format_datetime_simple
from . import main_bp
from ._shared import (
    get_current_member, get_user_members,
    _get_cached_value, _get_cached_image_path, _get_media_image_url,
    _get_profile_stats, _get_plex_event_details,
    _calculate_show_completion, MEMBER_AVATAR_COLORS,
)

_homepage_cache = {}
_homepage_cache_lock = threading.Lock()
```

Then paste the full `home()` function (lines 31–510 of media_routes.py) into this file.

- [ ] **Step 2: Remove home() from media_routes.py**

Delete lines 31–510 from `media_routes.py` (the `_homepage_cache`, `_homepage_cache_lock` declarations and the entire `home()` function). Also remove from the top-of-file imports in media_routes.py any imports that are now only used by home() and not by remaining functions.

- [ ] **Step 3: Register home_routes in __init__.py**

In `app/routes/main/__init__.py`, add after the existing route imports block:
```python
from . import home_routes              # noqa: F401, E402
```

- [ ] **Step 4: Rebuild and verify**

```bash
cd /home/docker/compose/shownotes-dev && docker compose up -d --build 2>&1 | tail -5
docker logs shownotes-dev --tail 10
```

Visit `http://localhost:5004/` — homepage must load without error.

- [ ] **Step 5: Commit**

```bash
cd /home/scott/show_notes_dev
git add -A
git commit -m "refactor: extract home_routes.py from media_routes.py"
```

---

## Task 3: Extract show_routes.py + move shared helpers

Extracts show/episode/character detail and summary API routes. Also moves the three private helpers that are shared across route files into `_shared.py`.

**Files:**
- Create: `app/routes/main/show_routes.py`
- Modify: `app/routes/main/media_routes.py` — remove extracted functions
- Modify: `app/routes/main/_shared.py` — add 3 helpers
- Modify: `app/routes/main/__init__.py` — add import

**Interfaces:**
- Produces: `show_routes.py` registering:
  - `main.show_detail` on `GET /show/<int:tmdb_id>`
  - `main.episode_detail` on `GET /show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>`
  - `main.character_detail` on `GET /character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:character_id>`
  - `main.summary_feedback` on `POST /api/summary/feedback`
  - `main.generate_show_summary_route` on `POST /api/generate-show-summary`
  - `main.generate_season_summary_route` on `POST /api/generate-season-summary`

- [ ] **Step 1: Move 3 helpers into _shared.py**

In `app/routes/main/media_routes.py`, find these three private functions and move them (cut, not copy) to the bottom of `app/routes/main/_shared.py`:

- `_get_tautulli_rating_key_for_media(db, media_type, tmdb_id)` — line ~609
- `_build_admin_service_links(db, media_type, media_dict)` — line ~641
- `_calculate_year_display(show_dict: dict) -> str` — line ~668

These functions have no blueprint dependency — they just use `database.get_db()` and plain Python. Check their bodies and add any missing imports to `_shared.py` (likely just `from ... import database` which is already there).

- [ ] **Step 2: Create show_routes.py**

Create `app/routes/main/show_routes.py`. Add the imports the extracted functions need (scan the bodies of show_detail, episode_detail, character_detail, summary routes):

```python
import datetime
import logging

from flask import render_template, request, redirect, url_for, session, jsonify, flash, current_app, abort
from flask_login import login_required, current_user

from ... import database
from ...data_transforms import format_datetime_simple
from . import main_bp
from ._shared import (
    get_current_member,
    _get_cached_image_path, _get_media_image_url,
    _get_tautulli_rating_key_for_media,
    _build_admin_service_links,
    _calculate_year_display,
)
```

Then paste these functions from media_routes.py into show_routes.py (in this order):
1. `get_next_up_episode` (helper, line ~944 — no route decorator, used by show_detail)
2. `show_detail` (line ~682)
3. `episode_detail` (line ~1044)
4. `character_detail` (line ~1210)
5. `summary_feedback` (line ~1546)
6. `generate_show_summary_route` (line ~1579)
7. `generate_season_summary_route` (line ~1612)

- [ ] **Step 3: Remove extracted functions from media_routes.py**

Delete from `media_routes.py`:
- The 3 helpers moved to _shared.py (~lines 609–681)
- `get_next_up_episode` and all show/episode/character/summary routes (~lines 682–1642)

Update imports at top of media_routes.py — import `_get_tautulli_rating_key_for_media`, `_build_admin_service_links`, `_calculate_year_display` from `._shared` (since movie_detail may still use them — check).

- [ ] **Step 4: Register show_routes and export new helpers**

In `app/routes/main/__init__.py`, add:
```python
from . import show_routes              # noqa: F401, E402
```

In `app/routes/main/_shared.py`, ensure the three moved helpers are exported (just having them defined at module level is sufficient — they don't need to be in an `__all__`).

- [ ] **Step 5: Rebuild and verify**

```bash
cd /home/docker/compose/shownotes-dev && docker compose up -d --build 2>&1 | tail -5
docker logs shownotes-dev --tail 10
```

Test these URLs return HTTP 200 (not 404 or 500):
- `http://localhost:5004/` (home)
- `http://localhost:5004/search` (search)

- [ ] **Step 6: Commit**

```bash
cd /home/scott/show_notes_dev
git add -A
git commit -m "refactor: extract show_routes.py, move shared helpers to _shared.py"
```

---

## Task 4: Extract movie_routes.py, search_routes.py, members_routes.py — delete media_routes.py

After Tasks 2 and 3, what remains in `media_routes.py` is:
- `movie_detail` (line ~577)
- `search` (line ~511)
- `discover` (line ~1356)
- `help` (line ~1351)
- `report_issue` (line ~1285)
- `members` (line ~1643)
- `_build_public_profile_context` (private helper, line ~1913)
- `public_profile` (line ~1980)
- `public_subprofile` (line ~2016)

**Files:**
- Create: `app/routes/main/movie_routes.py`
- Create: `app/routes/main/search_routes.py`
- Create: `app/routes/main/members_routes.py`
- Delete: `app/routes/main/media_routes.py`
- Modify: `app/routes/main/__init__.py` — swap `media_routes` import for the three new ones

**Interfaces:**
- Produces:
  - `movie_routes.py`: `main.movie_detail` on `GET /movie/<int:tmdb_id>`
  - `search_routes.py`: `main.search` on `GET /search`, `main.discover` on `GET /discover`, `main.help` on `GET /help`, `main.report_issue` on `GET|POST /report_issue/<media_type>/<media_id>`
  - `members_routes.py`: `main.members` on `GET /members`, `main.public_profile` on `GET /members/<username>`, `main.public_subprofile` on `GET /members/<username>/<int:member_id>`

- [ ] **Step 1: Create movie_routes.py**

Create `app/routes/main/movie_routes.py`:

```python
import logging

from flask import render_template, request, session, current_app
from flask_login import login_required, current_user

from ... import database
from ...data_transforms import format_datetime_simple
from . import main_bp
from ._shared import (
    get_current_member,
    _get_cached_image_path, _get_media_image_url,
    _get_tautulli_rating_key_for_media,
    _build_admin_service_links,
    _calculate_year_display,
)
```

Paste `movie_detail` from `media_routes.py` into this file (verify exact imports by checking what movie_detail's body references).

- [ ] **Step 2: Create search_routes.py**

Create `app/routes/main/search_routes.py`. Paste `search`, `discover`, `help`, and `report_issue` from `media_routes.py`. Add the imports those functions need (scan their bodies — typically `render_template`, `request`, `redirect`, `url_for`, `session`, `flash`, `login_required`, `current_user`, `database`, `get_current_member`).

- [ ] **Step 3: Create members_routes.py**

Create `app/routes/main/members_routes.py`. Paste `_build_public_profile_context`, `members`, `public_profile`, and `public_subprofile` from `media_routes.py`. Add the imports those functions need.

- [ ] **Step 4: Delete media_routes.py**

```bash
rm app/routes/main/media_routes.py
```

- [ ] **Step 5: Update __init__.py**

In `app/routes/main/__init__.py`, replace:
```python
from . import media_routes            # noqa: F401, E402
```
with:
```python
from . import home_routes              # noqa: F401, E402  (if not already present)
from . import show_routes              # noqa: F401, E402  (if not already present)
from . import movie_routes             # noqa: F401, E402
from . import search_routes            # noqa: F401, E402
from . import members_routes           # noqa: F401, E402
```

Ensure `home_routes` and `show_routes` from previous tasks are present; don't duplicate them.

- [ ] **Step 6: Verify no media_routes references remain**

```bash
grep -r "media_routes" app/ --include="*.py" | grep -v "__pycache__"
# Expected: no output
```

- [ ] **Step 7: Rebuild and verify**

```bash
cd /home/docker/compose/shownotes-dev && docker compose up -d --build 2>&1 | tail -5
docker logs shownotes-dev --tail 20
```

Expected: clean startup, no ImportError. Check these routes respond (use curl or browser):
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5004/search
# Expected: 302 (redirect to login) — not 404 or 500

curl -s -o /dev/null -w "%{http_code}" http://localhost:5004/help
# Expected: 200 or 302
```

- [ ] **Step 8: Final check — no orphaned references**

```bash
grep -rn "recap_pipeline\|parse_subtitles\|prompt_builder\|from app.prompts\|media_routes" app/ --include="*.py" | grep -v "__pycache__" | grep -v "migrations"
# Expected: no output
```

- [ ] **Step 9: Commit**

```bash
cd /home/scott/show_notes_dev
git add -A
git commit -m "refactor: split media_routes.py into movie, search, members route files"
```

---

## Post-Refactor Verification

After all tasks complete, run a final sanity check:

```bash
# Line counts — no route file should exceed 1100 lines
wc -l app/routes/main/*.py app/routes/admin/*.py | sort -n

# No dead code references
grep -rn "recap_pipeline\|parse_subtitles\|prompt_builder\|media_routes" app/ --include="*.py" | grep -v "__pycache__" | grep -v migrations

# Container healthy
docker logs shownotes-dev --tail 5
```
