# Codebase Refactor Design

**Date:** 2026-07-03  
**Scope:** Dead code removal + media routes restructure + admin route audit  
**Branch:** dev (`/home/scott/projects/show_notes_dev`)

---

## Background

ShowNotes originally planned a subtitle-based recap pipeline. That feature was discarded — the codebase now uses Sonarr episode descriptions for LLM-grounded summaries instead. However, the subtitle/recap infrastructure was never cleaned up and remains wired into every admin route file. Separately, `media_routes.py` grew to 2050 lines handling shows, movies, search, and members — it needs splitting into focused files.

---

## Part 1: Dead Code Removal

### Files to delete

- `app/parse_subtitles.py`
- `app/recap_pipeline.py`
- `app/prompt_builder.py`
- `app/prompts.py`
- `app/templates/admin_recap_pipeline.html`

### Code to remove from existing files

**All 7 admin route files** (dashboard.py, logs.py, management.py, settings.py, sync_tasks.py, llm.py, __init__.py):
- Remove the top-of-file import: `from ...parse_subtitles import process_all_subtitles`

**`app/routes/admin/llm.py`** — remove 4 recap routes (~lines 993–1143):
- `recap_pipeline` (GET `/recap-pipeline`)
- `recap_pipeline_generate_season` (POST `/recap-pipeline/generate-season`)
- `recap_pipeline_generate_episode` (POST `/recap-pipeline/generate-episode`)
- `recap_pipeline_view_season` (GET `/recap-pipeline/view/<recap_id>`)

**`app/routes/admin/__init__.py`** — remove nav entry:
- `{'title': 'Recap Pipeline (Subtitle-First)', 'category': 'Admin Page', 'url_func': ...}`

### What stays

`summary_services.py`, `llm_services.py`, and all LLM routes in `admin/llm.py` are untouched. These use Sonarr episode descriptions for grounded summaries — a different, kept feature.

---

## Part 2: `media_routes.py` Split

Currently 2050 lines. Split into 4 focused files under `app/routes/main/`:

### `show_routes.py`
- `show_detail` (`/show/<tmdb_id>`)
- `episode_detail` (`/show/<tmdb_id>/season/<n>/episode/<n>`)
- `character_detail` (`/character/<show_id>/...`)
- `generate_show_summary_route` (`/api/generate-show-summary`)
- `generate_season_summary_route` (`/api/generate-season-summary`)
- `summary_feedback` (`/api/summary/feedback`)
- `get_next_up_episode` (helper, local to this file)

### `movie_routes.py`
- `movie_detail` (`/movie/<tmdb_id>`)

### `search_routes.py`
- `search` (`/search`)
- `discover` (`/discover`)

### `members_routes.py`
- `members` (`/members`)
- `public_profile` (`/members/<username>`)
- `public_subprofile` (`/members/<username>/<member_id>`)
- `_build_public_profile_context` (private helper, stays in this file)

### `_shared.py` additions
Move these private helpers out of `media_routes.py` into the existing `_shared.py`:
- `_get_tautulli_rating_key_for_media`
- `_build_admin_service_links`
- `_calculate_year_display`

### Blueprint registration
`routes/main/__init__.py` imports routes from each new file. No URL changes. No behavior changes.

---

## Part 3: Admin Route Audit

No restructuring needed. After recap removal, `admin/llm.py` lands ~1010 lines but is cohesive — all LLM admin surface area. Other admin files are all under 600 lines and well-scoped.

---

## Out of Scope

- Template audit (follow-up project after this lands)
- Feature changes of any kind
- Database or migration changes

---

## Success Criteria

- Dev container builds and starts clean
- No references to `parse_subtitles`, `recap_pipeline`, `prompt_builder`, or `prompts` remain in any non-archive file
- All existing routes respond correctly (URLs unchanged)
- No file in `app/routes/` exceeds ~1100 lines
