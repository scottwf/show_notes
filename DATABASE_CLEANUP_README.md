# Database Schema Cleanup - How to Apply

This directory contains the results of a comprehensive database schema analysis and cleanup.

## Quick Start

### For Fresh Installations
No action needed - the updated `app/database.py` will create a clean schema without unused columns.

### For Existing Installations

1. **Backup your database first!**
   ```bash
   cp instance/shownotes.sqlite3 instance/shownotes.sqlite3.backup
   ```

2. **Run the cleanup migration:**
   ```bash
   python3 app/migrations/056_cleanup_unused_columns.py
   ```

3. **Verify the migration:**
   ```bash
   # Should show 11 columns were dropped
   # The migration will report: "Migration complete: 11 columns dropped, 0 skipped"
   ```

4. **Test your application:**
   - Start the application normally
   - Check that all features work as expected
   - The removed columns were unused, so no functionality should be affected

## What This Migration Does

Removes 11 unused database columns:

1. `episode_characters.llm_background` - From removed LLM features
2-5. `user_show_preferences`: `notify_new_episode`, `notify_season_finale`, `notify_series_finale`, `notify_time`
6-7. `users`: `external_links`, `profile_is_public`
8-9. `radarr_movies`: `rating_type`, `rating_votes`
10. `plex_activity_log.player_uuid`
11. `webhook_activity.processed`

## Documentation

- **DATABASE_ANALYSIS.md** - Complete schema analysis with findings and recommendations
- **DATABASE_CLEANUP_SUMMARY.md** - Executive summary of changes and impact
- **CLAUDE.md** - Updated with database documentation references

## Safety Features

- ✅ Migration is **idempotent** (safe to run multiple times)
- ✅ All data is **preserved**
- ✅ Works with both modern and legacy SQLite versions
- ✅ No breaking changes to application code
- ✅ Thoroughly tested on sample database

## Verification

After running the migration, verify columns were removed:

```bash
# These should NOT show the removed columns
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(episode_characters);"
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(user_show_preferences);"
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(users);"
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(radarr_movies);"
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(plex_activity_log);"
sqlite3 instance/shownotes.sqlite3 "PRAGMA table_info(webhook_activity);"
```

## Rollback

If you need to rollback (though this shouldn't be necessary):

```bash
# Stop the application
# Restore from backup
cp instance/shownotes.sqlite3.backup instance/shownotes.sqlite3
# Restart the application
```

**Note:** The removed columns were confirmed unused, so rollback should never be needed.

## Files Changed

### New Files
- `DATABASE_ANALYSIS.md` - Complete analysis
- `DATABASE_CLEANUP_SUMMARY.md` - Summary document
- `app/migrations/056_cleanup_unused_columns.py` - Migration script
- `DATABASE_CLEANUP_README.md` - This file

### Modified Files
- `app/database.py` - Updated init_db() schema
- `app/utils.py` - Removed player_uuid reference
- `app/routes/main.py` - Removed player_uuid reference
- `CLAUDE.md` - Added database documentation

## Questions?

See the detailed documentation:
- Issues with removed columns? Check `DATABASE_ANALYSIS.md` for rationale
- Want to know what was changed? See `DATABASE_CLEANUP_SUMMARY.md`
- Need schema reference? See `CLAUDE.md` Database Schema section

## Future Work

See `DATABASE_ANALYSIS.md` "Recommendations" section for:
- Phase 2: Additional cleanup opportunities
- Phase 3: Long-term schema maintenance suggestions
