# User Testing Feedback - December 31, 2025

## Issues Found During Testing

### 1. Homepage/Profile Route Structure
**Current Behavior:**
- Homepage is at `/` (shows generic page)
- Watch history is at `/profile/history`
- Tab is labeled "Watch History"

**Expected Behavior:**
- Profile/watch history should BE the homepage (`/`)
- Tab should be labeled "Profile" not "Watch History"
- Makes profile the landing page after login

**Impact:** High - Affects navigation and UX flow

**Files to Change:**
- `app/routes/main.py` - Move profile_history route to `/`
- `app/templates/profile_base.html` - Change tab label
- Update all navigation links

---

### 2. Watch History Needs Horizontal Scrolling Section
**Current Behavior:**
- Watch history shows list/grid of recent items
- All vertical layout

**Expected Behavior:**
- Below "Currently Playing" section
- Add horizontal scrolling section with recent episodes/movies
- Similar to Plex profile page design
- Show poster cards that scroll left/right
- Recent watches displayed chronologically

**Impact:** Medium - UX improvement

**Implementation:**
- Add horizontal scroll container
- Card-based layout for recent items
- Touch/swipe friendly
- "See All" link to full list

**Files to Change:**
- `app/templates/profile_history.html` - Add horizontal scroll section
- CSS for horizontal scroll behavior

---

### 3. Toast Notification White Bar Issue
**Current Behavior:**
- Toast notifications have white part on left side
- Styling issue with border or padding

**Expected Behavior:**
- Solid color throughout (blue/yellow/orange/green)
- No white sections

**Impact:** Low - Visual polish

**Files to Fix:**
- `app/templates/base.html` - Toast notification styles
- Check border-left styling

---

### 4. Announcement Notification Flow
**Current Behavior:**
- User dismisses announcement
- It disappears completely OR stays in notifications

**Expected Behavior:**
1. User sees toast notification
2. User dismisses it → toast disappears
3. Announcement shows at TOP of notifications tab (pinned)
4. User can see it there until admin marks announcement as inactive
5. Once admin deactivates, it moves to historical list (not pinned)

**Current Implementation Status:**
- ✅ Toast dismiss saves to user_announcement_views
- ✅ Creates notification on dismiss
- ❓ Need to verify pinning behavior
- ❓ Need to verify unpinning when admin deactivates

**Impact:** Medium - Notification UX

**Files to Check/Update:**
- `app/routes/main.py` - Dismiss announcement endpoint
- `app/templates/profile_notifications.html` - Pinning logic
- May need is_pinned column or ordering logic

---

### 5. Statistics Page Missing Data
**Current Behavior:**
- Statistics page loads but shows minimal/no data
- Tables exist but mostly empty

**Expected Behavior:**
- Rich statistics from watch history
- Charts showing trends
- Viewing patterns
- Top shows/movies

**Root Cause:**
- Statistics tables not populated from historical data
- Webhook triggers not updating statistics on watch events

**Impact:** High - Feature incomplete

**Solution Needed:**
1. Create backfill script to populate from plex_activity_log
2. Add webhook triggers to update statistics
3. See Issue #7 in github_issues.md

**Files to Create/Update:**
- `app/scripts/backfill_statistics.py` - New script
- `app/routes/main.py` - Add webhook triggers
- Admin tasks page - Add "Backfill Statistics" button

---

### 6. Notifications Tab Structure Needed
**Current Behavior:**
- Notifications tab shows mixed notification types
- No clear organization

**Expected Behavior:**
Three distinct sections in order:

#### Section 1: Site Announcements (Top)
- Active announcements (even if dismissed)
- Pinned at top until admin deactivates
- Once deactivated, moves to bottom historical section
- User can see full announcement text
- Shows when it was posted

#### Section 2: Show Issue Reports & Responses
- Issues the user submitted
- Admin responses to those issues
- Status updates (open, investigating, resolved)
- Link to the show/episode
- Chronological order

#### Section 3: User Activity Updates
- Favorite show returning (new season)
- Season finale notifications
- Show finale notifications
- New episodes available for favorites
- Recommendation activity (someone liked your rec)

**Impact:** High - Core feature organization

**Implementation Needed:**
- Update notification types in database
- Create notification templates for each type
- Implement webhook triggers for show updates
- Update UI to show three sections clearly

**Files to Update:**
- `app/templates/profile_notifications.html` - Restructure layout
- `app/routes/main.py` - Update notification queries
- Add notification generation logic for show events

---

## Priority Ranking

### P0 - Critical (Blocking UX)
1. Statistics page data population (backfill script)
2. Notifications tab structure (3 sections)

### P1 - High Priority (Navigation/UX)
3. Homepage should be profile/watch history (`/`)
4. Add horizontal scrolling recent items section
5. Announcement notification flow (pinning/unpinning)

### P2 - Medium Priority (Polish)
6. Toast notification white bar fix
7. Tab label change (Watch History → Profile)

---

## Implementation Plan

### Phase 1: Navigation & Structure
1. Move profile route to `/`
2. Update all navigation links
3. Change tab labels

### Phase 2: Notifications System
4. Fix toast notification styling
5. Implement 3-section notification structure
6. Add announcement pinning logic
7. Create notification types for show events

### Phase 3: Statistics
8. Create backfill script
9. Add webhook triggers for statistics
10. Test with populated data

### Phase 4: UX Enhancements
11. Add horizontal scrolling recent items section
12. Polish and test

---

## Database Changes Needed

### Notifications Table
May need to add:
- `is_pinned` BOOLEAN - For keeping announcements at top
- `notification_category` TEXT - 'announcement', 'issue_report', 'show_update'
- `parent_id` INTEGER - For linking responses to original reports

### New Notification Types
- `favorite_returning` - Favorite show has new season
- `season_finale` - Season finale aired
- `show_finale` - Series finale aired
- `episode_available` - New episode for favorite
- `issue_response` - Admin responded to issue report
- `issue_status_change` - Issue status updated

---

## Questions to Resolve

1. **Homepage Redirect**: Should `/` redirect to `/profile` or should profile_history handle both routes?
2. **Announcement Lifecycle**: When admin deactivates announcement, should it immediately unpin for all users?
3. **Show Updates**: Should we track Sonarr webhook for new episodes and create notifications automatically?
4. **Issue Responses**: Do we need a separate `issue_responses` table or use notification message field?

---

## Files Inventory for Changes

### Backend Routes
- `app/routes/main.py` - Homepage route, notification structure, statistics backfill trigger

### Templates
- `app/templates/profile_history.html` - Horizontal scroll section
- `app/templates/profile_notifications.html` - 3-section restructure
- `app/templates/base.html` - Toast notification styling
- `app/templates/profile_base.html` - Tab label changes

### New Files
- `app/scripts/backfill_statistics.py` - Statistics population script

### Database
- Migration for notification columns if needed
- Add notification type entries

---

## Next Steps

1. Create detailed plan for each issue
2. Prioritize implementation order
3. Design notification structure
4. Implement homepage change (quick win)
5. Build out statistics backfill
6. Restructure notifications tab
