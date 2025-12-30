# Issues to Fix Later

## Event Log Timezone
- Event logs are not respecting the timezone setting from Admin > Settings
- Timestamps should be converted to the user's configured timezone

## Sonarr Sync - Only 2 Shows Imported
- Sonarr sync only imported "60 Minutes" and "Adam Ruins Everything"
- Need to investigate why `get_all_sonarr_shows()` is only returning 2 shows instead of all shows from Sonarr
- Check if there's a pagination or filtering issue with the Sonarr API call

## TVMaze Enrichment Failed
- "60 Minutes TVMaze enrichment failed" due to missing columns
- ✅ FIXED: Ran migrations 029 and 030 to add TVMaze columns and show_cast table
- Need to re-run Sonarr sync to test if enrichment works now

## Radarr Sync - Missing Column
- ✅ FIXED: Added `release_date` column to radarr_movies table
- Created migration 037 for future fresh installs

## Pushover Fields
- ✅ FIXED: Corrected field names in onboarding template and JavaScript

## Service Test Buttons
- ✅ FIXED: Added `/onboarding/test-service` route
- ✅ FIXED: Tautulli API key now sent as query parameter instead of header

## User Authentication Columns
- ✅ FIXED: Added `username` and `password_hash` columns via migration 036

## Plex OAuth (Not Implemented)
- "Link Plex Account" button exists but routes don't exist
- `/admin/link-plex/start` - not implemented
- `/login/plex/start` - not implemented
- `/login/plex/poll` - not implemented
- Consider removing these buttons or implementing the OAuth flow
