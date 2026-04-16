# Calendar Week View — Design Spec

**Date:** 2026-04-16  
**Status:** Approved

---

## Overview

Add a navigable week grid to the existing `/calendar` page. The grid sits above the existing list sections and gives users a compact at-a-glance view of what's airing across the week. The existing TV Countdown, Season Finales, and Premieres list sections remain unchanged below it.

---

## Layout & Structure

The page structure becomes:

1. Header + filter tabs (unchanged)
2. **Week grid** (new)
3. TV Countdown list (unchanged)
4. Season Finales list (unchanged)
5. Series & Season Premieres list (unchanged)

The filter tabs (All / Favorites / Premieres / Finales / My Requests) apply to **both** the grid and the lists — active filters hide non-matching chips in the grid and non-matching list items below.

---

## Week Grid — Desktop (`md` and up)

- Seven columns, Monday through Sunday
- Week navigation: ‹ previous / Today / › next buttons in the top-right of the grid section
- Today's column: blue outline (`outline-2 outline-sky-500`)
- Past days: 50% opacity, dimmed
- Each **show** gets at most **one chip per day**:
  - If a show has a single episode airing that day → chip links to the episode detail page
  - If a show has multiple episodes airing that day → chip shows `Show Name ×N` and links to the show page
- Chip colors:
  - **Blue** (`bg-blue-900 border-l-2 border-blue-500 text-blue-200`) — regular episode
  - **Purple** (`bg-purple-900 border-l-2 border-purple-500 text-purple-300`) — season premiere or series premiere
  - **Red** (`bg-red-900 border-l-2 border-red-500 text-red-300`) — season finale
- Empty days show a muted `—` placeholder
- Day columns have a minimum height to avoid collapse on empty weeks

---

## Week Grid — Mobile (below `md`)

Single-day view replacing the 7-column grid:

- Large centered day name + date number + month/year
- ‹ › tap targets on either side to step forward/back one day
- **Dot strip**: 7 small dots representing Mon–Sun of whichever week contains the currently displayed day
  - Filled blue dot = day has events
  - Larger/brighter dot = today
  - Updates automatically when stepping past Sunday or before Monday into a new week
  - Lets users see at a glance which days are busy without tapping through
- Events listed as full-width chips below, same color coding as desktop
- Chips link to episode detail (single) or show page (multiple episodes)

---

## Navigation & Data

### Client-side navigation (Alpine.js)

Week navigation requires no HTTP requests. All data is pre-loaded:

- Python computes a **5-week window**: 7 days back + 28 days ahead from today
- Events are bucketed into `events_by_date`: a dict keyed `YYYY-MM-DD`, each value a list of event objects
- Passed to the template as `|tojson` and picked up by Alpine.js
- Alpine.js tracks `weekOffset` (integer, default 0) and computes the 7 dates to display
- `weekOffset = 0` always anchors to the current Mon–Sun week containing today
- Today button resets `weekOffset` to 0

### Event object shape (per entry in `events_by_date`)

```json
{
  "show_title": "The Bear",
  "show_url": "/show/1234",
  "episode_url": "/show/1234/season/3/episode/1",
  "season_number": 3,
  "episode_number": 1,
  "episode_title": "Forks",
  "type": "episode",
  "is_favorited": true,
  "is_premiere": false,
  "is_finale": false,
  "is_series_premiere": false
}
```

`type` is one of `"episode"`, `"premiere"`, `"finale"`.

### Collapsing multi-episode chips

Before rendering, events for each day are grouped by `show_title`. Groups with more than one entry become a single chip showing `×N` with `url` pointing to the show page. Single-entry groups link to the episode detail page.

This grouping happens in Alpine.js (client-side) so the filter state can be applied before grouping.

---

## Backend Changes

### `calendar_recommendations_routes.py`

- Extend the query window in `get_calendar_data_for_user` (or in the route itself) to cover 7 days back + 28 days ahead
- After fetching `tracked_upcoming`, `premieres`, and `finales`, build `events_by_date`:
  ```python
  events_by_date = {}  # { "2026-04-16": [ {...}, ... ] }
  ```
  Populate from all three event lists, tagging each entry with its `type`.
- Pass `events_by_date` to the template alongside the existing context variables.

### `utils.py` / `get_calendar_data_for_user`

- Widen the date window from the current value to `today - 7 days` through `today + 28 days` to support week navigation across ~4 future weeks.

---

## Template Changes (`calendar.html`)

- Add Alpine.js `x-data` block with:
  - `weekOffset` (int, default 0)
  - `eventsJson` (from `events_by_date | tojson`)
  - Computed `weekDays` array (7 date strings for the current offset)
  - `eventsForDay(dateStr)` — returns filtered + grouped chips for a date
  - `goToday()`, `prevWeek()`, `nextWeek()`
- Desktop grid: `hidden md:grid` with 7 `x-for` day columns
- Mobile view: `md:hidden` single-day navigator with dot strip
- Existing list sections: unchanged markup, existing Alpine filter logic untouched

---

## Responsive Breakpoints

| Breakpoint | Grid behavior |
|---|---|
| `< md` (< 768px) | Single-day view with dot strip and ‹ › |
| `md+` (≥ 768px) | 7-column week grid |

---

## Out of Scope

- Swipe gestures on mobile (can be added later)
- Clicking a dot to jump directly to that day (can be added later)
- Displaying episode overview/poster in the grid (lists below handle detail)
- iCal subscription fixes (separate spec)
