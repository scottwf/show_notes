# GitHub Issues - ShowNotes

## Critical Bugs

### Issue #1: Announcement Creation Failing
**Priority**: High
**Status**: ✅ Fixed (pending test)

**Description**:
When creating an announcement in admin panel, clicking save fails with error message.

**Root Cause**:
Potential database rollback issue where `db` variable wasn't defined before exception handler.

**Fix Applied**:
- Initialize `db = None` before try block
- Check `if db:` before calling `db.rollback()` in exception handler
- Located in `/app/routes/admin.py` lines 1624-1668

**Testing Required**:
- [ ] Create new announcement with all fields
- [ ] Create announcement with minimal fields
- [ ] Verify error messages if validation fails

---

### Issue #6: Watch Progress Tracking Not Working
**Priority**: Critical
**Status**: ✅ Fixed (pending test)

**Description**:
Episode watch tracking completely broken due to database schema mismatch:
1. "Mark Watched"/"Mark Unwatched" season buttons fail with "no such column: season_number"
2. Episode checkboxes fail to toggle with generic error
3. Plex webhook not auto-marking episodes as watched

**Root Cause**:
Multiple SQL queries were trying to SELECT `season_number` directly from `sonarr_episodes` table, but that table doesn't have this column. The `season_number` is stored in `sonarr_seasons` table, and episodes link via `season_id` foreign key.

**Affected Code Locations**:
- `/app/routes/main.py` line 4019: Season mark-all endpoint
- `/app/routes/main.py` line 3937: Episode toggle endpoint
- `/app/routes/main.py` line 325: Plex webhook auto-tracking
- `/app/routes/main.py` line 3890: Show progress API endpoint

**Fixes Applied**:
All queries updated to JOIN with `sonarr_seasons` table:
```sql
-- BEFORE (broken)
SELECT id, season_number, episode_number
FROM sonarr_episodes
WHERE show_id = ? AND season_number = ?

-- AFTER (fixed)
SELECT e.id, s.season_number, e.episode_number
FROM sonarr_episodes e
JOIN sonarr_seasons s ON e.season_id = s.id
WHERE s.show_id = ? AND s.season_number = ?
```

**Additional Fixes**:
- Changed `air_date` to `air_date_utc` (correct column name)
- Changed response field from `id` to `episode_id` to match frontend expectations

**Testing Required**:
- [ ] Click checkbox next to episode - should toggle watched status
- [ ] Click "Mark Watched" button on a season - all episodes should be marked
- [ ] Click "Mark Unwatched" button on a season - all episodes should be unmarked
- [ ] Watch an episode in Plex to 95%+ - should auto-mark as watched
- [ ] Checkboxes should load with correct initial state on page load

**User Education Needed**:
The checkboxes allow users to manually track which episodes they've watched, independent of Plex. This is useful for:
- Tracking episodes watched outside of Plex
- Planning which episodes to watch next
- Seeing completion progress for a show
- Marking episodes you don't plan to watch

---

### Issue #7: Profile Statistics Page Not Loading Data
**Priority**: High
**Status**: Needs investigation & data population

**Description**:
The `/profile/statistics` page is not loading any statistics data and is not using the configured timezone for date/time displays.

**Symptoms**:
1. No data displayed on statistics page (charts/metrics empty)
2. Timestamps not converted to user's timezone
3. Possible JavaScript errors in console

**Investigation Results**:
- ✅ API endpoints exist and are implemented (`/api/profile/statistics/*`)
- ✅ Statistics tables exist (`user_watch_statistics`, `user_genre_statistics`, `user_watch_streaks`)
- ⚠️ **Tables have minimal data (only 2 records in user_watch_statistics)**
- ❓ Need to check if Plex webhook is calling statistics update functions
- ❓ Need to check browser console for JavaScript errors
- ❓ Timezone not being passed from settings to frontend

**Root Cause - Low Priority**:
Statistics tables are not being populated with historical data. With only 2 records, there's insufficient data to display meaningful charts and metrics.

**Required Actions**:
1. **Create backfill script** to populate statistics from existing plex_activity_log
2. **Add webhook triggers** to update statistics on each watch event
3. **Fix timezone display** for any date/time shown
4. **Test with populated data** to verify charts render correctly

**Backfill Script Needed**:
Create `/app/scripts/backfill_statistics.py` to:
- Calculate daily watch statistics from plex_activity_log
- Populate user_watch_statistics with historical data
- Calculate genre statistics from watched shows
- Calculate watch streaks
- Should be runnable from admin Tasks page

**Files to Check**:
- `/app/templates/profile_statistics.html` - Frontend template
- `/app/routes/main.py` - API endpoints for statistics
- `/app/routes/main.py` - Plex webhook statistics triggers
- Statistics tables in database

**Expected API Endpoints** (per plan):
- `GET /api/profile/statistics/overview` - Total watch time, counts, streak
- `GET /api/profile/statistics/watch-time?period=30|90|365` - Daily chart data
- `GET /api/profile/statistics/genres` - Genre breakdown
- `GET /api/profile/statistics/viewing-patterns` - Hour/day distribution
- `GET /api/profile/statistics/top-shows?type=show|movie` - Top content

**Timezone Requirements**:
- All timestamps must be converted from UTC to user's timezone
- Use timezone from settings table
- Display with timezone abbreviation (e.g., "PST", "EST")
- Apply to: watch time charts, last watched dates, streak calculations

**Related Issues**:
- See Issue #2, #3, #4 for general timezone implementation guidance

---

### Issue #8: Now Playing Count Always Shows 0
**Priority**: Medium
**Status**: Needs investigation

**Description**:
The "now playing" count on profile page/homepage always displays 0 even when users are actively watching content in Plex.

**Affected Locations**:
- Profile homepage/dashboard
- Anywhere "now playing" or "active sessions" is displayed

**Expected Behavior**:
Should show the count of active Plex sessions where users are currently watching (playing or paused, not stopped).

**Investigation Needed**:
- [ ] Check SQL query for counting active sessions
- [ ] Verify what constitutes an "active" session
- [ ] Check if event types are correct (media.play, media.pause, media.resume)
- [ ] Verify session_key is being stored in plex_activity_log
- [ ] Check time window for "active" sessions (may need to filter by recent timestamp)

**Likely Root Cause**:
The query logic for determining "now playing" sessions may be incorrect:
1. May be checking wrong event types
2. May need to filter by recent timestamp (e.g., last 10 minutes)
3. Session tracking logic may not work as expected
4. May need to exclude stopped/scrobbled sessions

**Current Implementation** (needs review):
Found at `/app/routes/main.py` around line 4066:
```sql
WITH latest_events AS (
    SELECT
        session_key,
        plex_username,
        event_type,
        MAX(event_timestamp) as last_event_time,
        MAX(id) as last_event_id
    FROM plex_activity_log
    WHERE session_key IS NOT NULL AND session_key != ''
    GROUP BY session_key
)
SELECT COUNT(*)
FROM latest_events
WHERE event_type IN ('media.play', 'media.resume', 'media.pause')
```

**Potential Issues**:
- Query gets MAX(event_timestamp) but filters on event_type - these may not match
- No time window filter (sessions from days ago might be counted)
- Need to verify session_key is properly populated

**Recommended Fix**:
Should track sessions with last activity in past 10-15 minutes and not stopped:
```sql
SELECT COUNT(DISTINCT session_key)
FROM plex_activity_log
WHERE session_key IS NOT NULL
  AND session_key != ''
  AND event_timestamp > datetime('now', '-15 minutes')
  AND event_type IN ('media.play', 'media.resume', 'media.pause')
  AND session_key NOT IN (
      SELECT session_key
      FROM plex_activity_log
      WHERE event_type IN ('media.stop', 'media.scrobble')
        AND event_timestamp > datetime('now', '-15 minutes')
  )
```

**Testing Steps**:
- [ ] Start playing content in Plex
- [ ] Check if now playing count increases
- [ ] Pause the content - count should remain
- [ ] Stop the content - count should decrease
- [ ] Wait 15+ minutes - stale sessions should be excluded

---

## Timezone Issues

### Issue #2: Event Log Not Using Timezone
**Priority**: Medium
**Labels**: timezone, event-log

**Description**:
Event log displays timestamps in UTC instead of user's configured timezone setting.

**Affected Areas**:
- `/admin/logbook` page
- Any plex activity log displays

**Investigation Needed**:
- [ ] Check if timezone setting is being read from database
- [ ] Verify timezone is being passed to templates
- [ ] Add timezone conversion in Jinja filters or backend

**Proposed Solution**:
1. Create a custom Jinja filter for timezone conversion
2. Apply to all datetime displays in logbook
3. Use timezone from settings table

**Files to Update**:
- `/app/routes/admin.py` - logbook route
- `/app/templates/admin_logbook.html` - template filters
- Potentially create `/app/filters.py` for timezone utilities

---

### Issue #3: Admin Logbook Improvements
**Priority**: Medium
**Labels**: admin, logbook, timezone, enhancement

**Description**:
Admin logbook page needs several improvements:
1. Not displaying show title, only episode name
2. Timezone not being used (see Issue #2)
3. Could use better formatting and filtering

**Current Problems**:
- Limited context: "Episode: The Sacrifice" without show name
- UTC timestamps instead of local time
- No filtering by date range, show, or user

**Proposed Enhancements**:
- [ ] Display format: "Show Title - S01E05: Episode Title"
- [ ] Apply timezone conversion to all timestamps
- [ ] Add filters: date range, show name, username, event type
- [ ] Add pagination (currently shows all records)
- [ ] Add export to CSV functionality
- [ ] Color-code event types (play, pause, stop, scrobble)

**SQL Query Update Needed**:
```sql
SELECT
    pal.*,
    s.title as show_title,
    u.username
FROM plex_activity_log pal
LEFT JOIN sonarr_shows s ON pal.show_id = s.id
LEFT JOIN users u ON pal.plex_username = u.plex_username
ORDER BY pal.timestamp DESC
```

**Files to Update**:
- `/app/routes/admin.py` - logbook route with improved query
- `/app/templates/admin_logbook.html` - better display format
- Add JavaScript for client-side filtering

---

### Issue #4: Timezone Implementation Audit
**Priority**: Medium
**Labels**: timezone, audit

**Description**:
Comprehensive audit needed to find all places where timezone should be applied but isn't.

**Areas to Check**:
- [ ] Admin logbook (Issue #3)
- [ ] Admin event log
- [ ] User watch history (`/profile/history`)
- [ ] Episode air dates on show detail pages
- [ ] Announcement start/end dates
- [ ] Problem report timestamps
- [ ] User notification timestamps
- [ ] Last watched timestamps in progress tracking
- [ ] Season/episode air date displays

**Implementation Strategy**:
1. Create centralized timezone utility functions
2. Add Jinja template filter: `{{ datetime | local_time }}`
3. Create Python helper: `format_local_time(dt, timezone_str)`
4. Update all templates systematically
5. Document timezone handling in developer guide

**Files to Create/Update**:
- `/app/utils/timezone.py` - New utility module
- `/app/__init__.py` - Register Jinja filters
- Update all template files listed above

---

## Feature Updates

### Issue #5: Admin Dashboard Overhaul
**Priority**: High
**Labels**: admin, dashboard, roadmap, design

**Description**:
Admin dashboard needs complete redesign to reflect new direction as social media hub for TV/movies rather than just metadata tool.

**Current State**:
- Shows library statistics (shows count, episodes count)
- Focused on Sonarr/Radarr sync status
- Oriented toward content management

**New Vision - Social Hub Dashboard**:

**Top Metrics**:
- Total active users (last 30 days)
- User engagement: watch events (today/week/month)
- Community activity: recommendations, reports, list shares
- Popular content: most watched shows this week

**Dashboard Sections**:

1. **Community Activity** (Top Priority)
   - Recent user recommendations
   - Active problem reports awaiting review
   - Most created/shared lists this week
   - User signup trend chart

2. **Content Health**
   - Library size (shows, movies, episodes)
   - Sync status with Sonarr/Radarr
   - Missing metadata count
   - Failed webhook deliveries

3. **System Status**
   - Service connections (Sonarr, Radarr, Jellyseerr, Plex)
   - Recent errors/warnings from logs
   - Database size and performance metrics
   - API usage if applicable

4. **Quick Actions**
   - Create announcement button
   - Review pending reports (with count badge)
   - Manual library sync
   - View full logbook

5. **Recent Activity Feed**
   - Last 10 watch events across all users
   - Recent user signups
   - New recommendations submitted
   - System events (syncs, errors)

**Visual Design Updates**:
- Modern card-based layout (similar to profile pages)
- Charts for user engagement trends (Chart.js)
- Color-coded status indicators
- Dark mode optimized

**Metrics to Track**:
```sql
-- Add these queries to dashboard
SELECT COUNT(DISTINCT user_id) FROM plex_activity_log WHERE timestamp > datetime('now', '-30 days');
SELECT COUNT(*) FROM user_recommendations WHERE created_at > datetime('now', '-7 days');
SELECT COUNT(*) FROM issue_reports WHERE status = 'open';
SELECT COUNT(*) FROM announcements WHERE is_active = 1;
```

**Files to Update**:
- `/app/routes/admin.py` - dashboard route with new metrics
- `/app/templates/admin_dashboard.html` - complete redesign
- `/app/static/admin_dashboard.js` - new interactive elements
- Add Chart.js for visualizations

---

## Implementation Priority

### Phase 1 (Immediate - Critical Fixes)
1. **Issue #1**: Test announcement creation fix ✅ (Fixed)
2. **Issue #6**: Test watch progress tracking fixes ✅ (Fixed)
3. **Issue #8**: Fix now playing count always showing 0
4. **Issue #5**: Begin admin dashboard redesign (high impact)

### Phase 2 (Near Term - User Experience)
5. **Issue #7**: Create statistics backfill script & add webhook triggers (lower priority - tables exist but empty)
6. **Issue #2 & #3**: Fix logbook timezone and show title display
7. **Issue #4**: Timezone audit and standardization

### Phase 3 (Future Enhancements)
7. Additional logbook features (filtering, export)
8. Advanced dashboard analytics
9. User engagement metrics

---

## Notes

- All timezone work should use the `timezone` field from `settings` table
- Dashboard redesign should align with social hub vision discussed in docs/PRD.md
- Consider creating a `/docs/architecture/timezone.md` guide for developers
- Admin UI should maintain consistency with user-facing profile pages (Tailwind design system)

---

## Development Guidelines

When fixing timezone issues:
1. Always retrieve timezone from settings: `SELECT timezone FROM settings LIMIT 1`
2. Use Python's `pytz` library for conversions
3. Store all dates in UTC in database
4. Convert to local time only for display
5. Add timezone abbreviation to all datetime displays (e.g., "Jan 1, 2025 3:45 PM PST")

Example implementation:
```python
import pytz
from datetime import datetime

def format_local_time(utc_dt, timezone_str='UTC'):
    """Convert UTC datetime to local timezone"""
    if not utc_dt:
        return None

    tz = pytz.timezone(timezone_str)
    if isinstance(utc_dt, str):
        utc_dt = datetime.fromisoformat(utc_dt.replace('Z', '+00:00'))

    # Assume UTC if naive
    if utc_dt.tzinfo is None:
        utc_dt = pytz.UTC.localize(utc_dt)

    local_dt = utc_dt.astimezone(tz)
    return local_dt.strftime('%b %d, %Y %I:%M %p %Z')
```

Jinja filter registration:
```python
# In app/__init__.py
from app.utils.timezone import format_local_time

def create_app():
    # ... existing code ...

    @app.template_filter('local_time')
    def local_time_filter(dt, tz=None):
        if tz is None:
            tz = get_setting('timezone', 'UTC')
        return format_local_time(dt, tz)

    return app
```

Usage in templates:
```html
{{ episode.air_date | local_time }}
{{ log_entry.timestamp | local_time }}
```
