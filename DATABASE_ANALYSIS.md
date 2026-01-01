# Database Schema Analysis and Cleanup

## Executive Summary

This document provides a comprehensive analysis of the ShowNotes database schema, identifying:
- Unused columns that can be safely removed
- Tables that exist only in migrations (not in init_db)
- Deprecated tables from removed features
- Recommendations for cleanup and optimization

**Analysis Date:** 2026-01-01

## Tables Status Overview

### Tables in init_db() (Current)
```
api_usage, image_cache_queue, issue_reports, notifications, plex_activity_log,
plex_events, radarr_movies, schema_version, service_sync_status, settings,
sonarr_episodes, sonarr_seasons, sonarr_shows, subtitles, user_show_preferences, users
```

### Active Tables (Used in Application Code)
```
announcements, api_usage, episode_characters, episode_summaries, image_cache_queue,
issue_reports, plex_activity_log, problem_reports, prompt_history, radarr_movies,
schema_version, season_summaries, service_sync_status, settings, show_cast,
show_summaries, sonarr_episodes, sonarr_seasons, sonarr_shows, subtitles, system_logs,
user_announcement_views, user_episode_progress, user_favorites, user_list_items,
user_lists, user_notifications, user_recommendations, user_show_progress,
user_watch_statistics, user_watch_streaks, users, webhook_activity
```

### Tables Missing from init_db()
These tables are created via migrations but not present in the `init_db()` function.
This causes issues when initializing a fresh database.

1. **episode_characters** - Used for tracking episode cast (Plex webhook data)
2. **prompts** - LLM prompt templates (may be deprecated)
3. **prompt_history** - LLM prompt version history (may be deprecated)
4. **show_cast** - TVMaze cast/character data (actively used)
5. **user_announcement_views** - Tracks announcement dismissals
6. **user_lists** - User-created custom lists feature
7. **user_list_items** - Items in custom lists
8. **user_notifications** - User notification system
9. **webhook_activity** - Tracks Sonarr/Radarr webhook events
10. **user_favorites** - User favorites tracking (Migration 024)
11. **user_preferences** - User display preferences (Migration 024)
12. **user_watch_statistics** - Watch time tracking (Migration 041)
13. **user_genre_statistics** - Genre preference tracking (Migration 041)
14. **user_watch_streaks** - Viewing streak tracking (Migration 041)
15. **user_show_progress** - Show-level watch progress (Migration 043)
16. **user_episode_progress** - Episode-level watch tracking (Migration 043)
17. **announcements** - System announcements (Migration 045)
18. **problem_reports** - User-submitted issues (Migration 046)
19. **user_recommendations** - Show recommendations (Migration 047)
20. **system_logs** - Application logging (Migration 032)

### Deprecated Tables (Commented Out in database.py)
These tables are from removed features and should not be recreated:

1. **character_summaries** - LLM-generated character summaries (REMOVED)
2. **character_chats** - LLM chat feature (REMOVED)
3. **shows** - Replaced by sonarr_shows
4. **season_metadata** - Replaced by sonarr_seasons
5. **top_characters** - No longer used
6. **current_watch** - Replaced by user_show_progress
7. **webhook_log** - Replaced by webhook_activity
8. **autocomplete_logs** - No longer tracked

## Unused Columns Analysis

### High Priority Removals (Deprecated Features)

#### episode_characters.llm_background
- **Status:** UNUSED
- **Reason:** LLM features removed (see CLAUDE.md)
- **Action:** Remove in cleanup migration
- **Migration:** Added in 019_add_llm_background_column.py

### Medium Priority Removals (Incomplete Features)

#### user_show_preferences Columns
All notification preference columns are unused:
- `notify_new_episode`
- `notify_season_finale`
- `notify_series_finale`
- `notify_time`

**Reason:** Notification preference feature was never implemented
**Action:** Remove these columns OR implement the feature
**Recommendation:** Remove - user_notifications table provides more flexible notification system

#### users Table Profile Columns
- `external_links` - UNUSED
- `profile_is_public` - UNUSED

**Reason:** Advanced profile features not implemented
**Action:** Remove these columns OR implement privacy features
**Recommendation:** Remove for now, can be re-added if feature is planned

### Low Priority Removals (Questionable Utility)

#### radarr_movies Rating Columns
- `rating_type` - UNUSED
- `rating_votes` - UNUSED

**Note:** `rating_value` IS used, so only these two can be removed
**Reason:** Inconsistent with how sonarr_shows handles ratings
**Action:** Remove if not needed for future features

#### Other Unused Columns
- `image_cache_queue.item_db_id` - Appears redundant with `id` column
- `notifications.seen` - Should use status field instead
- `plex_activity_log.player_uuid` - Not needed for current functionality
- `webhook_activity.processed` - Never checked or updated

## Recommendations

### Phase 1: Immediate Actions (High Priority)
1. **Create comprehensive init_db() schema**
   - Add all actively used tables to database.py init_db()
   - Ensure fresh installs work correctly
   - Reference canonical migrations for each table structure

2. **Remove deprecated LLM columns**
   - Drop `episode_characters.llm_background`
   - Update migration 019 to skip this column

### Phase 2: Medium Term (Medium Priority)
3. **Clean up incomplete features**
   - Drop unused notification preference columns from user_show_preferences
   - Drop unused profile columns from users table
   - Document decision in this file

4. **Verify table usage**
   - Confirm prompts/prompt_history tables are still needed
   - Consider deprecating if LLM features are fully removed

### Phase 3: Long Term (Low Priority)
5. **Optimize remaining columns**
   - Remove other unused columns (player_uuid, item_db_id, etc.)
   - Consolidate similar functionality (notifications.seen vs status)

6. **Database performance**
   - Ensure all foreign keys are indexed
   - Add composite indexes where needed
   - Review query patterns

## Implementation Notes

### SQLite Limitations
- SQLite versions before 3.35.0 don't support `DROP COLUMN`
- May need to recreate tables to drop columns in older SQLite
- Check SQLite version before applying cleanup migration

### Testing Requirements
1. Test fresh database initialization with updated init_db()
2. Test migration from existing database
3. Verify all application features still work
4. Check that no code references dropped columns

### Migration Strategy
- Create numbered migration (e.g., 056_cleanup_unused_columns.py)
- Use IF EXISTS for all DROP operations
- Include rollback capability where possible
- Log all changes clearly

## Column Usage Reference

### Confirmed Active Columns
Based on code analysis, these column patterns are actively used:
- All `*_id` columns (primary/foreign keys)
- All timestamp columns (created_at, updated_at, etc.)
- User identity: username, plex_username, plex_user_id, plex_token
- Media metadata: title, overview, poster_url, fanart_url
- Episode tracking: season_number, episode_number, has_file
- Ratings: rating_value (used), ratings_*_value, ratings_*_votes (Sonarr)

### Columns to Investigate Further
These columns may have valid use cases not found in current code scan:
- Settings columns for services (may be used via get_setting/set_setting)
- Statistics columns (may be updated via triggers)
- Webhook tracking columns (may be logged but not queried)

## Related Documentation
- See `CLAUDE.md` for recent changes (LLM feature removal)
- See individual migration files in `app/migrations/` for table creation history
- See `app/database.py` for current init_db() schema
