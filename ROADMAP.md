# ShowNotes Roadmap

Track feature work here. Dev branch → test at `sn.chitekmedia.club` → merge to prod at `shownotes.chitekmedia.club`.

---

## v1.0 — Stabilization (current)

Get prod solid before opening to friends.

- [x] Homepage 72s perf fix (broken CAST join in `load_premieres`)
- [x] `players_today` query full-scan fix (563ms → 1.6ms)
- [x] Sonarr webhook crash fix (`seasons` → `season_count` column)
- [x] Auth hardening — `SECRET_KEY` from env, `SESSION_COOKIE_SECURE`, Plex OAuth `session.permanent`
- [x] Prod/dev split — `shownotes.chitekmedia.club` / `sn.chitekmedia.club`
- [x] Calendar page perf audit — CAST join in `get_calendar_data_for_user` (utils.py:2543) fixed
- [x] Remaining `DATE(event_timestamp)` in non-auth stats path (main.py:217) fixed
- [ ] N+1 season summary queries in `show_detail` (main.py:2413) — batch fetch needed
- [ ] LIKE `%title%` search (main.py:2123) — no index can help; needs FTS5 or prefix-only

---

## v1.1 — Multi-user & Social

First feature milestone after prod is stable.

### User management
- [ ] User registration flow (invite link or open registration toggle)
- [ ] Per-user watch history (Tautulli data scoped to each user's Plex account)
- [ ] User profile pages (public-facing watch stats, recent activity)
- [ ] Friends list / follow system

### Social features
- [ ] Activity feed — see what friends are watching
- [ ] Shared watchlists
- [ ] Episode/movie ratings (personal, optionally visible to friends)
- [ ] Comments on shows/episodes

---

## v1.2 — Discovery & Recommendations

- [ ] "Because you watched X" recommendations
- [ ] Friends' picks — what are people in your network watching
- [ ] Genre/mood filters on the homepage
- [ ] "Continue watching" row (in-progress episodes with progress bar)

---

## v1.3 — Polish & Power Features

- [ ] Mobile-responsive improvements (current UI is functional but not optimized)
- [ ] Push notifications (new episode of favorited show, friend activity)
- [ ] Better calendar — filter by user, show upcoming vs. aired state
- [ ] Export watch history (CSV, Letterboxd-compatible for movies)
- [ ] Homepage customization (reorder/hide sections per user)

---

## Backlog (unscheduled)

- Better Bazarr integration (subtitle availability per episode)
- Deeper Tautulli stats (watch time graphs, completion rates)
- TMDB/TVDB enrichment improvements
- Docker one-click setup for self-hosters
- Public instance hardening (rate limiting, abuse prevention)

---

## Notes

- All feature work happens on dev (`sn.chitekmedia.club`) first
- Deploy to prod only after testing on dev
- Keep the prod deploy clean — no debug prints, no temp instrumentation
