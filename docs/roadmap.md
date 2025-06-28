# Project Roadmap

This document outlines the planned features and development stages for the ShowNotes application.

## Completed
- [x] **Search Navigation Highlighting:** Added visual highlight for keyboard-selected search items.
- [x] **Local Image Caching & Loading:** Switched movie/show images to load from local cache (`/static/poster/`, `/static/background/`) and updated Sonarr/Radarr sync jobs to queue images with TMDB ID based filenames.
- [x] **Show Detail Page Overhaul:** Redesigned show detail page with background image, poster, full metadata (first air date, status, next episode, IMDb link), collapsible seasons/episodes list, and 'currently watched' status display.
- [x] **Homepage Layout Update:** Implemented new homepage design with prominent 'current' item (playing/paused) and a grid of 'previously watched' items, based on detailed Plex activity history.
- [x] **Dynamic Service Status Indicators:** Added visual connection status indicators (green/red dots) for configured services that update in real-time via JavaScript.
- [x] Plex OAuth login (PIN-based, DB-stored credentials), logout, session management, and onboarding fixes.
- [x] **Enhanced Plex Event Handling & Homepage Display (Initial):** Implemented detailed logging of Plex webhook events (play, pause, resume, stop, scrobble) into a new `plex_activity_log` table. Initial homepage update to display "Now Playing" or "Recently Played" information. (Further enhanced by the new layout update).
- [x] **Search Image Display Fix:** Corrected image display in search results by ensuring absolute URLs and proper API key usage for Sonarr/Radarr images, with on-demand caching.
- [x] Integrate Sonarr/Radarr APIs for reliable poster/metadata display.
- [x] Admin settings UI for service URLs and API keys (initial version).
- [x] Separated Sonarr and Radarr library sync functionalities with dedicated admin actions.
- [x] Foundational Admin Panel UI: Responsive sidebar, dashboard page (`/admin/dashboard`), and integration of service settings into the new layout.
- [x] Basic Flask application structure.
- [x] Database setup (SQLite).
- [x] Tailwind CSS integration & Dark Mode.
- [x] Basic HTML templates and routes.
- [x] Initial documentation setup.
- [x] **Admin Tasks Page:** Created a dedicated page (`/admin/tasks`) for managing Sonarr and Radarr library synchronization.
- [x] **Sync Operation Feedback:** Implemented flash messages to inform users of the number of items processed after Sonarr/Radarr sync.
- [x] **Admin UI Consistency:** Standardized styling for sidebar navigation links (e.g., 'Tasks' link) to match other admin links.
- [x] **Task Button Styling:** Restyled Sonarr/Radarr sync buttons on the `/admin/tasks` page for better visual consistency.
- [x] **Logo Display Fixes:** Corrected display of Sonarr and Radarr logos on the `/admin/tasks` page for proper visibility in both light and dark modes.
- [x] **Flask Route Modularization:** Refactored application routes into Admin (`/admin`) and Main blueprints for improved organization and maintainability.
- [x] **Interactive Service Connection Testing:** Enhanced the Admin Services page to allow manual testing of service connections (Sonarr, Radarr, Bazarr, Ollama, Pushover) using current form values, with immediate visual feedback and resolution of related `url_for` and JavaScript issues.
- [x] **Tautulli Integration:** Watch history synchronization via Tautulli API with connection testing.
- [x] **Admin Logbook & User List:** Added logbook page and basic Plex user listing.
- [x] **Episode Detail Pages:** Added standalone episode pages with air date and availability label. (Further enhanced - see below)
- [x] **Episode List Cleanup:** Season 0 hidden by default; episodes show "Available" when files exist. (Further enhanced - see below)
- [x] **Header Consistency and Layout (Main and Admin):** Standardized header appearance; admin header now full-width.
- [x] **Search Bar Responsiveness (Mobile):** Main site search results now use a modal display on mobile.
- [x] **Image Caching and Display:** Ensured consistent use of locally cached static images with proper fallbacks.
- [x] **Episodes List Improvements (Show Detail Page):**
    - [x] Confirmed Season 0 ("Specials") hidden.
    - [x] Added "Most Recently Watched" / "Currently Watching" card.
    - [x] "Available" label for episodes confirmed.
- [x] **Episode Detail Pages (Content and Links):** Revamped with comprehensive information (poster, air date, summary, availability, runtime, rating) and "Back to Show" link.
- [x] **Admin Search Functionality:** Implemented unified search in the admin panel for shows, movies, and admin routes.
- [x] **README and Roadmap updates:** Documentation updated to reflect recent changes (this item).
- [x] **Descriptive comments:** Added docstrings and inline comments to key Python files (this item).
- [x] **LLM Integration & Management UI:**
    - [x] Added admin pages to view and test LLM prompt templates.
    - [x] Implemented API usage logging with a dedicated page to view provider, token counts, cost, and processing time.
    - [x] Enhanced the settings page to allow selection between LLM providers (e.g., Ollama, OpenAI) and configure model names.
- [x] **Core LLM Features:**
    - [x] Spoiler-aware character summaries (Ollama/OpenAI integration).
    - [x] Relationship mapping and actor overlap via LLM generation.
    - [x] "Currently Watching" tracking via Plex webhook integration.
- [x] **Subtitle Integration (Bazarr):** Foundational support for parsing subtitles via an admin task.

## Next Steps

- [ ] **Enhance Character Detail Page UI:** Redesign the character detail page to present LLM-generated content in a more organized and visually appealing manner (e.g., using a card-based or tabbed layout).
- [ ] **Refine "Next Up" Feature:** Improve the logic for determining the next unwatched episode and display it more prominently on the show detail page and homepage.
- [ ] **Improve Plex User Detection:** Increase the robustness of Plex user detection at login to handle edge cases and ensure more reliable username/ID capture.
- [ ] **Improve UI/UX Feedback:** Add loading indicators for image fetches and error states for missing images to provide better feedback on slower connections.

## Future Enhancements

- [ ] **Advanced Admin Dashboard:**
    - [ ] Display real-time usage statistics (e.g., active users, Plex events processed).
    - [ ] Show recent user logins and a more detailed history of events per user.
    - [ ] Implement a notification system for important alerts or errors.
- [ ] **Advanced Search & Filtering:** Implement more powerful search capabilities with filters for genre, year, actors, etc.
- [ ] **Interactive Character Chat:** Develop the LLM-powered summary feature into a fully interactive, in-character chat experience.
- [ ] **User-Specific Features:**
    - [ ] Create dedicated user watch history and recommendations pages.
    - [ ] Allow for customizable user dashboards.
- [ ] **Documentation:**
    - [ ] Create in-app help and documentation for administrators and users.
    - [ ] Document the setup and troubleshooting process for multi-user environments.
- [ ] **Testing:** Implement a comprehensive suite of unit and integration tests to ensure application stability.
- [ ] **Notifications:** Fully integrate Pushover for notifications about file issues or other system events.
