# Discover Page Tab Reorganization

**Date:** 2026-04-25
**Status:** Approved

## Goal

Reorganize the Discover page's single "Popular" tab — which currently stacks six content sections vertically — into two distinct top-level tabs: **Popular** and **Trending**. This reduces scroll depth and makes each tab's content more focused.

## Tab Structure

| Tab | Visibility | Content sections |
|-----|-----------|-----------------|
| Popular | Always | Popular Shows, Popular Movies |
| Trending | Always | Watching Live, Binge Watch, Night Owl, Early Bird |
| Recommended | Conditional (`received_recs or community_picks`) | Community Picks, Shared With You |
| Upcoming | Conditional (`jellyseer_url`) | Jellyseerr upcoming movies |

Default active tab on page load: **Popular** (unchanged).

## Changes Required

### `app/templates/discover.html` (only file modified)

1. **Tab navigation bar** — add a "Trending" button between Popular and Recommended; rename "Upcoming Movies" to "Upcoming".
2. **Popular tab content** (`#popular-tab`) — remove Watching Live, Binge Watch, Night Owl, Early Bird. Keep Popular Shows and Popular Movies. The existing empty state ("No viewing activity in the last 30 days") remains for when both are empty.
3. **Trending tab content** (new `#trending-tab`) — contains Watching Live, Binge Watch, Night Owl, Early Bird, moved verbatim from the Popular tab. Shows the same empty state if all four sections have no data.
4. **Recommended and Upcoming tabs** — content unchanged; "Upcoming Movies" button label shortened to "Upcoming".
5. **JavaScript** — no logic changes needed. `showTab()` already handles arbitrary tab IDs via `data-tab` attributes and `${tab}-tab` element IDs.

## What Does Not Change

- Backend route (`discover()` in `media_routes.py`) — all data already fetched; no new queries needed.
- Content within each section — posters, badges, overlays, hover effects unchanged.
- Conditional rendering logic for Recommended and Upcoming tabs.
- Tab switching animation and active-state styling.
