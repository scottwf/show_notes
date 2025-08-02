# Service ID Mapping and Database Schema Reference

This document tracks how different external service IDs map to our internal database schema. This is critical for maintaining data consistency and avoiding confusion when building features that cross multiple services.

## Overview

The Show Notes application integrates with multiple external services, each with their own ID systems. Understanding how these IDs relate to our database is essential for proper data handling.

## Database Tables and ID Relationships

### Shows/Series

| Service | ID Field | Our DB Table | Our DB Column | Notes |
|---------|----------|--------------|---------------|-------|
| TMDB | `tmdb_id` | `sonarr_shows` | `tmdb_id` | Primary external identifier |
| Sonarr | `sonarr_id` | `sonarr_shows` | `sonarr_id` | Sonarr's internal series ID |
| TVDB | `tvdb_id` | `sonarr_shows` | `tvdb_id` | Legacy TV database ID |
| IMDb | `imdb_id` | `sonarr_shows` | `imdb_id` | IMDb identifier |
| Plex | `rating_key` | `plex_activity_log` | `rating_key` | Plex's internal ID |

**Primary Key:** `sonarr_shows.id` (auto-increment)
**URL Parameter:** Uses `tmdb_id` in routes like `/show/<int:tmdb_id>`

### Episodes

| Service | ID Field | Our DB Table | Our DB Column | Notes |
|---------|----------|--------------|---------------|-------|
| TMDB | `tmdb_id` | `sonarr_episodes` | `tmdb_id` | Episode-specific TMDB ID |
| Sonarr | `sonarr_id` | `sonarr_episodes` | `sonarr_id` | Sonarr's episode ID |
| TVDB | `tvdb_id` | `sonarr_episodes` | `tvdb_id` | TVDB episode ID |
| Plex | `rating_key` | `plex_activity_log` | `rating_key` | Plex episode ID |

**Primary Key:** `sonarr_episodes.id` (auto-increment)
**URL Parameter:** Uses `show_tmdb_id`, `season_number`, `episode_number` in routes
**Foreign Key:** `show_tmdb_id` links to `sonarr_shows.tmdb_id`

### Characters/Actors

| Service | ID Field | Our DB Table | Our DB Column | Notes |
|---------|----------|--------------|---------------|-------|
| TMDB | `actor_id` | `episode_characters` | `actor_id` | TMDB person/actor ID |
| Plex | `actor_id` | `episode_characters` | `actor_id` | Same as TMDB in most cases |

**Primary Key:** `episode_characters.id` (auto-increment) **← CRITICAL: This is what we use in URLs**
**URL Parameter:** Uses `character_id` (the primary key) in routes like `/character/<show_id>/<season>/<episode>/<character_id>`
**Foreign Key:** `show_tmdb_id` links to `sonarr_shows.tmdb_id`

### Movies

| Service | ID Field | Our DB Table | Our DB Column | Notes |
|---------|----------|--------------|---------------|-------|
| TMDB | `tmdb_id` | `radarr_movies` | `tmdb_id` | Primary external identifier |
| Radarr | `radarr_id` | `radarr_movies` | `radarr_id` | Radarr's internal movie ID |
| IMDb | `imdb_id` | `radarr_movies` | `imdb_id` | IMDb identifier |

**Primary Key:** `radarr_movies.id` (auto-increment)
**URL Parameter:** Uses `tmdb_id` in routes like `/movie/<int:tmdb_id>`

## Critical Route Patterns

### Show Detail
- **Route:** `/show/<int:tmdb_id>`
- **Parameter:** `tmdb_id` (TMDB show ID)
- **Database Query:** `SELECT * FROM sonarr_shows WHERE tmdb_id = ?`

### Episode Detail
- **Route:** `/show/<int:tmdb_id>/<int:season_number>/<int:episode_number>`
- **Parameters:** `tmdb_id`, `season_number`, `episode_number`
- **Database Query:** `SELECT * FROM sonarr_episodes WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?`

### Character Detail
- **Route:** `/character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:character_id>`
- **Parameters:** `show_id` (TMDB show ID), `season_number`, `episode_number`, `character_id` (PRIMARY KEY)
- **Database Query:** `SELECT * FROM episode_characters WHERE id = ?`
- **⚠️ IMPORTANT:** `character_id` is the auto-increment primary key, NOT the `actor_id` field

### Movie Detail
- **Route:** `/movie/<int:tmdb_id>`
- **Parameter:** `tmdb_id` (TMDB movie ID)
- **Database Query:** `SELECT * FROM radarr_movies WHERE tmdb_id = ?`

## Data Flow Examples

### Character Link from Episode Page
1. Episode page queries: `SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?`
2. Template generates link with: `character_id=char.id` (PRIMARY KEY)
3. Character page receives: `character_id` parameter
4. Character page queries: `SELECT * FROM episode_characters WHERE id = ?` (using PRIMARY KEY)

### Show Navigation
1. Search/homepage links to: `/show/<tmdb_id>`
2. Show page queries: `SELECT * FROM sonarr_shows WHERE tmdb_id = ?`
3. Episode links use: `/show/<tmdb_id>/<season>/<episode>`
4. Episode page queries episodes by: `show_tmdb_id = tmdb_id`

## Common Pitfalls

### Character ID Confusion
- ❌ **Wrong:** Using `actor_id` as the URL parameter
- ✅ **Correct:** Using `id` (primary key) as the URL parameter
- **Reason:** Multiple characters can have the same `actor_id` across different episodes

### Foreign Key Relationships
- Shows use `tmdb_id` as the business key
- Episodes link to shows via `show_tmdb_id` → `sonarr_shows.tmdb_id`
- Characters link to shows via `show_tmdb_id` → `sonarr_shows.tmdb_id`

### Service Webhooks
- **Plex:** Uses `rating_key` for identification
- **Sonarr:** Uses internal `seriesId` and `episodeId`
- **Radarr:** Uses internal `movieId`
- Always map these back to TMDB IDs for consistency

## LLM Data Storage

LLM-generated character summaries are stored directly in the `episode_characters` table:
- `llm_relationships`, `llm_motivations`, `llm_quote`, `llm_traits`, `llm_events`, `llm_importance`
- `llm_raw_response`, `llm_last_updated`, `llm_source`

Updates use: `UPDATE episode_characters SET ... WHERE id = ?` (using primary key)

## Recent Fixes & Updates

### Character ID System (December 2025)
**Issue:** Character pages were using `actor_id` instead of primary key, causing "Character not found" errors and incorrect character associations.

**Solution:** 
- Updated `episode_detail.html` to pass `character_id=char.id` (primary key) instead of `actor_id=char.actor_id`
- Modified `character_detail` route in `main.py` to expect `character_id` parameter and query by primary key
- Removed problematic JOIN that was failing due to TMDB ID mismatches between character data and show data
- Added separate show title lookup to handle data inconsistencies gracefully

**Impact:** Character pages now load reliably and display correct character information.

### LLM Context Enhancement (December 2025)
**Enhancement:** Added comprehensive context to character summary prompts to reduce hallucinations.

**Implementation:**
- Enhanced `build_character_prompt` and `build_character_chat_prompt` in `prompt_builder.py`
- Added `show_context` (overview, year), `episode_context` (title, overview), and `character_context` (actor name, other characters)
- Modified `character_detail` route to fetch and pass context data to LLM functions
- Added explicit instructions to LLM to avoid assumptions and state "Not available" when uncertain

**Result:** More accurate, character-specific summaries with reduced hallucinations.

### UI Readability Improvements (December 2025)
**Issue:** Transparent backgrounds on show detail page made text difficult to read in light mode.

**Solution:**
- Increased background opacity on show description section from 95% to 98% in light mode
- Standardized dark mode opacity to 95% for consistency
- Changed semi-transparent borders to solid borders for better definition
- Applied similar fixes to "Next Episode" and "Seasons & Episodes" sections

**Result:** Clear text readability in both light and dark modes.

## Future Considerations

- **Character Data Consistency:** Address TMDB ID mismatches that can cause characters to appear in wrong episodes/shows
- Consider creating a dedicated `characters` table if character data becomes more complex
- May need to handle actor aliases and character variations across episodes
- TMDB API rate limiting may require caching strategies for character data
- **LLM Cache Management:** Implement more sophisticated caching strategies to balance accuracy with performance