# User Profile Features

## Overview

User profiles provide personalized tracking and management of watch history, favorites, and preferences.

## Current Features

### Profile Pages
- **Watch History** - Recent viewing activity with progress tracking
- **Favorites** - Grid of favorited shows with management
- **Progress** - Track show completion status
- **Lists** - Custom user lists for organizing content
- **Statistics** - Viewing analytics and trends
- **Recommendations** - Personalized suggestions
- **Settings** - Profile customization and privacy

### Profile Data
- Plex username and profile photo
- Member since date (from Plex account)
- Watch statistics (episodes, movies, shows)
- Favorites tracking
- Custom lists
- Notification preferences

### Integration
- Plex activity log for watch history
- Real-time progress via Tautulli
- Automatic updates via webhooks
- Profile photo sync from Plex

## Technical Implementation

### Database Tables
- `users` - User accounts and preferences
- `plex_activity_log` - Watch history events
- `user_favorites` - Favorited shows
- `user_lists` - Custom user lists
- `user_show_preferences` - Per-show notification settings
- `notifications` - User notification queue
- `issue_reports` - User-submitted problems

### Authentication
- Plex OAuth for authentication
- Session management via Flask-Login
- 30-day session persistence

## Future Enhancements

- Multi-user sub-profiles per account
- Enhanced statistics visualization
- Watch goals and achievements
- Social features (shared lists)
- Trakt/IMDb integration
- Year in review
