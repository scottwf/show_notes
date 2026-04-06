# ShowNotes Roadmap

Track feature work here. Dev branch → test at `sn.chitekmedia.club` → merge to prod at `shownotes.chitekmedia.club`.

---

## v1.0 — Stabilization ✓

- [x] Homepage 72s perf fix (broken CAST join in `load_premieres`)
- [x] Calendar CAST join fix (`get_calendar_data_for_user` in utils.py)
- [x] `DATE(event_timestamp)` full-scan fix — both instances (563ms → 1.6ms)
- [x] Sonarr webhook crash fix (`seasons` → `season_count` column)
- [x] Auth hardening — `SECRET_KEY` from env, `SESSION_COOKIE_SECURE`, Plex OAuth `session.permanent`
- [x] Prod/dev split — `shownotes.chitekmedia.club` / `sn.chitekmedia.club`
- [ ] N+1 season summary queries in `show_detail` (main.py:2413) — batch fetch
- [ ] Search `LIKE '%title%'` — needs SQLite FTS5 for real fix

---

## v1.1 — UX Polish + Profile Redesign

Make the app intuitive for non-technical users before building social features on top.

### Homepage header
- [ ] Add explicit "View my profile →" label/button — avatar+username link is invisible without hover
- [ ] Split stats row: keep server stats (current viewers, plays today, library size) but add a
      second row of **personal stats** for the logged-in user (my shows watched, my episodes, my watch time)
- [ ] Server stats label cleanup: "Now Playing" → "Watching Now", "Players Today" → "Viewers Today"

### Profile page redesign
- [ ] Banner/cover photo support
- [ ] Bio / display name (separate from Plex username)
- [ ] "Member since" → human-friendly format ("Watching since March 2023")
- [ ] Always show tab labels (not icon-only on mobile)
- [ ] Consolidate tabs — aim for 4–5 max (History · Favorites · Lists · Stats · Settings)
- [ ] Public profile view (what others see vs. what you see on your own profile)
- [ ] Privacy toggle: opt-in to appearing on the Members page

### General UX
- [ ] Clearer clickable affordances throughout (buttons look like buttons, links have underlines or arrows)
- [ ] "Continue watching" row on homepage — in-progress episodes with progress bar
- [ ] Empty state messaging — new users should see helpful prompts, not blank sections

---

## v1.2 — Multi-User & Social Foundation

### Household profiles (decided)
One Plex account can have multiple ShowNotes profiles (e.g. you + wife + anyone else sharing
the account). Play history stays shared under one `plex_username` — that's fine. What's
per-profile: favorites, watchlist, recommendations, avatar, display name.

- [ ] `household_members` table: `(id, user_id, display_name, avatar_url)`
- [ ] Add `member_id` FK to `user_favorites`, `user_notifications`, lists, ratings
- [ ] "Who's watching?" picker on login if multiple profiles exist — sets `sn_member_id` cookie
- [ ] Profile page: "Add a profile to this Plex account" button (creates a household member)
- [ ] Profile switcher in nav/header

### Friends & discovery
- [ ] User registration — invite link (admin sends, user claims via Plex OAuth)
- [ ] Members page — opt-in directory with avatar, bio, currently watching
- [ ] Follow system — follow a member to see their public activity
- [ ] Watch status per show: Watching / Completed / Dropped / Want to Watch
- [ ] Activity feed on homepage — recent watches from people you follow

---

## v1.3 — Comments & Recommendations

- [ ] Comments on shows, seasons, and episodes
  - Spoiler-aware: comments hidden until viewer has watched up to that point
  - Tautulli history determines what's safe to show each user
- [ ] Friend recommendations with context ("X who also watched Breaking Bad recommends this")
- [ ] "Also watching" indicator — badge when a follower is within a few episodes of you on the same show
- [ ] Episode/show ratings (personal star rating, visible to followers)

---

## v1.4 — Notifications

Using **ntfy** (already running in homelab) for self-hosted push notifications to phones.

- [ ] Returning show alerts — scheduled job detects when a show you've watched is getting a new season
- [ ] Season finale alert — Tautulli webhook fires when you start the last episode of a season → push to phone
- [ ] New episode available — notify when a show you follow has a new episode downloaded
- [ ] Friend activity digest — daily/weekly summary of what people you follow watched
- [ ] Notification preferences per user (opt in/out per type)

---

## Backlog (unscheduled)

- Search: SQLite FTS5 full-text search to replace `LIKE '%query%'` scans
- Calendar: filter by user, better "aired vs. upcoming" visual distinction
- Watch time graphs and completion rate stats (deeper Tautulli integration)
- Bazarr integration: subtitle availability per episode
- Export watch history (CSV, Letterboxd-compatible for movies)
- Homepage section customization (reorder/hide sections per user)
- Docker one-click setup for self-hosters
- Public instance hardening (rate limiting, abuse prevention)

---

## Notes

- All feature work on dev (`sn.chitekmedia.club`) first — deploy to prod only after testing
- "Mom test": every new UI element should be understandable without explanation
- Keep prod deploys clean — no debug prints, no temp instrumentation
