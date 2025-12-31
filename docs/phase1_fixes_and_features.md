# Phase 1 Fixes & Features Summary

## Issues Fixed Today (Dec 31, 2025)

### 1. Progress Page Error - FIXED ✅
**Issue**: `/profile/progress` showed "Error loading shows"
**Cause**: SQL query referenced `poster_path` column but database uses `poster_url`
**Fix**: Updated query in `/api/profile/progress/shows` endpoint (line 3822)
**Status**: Resolved

### 2. Trailers Showing in Watch History - FIXED ✅
**Issue**: Movie trailers (2-10 minute videos) appearing as full movies in watch history
**Solution**:
- Added duration filter in Plex webhook (lines 234-238) - skips content < 10 minutes
- Added duration filter in watch history query (line 2105) - filters existing trailers
**Threshold**: Content shorter than 10 minutes (600,000ms) is considered a trailer
**Status**: Resolved - new trailers won't be logged, existing ones filtered from display

### 3. Profile Photo in Header - FIXED ✅
**Issue**: Profile photo uploaded but not showing in header
**Solution**:
- Updated `base.html` to display profile photo in user menu button (lines 58-67)
- Falls back to first letter of username if no photo
- Added `profile_photo_url` to session on all login paths (lines 777, 885, 971)
**Status**: Resolved - photo will show after next login

### 4. Shows Not in Sonarr - PARTIAL ⚠️
**Issue**: "Little Disasters" watched in Plex but no link/poster in history
**Cause**: Show not in Sonarr database - either:
  - Not managed by Sonarr at all (user watching content outside Sonarr)
  - Sonarr webhook "On Series Add" not enabled
  - Show added before webhook was configured
**Current Behavior**: Shows/movies not in Sonarr/Radarr appear in history but without:
  - Clickable links
  - Poster images
  - Detail pages
**Temporary Solution**: Run manual sync from admin page
**Long-term Solution**: Ensure Sonarr webhook has "On Series Add" enabled
**Status**: Documented - requires Sonarr configuration check

---

## New Feature Request: Multi-User Profiles

### User Story
> "My wife and I use the same Plex account so we share a watch history, but should be able to make lists and add favorites etc separately."

### Current Limitation
- One Plex account = One ShowNotes profile
- All data (favorites, lists, progress) is tied to the Plex username
- No way to differentiate between family members using the same Plex account

### Proposed Solution: Sub-Profiles

#### Database Changes Needed
1. Add `user_profiles` table:
```sql
CREATE TABLE user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,  -- Links to main user account
    profile_name TEXT NOT NULL,
    profile_icon TEXT,  -- emoji or icon identifier
    is_primary BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
```

2. Add `active_profile_id` column to `users` table to track current profile

3. Update existing tables to use `profile_id` instead of `user_id`:
   - `user_favorites` → `profile_favorites`
   - `user_lists` → `profile_lists`
   - `user_show_progress` → `profile_show_progress`
   - `user_episode_progress` → `profile_episode_progress`
   - `user_recommendations` → `profile_recommendations`

#### UI Changes Needed
1. **Profile Switcher**
   - Dropdown in header next to user menu
   - Shows current profile with icon
   - Lists all profiles for account
   - "+ Add Profile" option

2. **Profile Management Page**
   - Create new profiles
   - Edit profile names/icons
   - Set primary profile (auto-selected on login)
   - Delete profiles

3. **Profile-Specific Data**
   - Watch history remains SHARED (Plex account level)
   - Favorites, Lists, Progress, Recommendations are PROFILE-SPECIFIC

#### Migration Strategy
1. Create migration to add new tables
2. For existing users, create a "primary" profile
3. Move all existing user data to their primary profile
4. Add profile switcher UI
5. Allow users to create additional profiles

#### Benefits
- Personalized lists and favorites per family member
- Individual watch progress tracking
- Shared watch history (family can see what's being watched)
- Better recommendations per person
- No need for separate Plex accounts

#### Technical Considerations
- Session needs to store `active_profile_id`
- All queries need to filter by `profile_id` instead of `user_id`
- Plex webhook still logs to shared watch history
- Profile switch = session update only (no re-authentication)

#### Priority
**Medium** - Requested feature but not blocking. Can be implemented after Phase 1 core features are complete.

---

## Testing Checklist

- [x] Progress page loads without errors
- [x] Trailers no longer appear in watch history
- [ ] Profile photo appears in header (requires re-login to test)
- [ ] Sonarr webhook configured with "On Series Add" enabled
- [ ] New shows sync automatically via webhook

---

## Notes for Next Session
1. Add "Report Problem" and "Recommend" buttons to show/episode pages
2. Restore flag/issue button on episodes
3. Add Jellyseer integration/links
4. Create user manual page
5. Consider multi-user profile feature for future release
