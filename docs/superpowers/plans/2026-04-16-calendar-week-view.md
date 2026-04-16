# Calendar Week View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a navigable 7-day week grid to the `/calendar` page, above the existing list sections, with a responsive single-day mobile view.

**Architecture:** Python buckets all calendar events into an `events_by_date` dict (keyed `YYYY-MM-DD`) and passes it as JSON to the template. Alpine.js handles all week navigation client-side with no extra HTTP requests. The existing list sections and filter tabs are unchanged.

**Tech Stack:** Flask, SQLite, Jinja2, Alpine.js, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-16-calendar-week-view-design.md`

---

## File Map

| File | Change |
|---|---|
| `app/calendar_service.py` | Widen `upcoming_episodes` query window to include 7 days back |
| `app/routes/main/calendar_recommendations_routes.py` | Add `_build_events_by_date()` helper, pass `events_by_date` JSON to template |
| `app/templates/calendar.html` | Replace outer `x-data`, add week grid (desktop + mobile), keep lists unchanged |

---

## Task 1: Widen the calendar data window to include past week

The current `build_calendar_data` query for `upcoming_episodes` starts at `now` (current timestamp). The week grid needs to show events from the start of the current week (up to 6 days in the past). Change the start to 7 days ago.

**Files:**
- Modify: `app/calendar_service.py` around line 312–343

- [ ] **Step 1: Update the query start date**

In `build_calendar_data`, find this block (~line 312):

```python
now_utc = dt.datetime.now(dt.timezone.utc)
now = now_utc.strftime('%Y-%m-%d %H:%M:%S')
today = now_utc.date().isoformat()

# Get all upcoming episodes (next 30 days, limit 200)
thirty_days_later = (now_utc.date() + dt.timedelta(days=30)).isoformat()

upcoming_episodes = db.execute("""
    ...
    WHERE e.air_date_utc >= ?
      AND e.air_date_utc <= ?
      AND ss.season_number > 0
    ORDER BY e.air_date_utc ASC
    LIMIT 200
""", (now, thirty_days_later + ' 23:59:59')).fetchall()
```

Replace with:

```python
now_utc = dt.datetime.now(dt.timezone.utc)
now = now_utc.strftime('%Y-%m-%d %H:%M:%S')
today = now_utc.date().isoformat()

# Get episodes for the week grid window: 7 days back + 28 days ahead
seven_days_ago = (now_utc.date() - dt.timedelta(days=7)).isoformat()
twenty_eight_days_later = (now_utc.date() + dt.timedelta(days=28)).isoformat()

upcoming_episodes = db.execute("""
    SELECT
        e.id as episode_id,
        e.title as episode_title,
        e.episode_number,
        e.air_date_utc,
        e.overview as episode_overview,
        e.has_file,
        ss.season_number,
        s.id as show_id,
        s.title as show_title,
        s.tmdb_id,
        s.tvdb_id,
        s.year,
        s.status,
        s.network_name
    FROM sonarr_episodes e
    JOIN sonarr_seasons ss ON e.season_id = ss.id
    JOIN sonarr_shows s ON ss.show_id = s.id
    WHERE e.air_date_utc >= ?
      AND e.air_date_utc <= ?
      AND ss.season_number > 0
    ORDER BY e.air_date_utc ASC
    LIMIT 400
""", (seven_days_ago, twenty_eight_days_later + ' 23:59:59')).fetchall()
```

- [ ] **Step 2: Verify the app still starts cleanly**

```bash
cd /home/scott/projects/show_notes_dev
.venv/bin/python -c "from app import create_app; app = create_app(); print('OK')"
```

Expected: `OK` with no tracebacks.

- [ ] **Step 3: Commit**

```bash
git add app/calendar_service.py
git commit -m "feat: widen calendar episode window to 7 days back + 28 days ahead"
```

---

## Task 2: Build `events_by_date` in the calendar route and pass to template

Add a helper function `_build_events_by_date` in the calendar route file that takes the already-formatted episode lists (with URLs) and buckets them into a dict keyed by `YYYY-MM-DD`. Pass this as JSON to the template.

**Files:**
- Modify: `app/routes/main/calendar_recommendations_routes.py`

- [ ] **Step 1: Add the helper function**

After the imports at the top of `calendar_recommendations_routes.py`, add this function before the `@main_bp.route('/calendar')` decorator:

```python
def _build_events_by_date(upcoming, premieres, finales):
    """
    Bucket formatted calendar events into a dict keyed by YYYY-MM-DD.

    Each value is a list of event dicts with shape:
        show_title, show_url, episode_url, season_number, episode_number,
        episode_title, type ('episode'|'premiere'|'finale'),
        is_favorited, is_premiere, is_finale, is_series_premiere

    Args:
        upcoming: formatted tracked_upcoming episodes (list of dicts)
        premieres: formatted series_premieres (list of dicts)
        finales: formatted season_finales (list of dicts)

    Returns:
        dict[str, list[dict]]
    """
    import datetime as _dt

    events_by_date = {}

    def _date_key(date_str):
        """Extract YYYY-MM-DD from an ISO datetime string or return None."""
        if not date_str:
            return None
        try:
            return str(date_str)[:10]
        except Exception:
            return None

    def _add(date_key, event):
        if date_key:
            events_by_date.setdefault(date_key, []).append(event)

    for ep in upcoming:
        key = _date_key(ep.get('air_date_utc'))
        _add(key, {
            'show_title': ep.get('show_title', ''),
            'show_url': ep.get('show_url', ''),
            'episode_url': ep.get('episode_url', ''),
            'season_number': ep.get('season_number'),
            'episode_number': ep.get('episode_number'),
            'episode_title': ep.get('episode_title', ''),
            'type': 'episode',
            'is_favorited': ep.get('is_favorited', False),
            'is_premiere': ep.get('is_season_premiere', False),
            'is_finale': False,
            'is_series_premiere': ep.get('is_series_premiere', False),
        })

    for ep in premieres:
        key = _date_key(ep.get('premiere_date') or ep.get('air_date_utc'))
        _add(key, {
            'show_title': ep.get('show_title', ''),
            'show_url': ep.get('show_url', ''),
            'episode_url': ep.get('episode_url', ''),
            'season_number': ep.get('season_number'),
            'episode_number': ep.get('episode_number'),
            'episode_title': ep.get('episode_title', ''),
            'type': 'premiere',
            'is_favorited': ep.get('is_favorited', False),
            'is_premiere': True,
            'is_finale': False,
            'is_series_premiere': ep.get('is_series_premiere', False),
        })

    for ep in finales:
        key = _date_key(ep.get('finale_date') or ep.get('air_date_utc'))
        _add(key, {
            'show_title': ep.get('show_title', ''),
            'show_url': ep.get('show_url', ''),
            'episode_url': ep.get('episode_url', ''),
            'season_number': ep.get('season_number'),
            'episode_number': ep.get('episode_number'),
            'episode_title': ep.get('episode_title', ''),
            'type': 'finale',
            'is_favorited': ep.get('is_favorited', False),
            'is_premiere': False,
            'is_finale': True,
            'is_series_premiere': False,
        })

    return events_by_date
```

- [ ] **Step 2: Call the helper and pass events_by_date to the template**

In the `calendar()` route function, find the `return render_template(...)` call (currently around line 105):

```python
return render_template('calendar.html',
                     upcoming_episodes=formatted_upcoming,
                     series_premieres=formatted_premieres,
                     season_finales=formatted_finales)
```

Replace with:

```python
events_by_date = _build_events_by_date(
    formatted_upcoming,
    formatted_premieres,
    formatted_finales,
)

return render_template('calendar.html',
                     upcoming_episodes=formatted_upcoming,
                     series_premieres=formatted_premieres,
                     season_finales=formatted_finales,
                     events_by_date=events_by_date)
```

- [ ] **Step 3: Verify the route loads without error**

```bash
cd /home/scott/projects/show_notes_dev
.venv/bin/python -c "from app import create_app; app = create_app(); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/routes/main/calendar_recommendations_routes.py
git commit -m "feat: build events_by_date dict in calendar route and pass to template"
```

---

## Task 3: Add Alpine.js calendar component and desktop week grid to template

Replace the outer `x-data="{ filter: 'all' }"` div with a full `calendarApp()` Alpine.js component that manages both the filter state and the week grid. Add the desktop week grid HTML above the existing list sections.

**Files:**
- Modify: `app/templates/calendar.html`

- [ ] **Step 1: Replace the outer x-data and add the Alpine component script**

At the top of the `{% block page_content %}` block, find:

```html
<div class="container mx-auto px-2 sm:px-4 py-4 sm:py-6" x-data="{ filter: 'all' }">
```

Replace with:

```html
<div class="container mx-auto px-2 sm:px-4 py-4 sm:py-6" x-data="calendarApp()" x-init="init()">
```

Then, before `{% endblock %}`, add:

```html
<script>
function calendarApp() {
  return {
    filter: 'all',
    weekOffset: 0,
    mobileDayOffset: 0,
    events: {{ events_by_date | tojson }},

    init() {
      // No async needed — all data pre-loaded
    },

    // ── Shared helpers ──────────────────────────────────────────────

    _dateKey(date) {
      // Returns YYYY-MM-DD for a Date object
      const y = date.getFullYear();
      const m = String(date.getMonth() + 1).padStart(2, '0');
      const d = String(date.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    },

    _getMonday(date) {
      const d = new Date(date);
      const day = d.getDay(); // 0=Sun, 1=Mon...
      const diff = day === 0 ? -6 : 1 - day;
      d.setDate(d.getDate() + diff);
      d.setHours(0, 0, 0, 0);
      return d;
    },

    _todayKey() {
      return this._dateKey(new Date());
    },

    // ── Desktop week grid ────────────────────────────────────────────

    get weekDays() {
      const monday = this._getMonday(new Date());
      monday.setDate(monday.getDate() + this.weekOffset * 7);
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(monday);
        d.setDate(d.getDate() + i);
        return d;
      });
    },

    get weekLabel() {
      const days = this.weekDays;
      const fmt = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return `${fmt(days[0])} – ${fmt(days[6])}`;
    },

    isToday(date) {
      return this._dateKey(date) === this._todayKey();
    },

    isPast(date) {
      return this._dateKey(date) < this._todayKey();
    },

    eventsForDay(date) {
      const key = this._dateKey(date);
      const allEvents = this.events[key] || [];

      // Apply active filter
      const filtered = allEvents.filter(ev => {
        if (this.filter === 'all') return true;
        if (this.filter === 'favorites') return ev.is_favorited;
        if (this.filter === 'premieres') return ev.is_premiere;
        if (this.filter === 'finales') return ev.is_finale;
        if (this.filter === 'requests') return ev.user_requested;
        return true;
      });

      // Group by show_title → one chip per show per day
      const groups = {};
      for (const ev of filtered) {
        if (!groups[ev.show_title]) groups[ev.show_title] = [];
        groups[ev.show_title].push(ev);
      }

      return Object.values(groups).map(group => ({
        ...group[0],
        count: group.length,
        // Single ep → episode page; multiple eps → show page
        url: group.length === 1 ? group[0].episode_url : group[0].show_url,
      }));
    },

    prevWeek() { this.weekOffset--; },
    nextWeek() { this.weekOffset++; },
    goToday() { this.weekOffset = 0; this.mobileDayOffset = 0; },

    // ── Mobile single-day view ───────────────────────────────────────

    get mobileDay() {
      const d = new Date();
      d.setDate(d.getDate() + this.mobileDayOffset);
      d.setHours(0, 0, 0, 0);
      return d;
    },

    get mobileDayLabel() {
      return this.mobileDay.toLocaleDateString('en-US', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
      });
    },

    get mobileDayEvents() {
      return this.eventsForDay(this.mobileDay);
    },

    get weekDots() {
      const monday = this._getMonday(this.mobileDay);
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(monday);
        d.setDate(d.getDate() + i);
        const key = this._dateKey(d);
        return {
          date: d,
          key: key,
          isToday: key === this._todayKey(),
          isCurrent: key === this._dateKey(this.mobileDay),
          hasEvents: (this.events[key] || []).length > 0,
        };
      });
    },

    prevDay() { this.mobileDayOffset--; },
    nextDay() { this.mobileDayOffset++; },
  };
}
</script>
```

- [ ] **Step 2: Update the existing filter tab buttons**

The filter tabs currently use `@click="filter = 'all'"` etc. These still work because `filter` is now part of the same Alpine component. No changes needed to the filter tab markup.

- [ ] **Step 3: Add the desktop week grid section**

After the closing `</div>` of the filter tabs block (around line 56), and before the `<!-- TV Countdown -->` comment, insert:

```html
    <!-- ── Week Grid (desktop) ─────────────────────────────────────── -->
    <div class="hidden md:block mb-8">

      <!-- Week navigation header -->
      <div class="flex items-center justify-between mb-3">
        <div>
          <h2 class="text-base font-bold text-slate-800 dark:text-slate-100" x-text="weekLabel"></h2>
          <p class="text-xs text-slate-500 dark:text-slate-400"
             x-text="weekOffset === 0 ? 'Current week' : (weekOffset > 0 ? `+${weekOffset} week${weekOffset > 1 ? 's' : ''}` : `${weekOffset} week${weekOffset < -1 ? 's' : ''}`)">
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button @click="prevWeek()"
                  class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-200 dark:bg-slate-700
                         text-slate-600 dark:text-slate-300 hover:bg-slate-300 dark:hover:bg-slate-600
                         transition-colors text-sm font-bold">
            ‹
          </button>
          <button @click="goToday()"
                  class="px-3 py-1.5 rounded-lg bg-slate-200 dark:bg-slate-700 text-sky-600 dark:text-sky-400
                         text-xs font-semibold hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors">
            Today
          </button>
          <button @click="nextWeek()"
                  class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-200 dark:bg-slate-700
                         text-slate-600 dark:text-slate-300 hover:bg-slate-300 dark:hover:bg-slate-600
                         transition-colors text-sm font-bold">
            ›
          </button>
        </div>
      </div>

      <!-- 7-column grid -->
      <div class="grid grid-cols-7 gap-1.5">
        <template x-for="day in weekDays" :key="_dateKey(day)">
          <div class="rounded-lg overflow-hidden min-h-[90px] transition-opacity"
               :class="{
                 'bg-slate-100 dark:bg-slate-800': true,
                 'ring-2 ring-sky-500': isToday(day),
                 'opacity-50': isPast(day) && !isToday(day)
               }">

            <!-- Day header -->
            <div class="px-2 py-1.5 border-b border-slate-200 dark:border-slate-700 text-center">
              <div class="text-[9px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500"
                   x-text="day.toLocaleDateString('en-US', { weekday: 'short' })">
              </div>
              <div class="text-sm font-extrabold leading-none mt-0.5"
                   :class="isToday(day) ? 'text-sky-500' : (isPast(day) ? 'text-slate-400 dark:text-slate-600' : 'text-slate-800 dark:text-slate-100')"
                   x-text="day.getDate()">
              </div>
            </div>

            <!-- Events -->
            <div class="p-1.5 flex flex-col gap-1">
              <template x-if="eventsForDay(day).length === 0">
                <div class="text-[9px] text-slate-400 dark:text-slate-600 text-center py-2">—</div>
              </template>
              <template x-for="chip in eventsForDay(day)" :key="chip.show_title">
                <a :href="chip.url"
                   class="flex items-center justify-between px-1.5 py-1 rounded text-[9px] font-semibold
                          truncate cursor-pointer hover:opacity-80 transition-opacity border-l-2"
                   :class="{
                     'bg-blue-900 border-blue-500 text-blue-200':   chip.type === 'episode' && !chip.is_premiere,
                     'bg-purple-900 border-purple-500 text-purple-200': chip.is_premiere || chip.type === 'premiere',
                     'bg-red-900 border-red-500 text-red-200':     chip.type === 'finale'
                   }">
                  <span class="truncate" x-text="chip.show_title"></span>
                  <span x-show="chip.count > 1"
                        class="ml-1 flex-shrink-0 bg-white/20 rounded-full px-1 text-[8px] font-extrabold"
                        x-text="'×' + chip.count">
                  </span>
                </a>
              </template>
            </div>
          </div>
        </template>
      </div>
    </div>
    <!-- ── End week grid ──────────────────────────────────────────── -->
```

- [ ] **Step 4: Verify the page renders correctly in a browser**

Start the dev server and open `http://localhost:5001/calendar` (or the dev container at port 5004):

```bash
cd /home/scott/projects/show_notes_dev
.venv/bin/python run.py
```

Check:
- Week grid appears above the lists on a wide viewport
- Grid is hidden on narrow viewport (< 768px)
- Today's column has a blue ring
- Past days are dimmed
- ‹ / Today / › buttons change the week
- Chips navigate correctly on click

- [ ] **Step 5: Commit**

```bash
git add app/templates/calendar.html
git commit -m "feat: add desktop week grid to calendar page with Alpine.js navigation"
```

---

## Task 4: Add mobile single-day view with dot strip

Add the `md:hidden` mobile view above the desktop grid (it uses the same Alpine.js component data, so no additional JS needed).

**Files:**
- Modify: `app/templates/calendar.html`

- [ ] **Step 1: Add mobile day navigator and dot strip**

Immediately before the `<!-- ── Week Grid (desktop) -->` comment added in Task 3, insert:

```html
    <!-- ── Single Day View (mobile) ──────────────────────────────── -->
    <div class="md:hidden mb-8">

      <!-- Day navigator -->
      <div class="flex items-center justify-between mb-3">
        <button @click="prevDay()"
                class="w-10 h-10 flex items-center justify-center rounded-xl
                       bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300
                       hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors text-xl font-bold">
          ‹
        </button>

        <div class="text-center flex-1 px-2">
          <div class="text-xs font-bold text-sky-500 uppercase tracking-wider"
               x-text="mobileDay.toLocaleDateString('en-US', { weekday: 'long' })">
          </div>
          <div class="text-3xl font-extrabold text-slate-800 dark:text-slate-100 leading-none my-0.5"
               x-text="mobileDay.getDate()">
          </div>
          <div class="text-xs text-slate-500 dark:text-slate-400"
               x-text="mobileDay.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })">
          </div>
        </div>

        <button @click="nextDay()"
                class="w-10 h-10 flex items-center justify-center rounded-xl
                       bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300
                       hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors text-xl font-bold">
          ›
        </button>
      </div>

      <!-- Week dots strip -->
      <div class="flex justify-center items-center gap-2 mb-4">
        <template x-for="dot in weekDots" :key="dot.key">
          <div class="rounded-full transition-all cursor-pointer"
               :class="{
                 'w-2.5 h-2.5 bg-sky-400': dot.isToday && dot.isCurrent,
                 'w-2 h-2 bg-sky-500/60': dot.isToday && !dot.isCurrent,
                 'w-2 h-2 bg-blue-500': !dot.isToday && dot.hasEvents && dot.isCurrent,
                 'w-1.5 h-1.5 bg-blue-400/60': !dot.isToday && dot.hasEvents && !dot.isCurrent,
                 'w-1.5 h-1.5 bg-slate-600': !dot.hasEvents
               }">
          </div>
        </template>
      </div>

      <!-- Events for current day -->
      <div class="flex flex-col gap-2">
        <template x-if="mobileDayEvents.length === 0">
          <div class="bg-slate-100 dark:bg-slate-800 rounded-xl p-6 text-center">
            <p class="text-slate-500 dark:text-slate-400 text-sm">Nothing airing today</p>
            <button @click="nextDay()"
                    class="mt-2 text-xs text-sky-500 hover:underline">
              Check tomorrow →
            </button>
          </div>
        </template>
        <template x-for="chip in mobileDayEvents" :key="chip.show_title">
          <a :href="chip.url"
             class="flex items-center justify-between px-4 py-3 rounded-xl font-semibold
                    cursor-pointer hover:opacity-80 transition-opacity border-l-4"
             :class="{
               'bg-blue-900/80 border-blue-500 text-blue-100':       chip.type === 'episode' && !chip.is_premiere,
               'bg-purple-900/80 border-purple-500 text-purple-100': chip.is_premiere || chip.type === 'premiere',
               'bg-red-900/80 border-red-500 text-red-100':          chip.type === 'finale'
             }">
            <div class="min-w-0">
              <div class="text-sm font-bold truncate" x-text="chip.show_title"></div>
              <div class="text-xs opacity-70 mt-0.5"
                   x-text="chip.count > 1
                     ? chip.count + ' episodes'
                     : 'S' + String(chip.season_number).padStart(2,'0') + 'E' + String(chip.episode_number).padStart(2,'0') + (chip.episode_title ? ' · ' + chip.episode_title : '')">
              </div>
            </div>
            <svg class="w-4 h-4 flex-shrink-0 ml-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
          </a>
        </template>
      </div>
    </div>
    <!-- ── End single day view ─────────────────────────────────────── -->
```

- [ ] **Step 2: Verify mobile view in browser**

Resize browser window to < 768px (or use DevTools device mode). Check:
- Desktop grid is hidden, mobile view appears
- ‹ › step through days correctly
- Dot strip updates when stepping into a new week
- Today dot is highlighted
- Chips with multiple episodes show episode count
- Empty day shows "Nothing airing" with "Check tomorrow →" link
- `goToday()` button (from desktop) resets mobile offset too

- [ ] **Step 3: Final commit**

```bash
git add app/templates/calendar.html
git commit -m "feat: add mobile single-day calendar view with dot strip navigation"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Week grid at top, lists unchanged below | Task 3 |
| Mon–Sun, today highlighted, past dimmed | Task 3 |
| ‹ / Today / › navigation | Task 3 |
| Single chip per show per day, ×N for multiples | Task 3 (eventsForDay grouping) |
| Click single chip → episode page | Task 3 |
| Click multi chip → show page | Task 3 |
| Blue/purple/red color coding | Tasks 3 & 4 |
| Filter tabs apply to grid | Task 3 (filter check in eventsForDay) |
| Mobile: single-day view | Task 4 |
| Mobile: ‹ › day navigation | Task 4 |
| Mobile: dot strip showing busy days | Task 4 |
| Dots update when crossing week boundary | Task 4 (weekDots uses mobileDay's week) |
| Data window: 7 days back + 28 ahead | Task 1 |
| Client-side navigation, no extra requests | Tasks 2 & 3 |

All spec requirements covered. No placeholders.
