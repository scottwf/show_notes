# User Profile Page - Implementation Plan

## Overview
Create a comprehensive user profile page to replace the "Your Profile (soon)" placeholder in the main navigation menu. This will be the central hub for users to manage their preferences, view watch history, and customize their ShowNotes experience.

## Current Database Support
The following tables already exist and can be leveraged:

1. **`users`** - User account information (username, Plex credentials, admin status)
2. **`plex_activity_log`** - Complete watch history (play, pause, resume, stop, scrobble events)
3. **`user_show_preferences`** - Notification preferences per show
4. **`notifications`** - User notifications queue
5. **`issue_reports`** - User-submitted issue reports

## Profile Page Features

### 1. **Profile Header**
- Display user's Plex username and profile picture (if available from Plex API)
- Last login timestamp
- Member since date
- Quick stats card:
  - Total episodes watched
  - Total movies watched
  - Shows followed
  - Active notifications

### 2. **Watch History Tab** (Default View)
- **Recent Activity** (Last 30 days)
  - Timeline view of all watched content
  - Group by date with expandable sections
  - Show poster thumbnails, titles, and S#E# for episodes
  - Display watch progress percentage for partially watched content
  - Link directly to show/episode/movie detail pages
  
- **Filters & Search**
  - Filter by media type (Movies, TV Shows, All)
  - Search within watch history
  - Date range selector
  - Sort options: Recent, Alphabetical, Most Watched

- **Statistics**
  - Most watched shows (by episode count)
  - Favorite genres (derived from watched content)
  - Watch time heatmap (time of day, day of week)
  - Monthly viewing trends chart

### 3. **Favorites & Following Tab**
- **Favorite Shows**
  - Grid/list view of shows user has marked as favorites
  - Quick "Add to Favorites" star button on show detail pages
  - Shows current season/episode status
  - Next episode to air (if show is continuing)
  - Notification settings toggle per show
  
- **Currently Watching**
  - Shows where user has watched episodes but not finished
  - Display next unwatched episode
  - Progress through season/series percentage
  - "Mark as Dropped" option

### 4. **Notifications Tab**
- **Notification Center**
  - List of all notifications (new episodes, season finales, etc.)
  - Mark as read/unread
  - Delete notifications
  - Filter by type and status
  
- **Notification Preferences** (Global Settings)
  - Enable/disable notification types:
    - New episode available
    - Season finale available
    - Series finale available
    - Show returning from hiatus
  - Notification delivery method (currently Pushover, future: in-app only)
  - Notification timing (immediate, daily digest, weekly digest)
  - Quiet hours configuration

### 5. **Settings Tab**
- **Display Preferences**
  - Default view (Grid/List for show/movie pages)
  - Episodes per page
  - Spoiler protection level
  - Auto-play next episode preference
  
- **Privacy Settings**
  - Watch history visibility (future: for multi-user scenarios)
  - Profile visibility
  
- **Account Settings**
  - Change password (for admin users with password auth)
  - Disconnect/Reconnect Plex account
  - Export watch history data
  - Account deletion request

### 6. **Issue Reports Tab**
- View all issue reports submitted by the user
- Status tracking (Open, In Progress, Resolved)
- Add new issue report
- View admin responses/resolution notes

## Database Schema Changes Needed

### New Tables

```sql
-- User favorites/following
CREATE TABLE user_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_dropped BOOLEAN DEFAULT 0,
    dropped_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (user_id, show_id)
);

-- User display preferences
CREATE TABLE user_preferences (
    user_id INTEGER PRIMARY KEY,
    default_view TEXT DEFAULT 'grid',
    episodes_per_page INTEGER DEFAULT 20,
    spoiler_protection TEXT DEFAULT 'partial',
    notification_digest TEXT DEFAULT 'immediate',
    quiet_hours_start TEXT,
    quiet_hours_end TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Add last_login_at to users table (migration)
ALTER TABLE users ADD COLUMN last_login_at DATETIME;
ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;
```

### Table Modifications

Update `user_show_preferences`:
```sql
-- Already exists, just ensure it has:
-- - notify_new_episode
-- - notify_season_finale
-- - notify_series_finale
-- - notify_time (immediate, daily, weekly)
```

## Route Structure

```
/profile                    # Main profile page (redirect to /profile/history)
/profile/history            # Watch history tab
/profile/favorites          # Favorites & following tab
/profile/notifications      # Notifications center
/profile/settings           # User settings
/profile/reports            # Issue reports

# API Endpoints
/api/profile/favorite/<int:show_id>              # POST/DELETE to add/remove favorite
/api/profile/notifications/<int:id>/read        # Mark notification as read
/api/profile/notifications/<int:id>/delete      # Delete notification
/api/profile/preferences                         # GET/PUT user preferences
/api/profile/watch-stats                         # GET watch statistics data
```

## UI/UX Design Considerations

### Layout
- Use tabbed navigation at the top
- Consistent with existing admin panel style
- Mobile-responsive design
- Dark mode compatible

### Key UI Components Needed
1. **Activity Timeline Component** - For watch history
2. **Favorite Show Card** - With poster, progress, next episode
3. **Notification Item** - With timestamp, type badge, read status
4. **Stats Card** - Reusable for various statistics
5. **Chart Components** - For viewing trends (use Chart.js)

### Visual Hierarchy
1. Profile header with key stats (always visible)
2. Tab navigation (sticky on scroll)
3. Tab content area (scrollable)
4. Call-to-action buttons prominently placed

## Implementation Phases

### Phase 1: Foundation (MVP) ✓ Recommended Priority
- [ ] Create database migrations for new tables
- [ ] Build basic `/profile` route and template structure
- [ ] Implement Watch History tab (recent 50 items, simple list)
- [ ] Add "Favorite" star button to show detail pages
- [ ] Create basic Favorites tab showing favorited shows
- [ ] Enable navigation: Update "Your Profile (soon)" link to `/profile`

### Phase 2: Enhanced History & Stats
- [ ] Add date range filtering to watch history
- [ ] Implement search within watch history
- [ ] Create watch statistics dashboard
- [ ] Add charts for viewing trends
- [ ] Implement "Most Watched" and genre analysis

### Phase 3: Notifications System
- [ ] Build notification center UI
- [ ] Implement per-show notification preferences
- [ ] Add global notification settings
- [ ] Create background job to check for new episodes and generate notifications
- [ ] Integrate Pushover for external notifications

### Phase 4: Settings & Preferences
- [ ] Build user preferences form
- [ ] Implement preference persistence
- [ ] Add account management features
- [ ] Enable watch history export

### Phase 5: Polish & Advanced Features
- [ ] Improve "Currently Watching" detection logic
- [ ] Add "Mark as Dropped" functionality
- [ ] Implement spoiler protection features
- [ ] Create onboarding tour for new users
- [ ] Add profile customization (themes, avatars)

## Technical Considerations

### Performance
- Implement pagination for watch history (can grow very large)
- Use database indexes on `user_id` for fast queries
- Cache watch statistics (refresh hourly or on-demand)
- Lazy-load images in activity timeline

### Security
- Ensure users can only access their own profile data
- Validate all user inputs
- Sanitize notification messages
- Rate limit API endpoints to prevent abuse

### Accessibility
- Proper ARIA labels for all interactive elements
- Keyboard navigation support
- Screen reader friendly
- Color contrast compliance (WCAG AA)

## Success Metrics
- User engagement with profile features
- Percentage of users who favorite shows
- Notification opt-in rates
- Average time spent on profile page
- Feature usage analytics (which tabs are most visited)

## Future Enhancements (Post-Launch)
- Social features (compare watch lists with friends)
- Recommendations based on watch history
- Watchlist/queue functionality
- Integration with external services (Trakt, IMDb)
- Custom lists and collections
- Watch goals and achievements/badges
- Year in review (annual watch statistics)
