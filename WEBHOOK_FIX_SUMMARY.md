# Webhook Automatic Sync Fix - Summary

## Problem Identified

The automatic database updates from Sonarr and Radarr webhooks were not working, requiring manual syncs from the admin tasks page.

## Root Cause

The webhook handler code was checking for incomplete event type names:

### Sonarr Issues:
- Code was checking for `'Series'` events
- Sonarr v3+ actually sends `'SeriesAdd'` when new shows are added
- **100 SeriesAdd events** were received but not processed

### Radarr Issues:
- Code was checking for `'Movie'` events  
- Radarr v3+ actually sends `'MovieAdded'` when new movies are added
- **194 MovieAdded events** were received but not processed

## Changes Made

### 1. Updated `app/routes/main.py` - Sonarr Webhook Handler (Lines 443-452)

**Before:**
```python
sync_events = [
    'Download',           # Episode downloaded
    'Series',             # Series added/updated
    'Episode',            # Episode added/updated
    'Rename',             # Files renamed
    'Delete',             # Files deleted
    'Health',             # Health check
    'Test'                # Test event
]
```

**After:**
```python
sync_events = [
    'Download',           # Episode downloaded
    'Series',             # Series added/updated (generic)
    'SeriesAdd',          # Series added (Sonarr v3+) ✨ NEW
    'SeriesDelete',       # Series deleted ✨ NEW
    'Episode',            # Episode added/updated
    'EpisodeFileDelete',  # Episode file deleted ✨ NEW
    'Rename',             # Files renamed
    'Delete',             # Files deleted
    'Health',             # Health check
    'Test'                # Test event
]
```

### 2. Updated `app/routes/main.py` - Radarr Webhook Handler (Lines 570-578)

**Before:**
```python
sync_events = [
    'Download',           # Movie downloaded
    'Movie',              # Movie added/updated
    'Rename',             # Files renamed
    'Delete',             # Files deleted
    'Health',             # Health check
    'Test'                # Test event
]
```

**After:**
```python
sync_events = [
    'Download',           # Movie downloaded
    'Movie',              # Movie added/updated (generic)
    'MovieAdded',         # Movie added (Radarr v3+) ✨ NEW
    'MovieDelete',        # Movie deleted ✨ NEW
    'MovieFileDelete',    # Movie file deleted ✨ NEW
    'Rename',             # Files renamed
    'Delete',             # Files deleted
    'Health',             # Health check
    'Test'                # Test event
]
```

### 3. Enabled Application Logging (`app/__init__.py`, Lines 48-66)

**Changed:** Uncommented the file logging configuration to help monitor webhook activity.

**Result:** Logs will now be written to `/home/scott/show_notes/logs/shownotes.log`

### 4. Updated Documentation (`docs/webhook_setup_guide.md`)

- Added all supported event types including v3+ specific events
- Updated webhook configuration instructions to include "On Series Add" and "On Movie Added"
- Clarified which events trigger syncs

## Verification from Database

**Webhook Activity Analysis:**
```sql
-- Sonarr events received:
Download: 6,614 events ✓ (already handled)
Grab: 4,902 events (tracked but doesn't trigger sync)
SeriesAdd: 100 events ✗ (NOW FIXED - will trigger full sync)
Test: 4 events ✓ (already handled)
Rename: 1 event ✓ (already handled)

-- Radarr events received:
Download: 218 events ✓ (already handled)
MovieAdded: 194 events ✗ (NOW FIXED - will trigger full sync)
Test: 3 events ✓ (already handled)
Movie: 1 event ✓ (already handled)
```

## Expected Behavior After Fix

### When a New Show is Added to Sonarr:
1. Sonarr sends a `SeriesAdd` webhook to ShowNotes
2. ShowNotes receives the webhook (logged in `webhook_activity` table)
3. Background sync thread starts automatically
4. Full Sonarr library sync runs (fetches all show metadata)
5. Database is updated with the new show
6. Log message: "Sonarr webhook-triggered sync completed: X shows processed"

### When a New Movie is Added to Radarr:
1. Radarr sends a `MovieAdded` webhook to ShowNotes
2. ShowNotes receives the webhook (logged in `webhook_activity` table)
3. Background sync thread starts automatically
4. Full Radarr library sync runs (fetches all movie metadata)
5. Database is updated with the new movie
6. Log message: "Radarr webhook-triggered sync completed: X movies processed"

### When an Episode is Downloaded:
1. Sonarr sends a `Download` webhook
2. ShowNotes triggers a **targeted** episode sync (more efficient)
3. Only the specific episodes are updated
4. Log message: "Targeted episode sync for series X completed"

## Testing the Fix

### Option 1: Add a New Show/Movie
1. Add a new show to Sonarr or movie to Radarr
2. Check the webhook activity: 
   ```bash
   sqlite3 instance/shownotes.sqlite3 "SELECT * FROM webhook_activity ORDER BY id DESC LIMIT 5;"
   ```
3. Check the logs:
   ```bash
   tail -f logs/shownotes.log
   ```
4. Verify the show/movie appears in ShowNotes without manual sync

### Option 2: Send a Test Webhook
1. Go to Sonarr → Settings → Connect → ShowNotes webhook
2. Click the "Test" button
3. Check logs for: "Sonarr webhook event 'Test' detected, triggering library sync"

### Option 3: Monitor Next Automatic Event
1. Wait for the next download or series add
2. Watch the logs for automatic sync trigger
3. Verify database updates without manual intervention

## Files Modified

1. `app/routes/main.py` - Updated webhook event handlers
2. `app/__init__.py` - Enabled file logging
3. `docs/webhook_setup_guide.md` - Updated documentation

## Next Steps

1. **The app needs to be restarted** for changes to take effect
2. Monitor `logs/shownotes.log` to see webhook activity
3. Verify automatic syncs are triggered when new content is added
4. Manual sync buttons remain available as a backup

## Webhook URLs (for reference)

Based on the app running on port 5001:
- **Sonarr**: `http://your-server:5001/sonarr/webhook`
- **Radarr**: `http://your-server:5001/radarr/webhook`

Make sure these are configured in Sonarr/Radarr with:
- Method: **POST** (not PUT)
- Username/Password: **Empty**
- Events: **All relevant events checked** (especially "On Series Add" / "On Movie Added")
