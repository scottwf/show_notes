# Discover Page Tab Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Discover page's overloaded "Popular" tab into two focused tabs — Popular (shows + movies) and Trending (live watching, binge, night owl, early bird) — and rename "Upcoming Movies" to "Upcoming".

**Architecture:** Pure template change to `app/templates/discover.html`. No backend changes — all data is already fetched and passed to the template. The existing `showTab()` JS function handles tab switching by `data-tab` attribute and `${tab}-tab` element ID, so adding a new tab requires only HTML changes.

**Tech Stack:** Jinja2, Tailwind CSS, vanilla JS (existing `showTab()`)

---

### Task 1: Create feature branch

**Files:**
- No file changes

- [ ] **Step 1: Create and check out branch**

```bash
git checkout -b feature/discover-trending-tab
```

Expected: `Switched to a new branch 'feature/discover-trending-tab'`

---

### Task 2: Update the tab navigation bar

**Files:**
- Modify: `app/templates/discover.html:14-38`

The nav currently has three buttons: Popular, Recommended (conditional), Upcoming Movies (conditional on `jellyseer_url`). We need to insert a Trending button (always visible) between Popular and Recommended, and rename "Upcoming Movies" → "Upcoming".

- [ ] **Step 1: Replace the tab navigation block**

In `app/templates/discover.html`, replace lines 14–38 (the `<!-- Tab Navigation -->` block) with:

```html
    <!-- Tab Navigation -->
    <div class="flex gap-1 mb-6 border-b border-slate-200 dark:border-slate-700 overflow-x-auto scrollbar-hide">
        <button onclick="showTab('popular')"
                class="tab-button px-4 py-3 text-sm font-medium transition-colors border-b-2 border-sky-500 text-sky-600 dark:text-sky-400 whitespace-nowrap"
                data-tab="popular">
            Popular
        </button>
        <button onclick="showTab('trending')"
                class="tab-button px-4 py-3 text-sm font-medium transition-colors border-b-2 border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 whitespace-nowrap"
                data-tab="trending">
            Trending
        </button>
        {% if received_recs or community_picks %}
        <button onclick="showTab('recommended')"
                class="tab-button px-4 py-3 text-sm font-medium transition-colors border-b-2 border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 whitespace-nowrap"
                data-tab="recommended">
            Recommended
            {% set unread_count = received_recs|selectattr('is_read', 'equalto', 0)|list|length %}
            {% if unread_count > 0 %}
            <span class="ml-1 inline-flex items-center justify-center w-5 h-5 text-[10px] font-bold bg-red-500 text-white rounded-full">{{ unread_count }}</span>
            {% endif %}
        </button>
        {% endif %}
        {% if jellyseer_url %}
        <button onclick="showTab('upcoming')"
                class="tab-button px-4 py-3 text-sm font-medium transition-colors border-b-2 border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 whitespace-nowrap"
                data-tab="upcoming">
            Upcoming
        </button>
        {% endif %}
    </div>
```

- [ ] **Step 2: Verify the file saved correctly**

```bash
grep -n "Trending\|Upcoming\|tab-button" app/templates/discover.html | head -20
```

Expected output should show 4 tab buttons with "Trending" appearing between "Popular" and "Recommended", and "Upcoming" (not "Upcoming Movies").

---

### Task 3: Trim the Popular tab and add the Trending tab

**Files:**
- Modify: `app/templates/discover.html:41-289`

The Popular tab currently contains six sections. We keep only Popular Shows and Popular Movies. The other four (Watching Live, Binge Watch, Night Owl, Early Bird) move verbatim into a new Trending tab.

- [ ] **Step 1: Replace the Popular tab content block**

Find the line `<div id="popular-tab" class="tab-content space-y-10">` (currently line ~41). Replace the entire `popular-tab` div with the trimmed version below. The closing `</div>` for `popular-tab` is at the end of the `{% else %}` empty-state block (currently around line 289).

Replace the full `popular-tab` div with:

```html
    <!-- Popular Tab -->
    <div id="popular-tab" class="tab-content space-y-10">
        {% if popular_shows or popular_movies %}

            <!-- Popular Shows -->
            {% if popular_shows %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-orange-500" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M12.395 2.553a1 1 0 00-1.45-.385c-.345.23-.614.558-.822.88-.214.33-.403.713-.57 1.116-.334.804-.614 1.768-.84 2.734a31.365 31.365 0 00-.613 3.58 2.64 2.64 0 01-.945-1.067c-.328-.68-.398-1.534-.398-2.654A1 1 0 005.05 6.05 6.981 6.981 0 003 11a7 7 0 1011.95-4.95c-.592-.591-.98-.985-1.348-1.467-.363-.476-.724-1.063-1.207-2.03zM12.12 15.12A3 3 0 017 13s.879.5 2.5.5c0-1 .5-4 1.25-4.5.5 1 .786 1.293 1.371 1.879A2.99 2.99 0 0113 13a2.99 2.99 0 01-.879 2.121z"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Popular Shows</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">Shows multiple members are watching this month</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for show in popular_shows %}
                    <div class="group">
                        <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=show.tmdb_id) }}"
                                     alt="{{ show.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute top-1.5 right-1.5 bg-black/75 text-white text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1">
                                    <svg class="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
                                        <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
                                        <path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/>
                                    </svg>
                                    {{ show.play_count }}
                                </div>
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ show.member_count }} member{{ 's' if show.member_count != 1 }}</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ show.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <!-- Popular Movies -->
            {% if popular_movies %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-sky-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm3 2h6v4H7V5zm8 8v2h1v-2h-1zm-2-2H7v4h6v-4zm2 0h1V9h-1v2zm1-4V5h-1v2h1zM5 5v2H4V5h1zm-1 4h1v2H4V9zm0 4h1v2H4v-2z" clip-rule="evenodd"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Popular Movies</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">Most watched movies this month</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for movie in popular_movies %}
                    <div class="group">
                        <a href="{{ url_for('main.movie_detail', tmdb_id=movie.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=movie.tmdb_id) }}"
                                     alt="{{ movie.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute top-1.5 right-1.5 bg-black/75 text-white text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1">
                                    <svg class="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
                                        <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
                                        <path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/>
                                    </svg>
                                    {{ movie.play_count }}
                                </div>
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ movie.member_count }} member{{ 's' if movie.member_count != 1 }}</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.movie_detail', tmdb_id=movie.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ movie.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

        {% else %}
            <div class="text-center py-12">
                <svg class="w-16 h-16 mx-auto text-slate-300 dark:text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"/>
                </svg>
                <p class="text-slate-500 dark:text-slate-400">No viewing activity in the last 30 days</p>
                <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">Start watching something on Plex to see popular content here</p>
            </div>
        {% endif %}
    </div>
```

- [ ] **Step 2: Insert the Trending tab immediately after the closing `</div>` of the Popular tab**

Add this block right after the Popular tab's closing `</div>`:

```html
    <!-- Trending Tab -->
    <div id="trending-tab" class="tab-content hidden space-y-10">
        {% if watching_live or binge_shows or late_night or early_bird %}

            <!-- Watching Live -->
            {% if watching_live %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Watching Live</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">Shows members watch within 48 hours of airing</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for show in watching_live %}
                    <div class="group">
                        <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=show.tmdb_id) }}"
                                     alt="{{ show.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ show.live_member_count }} member{{ 's' if show.live_member_count != 1 }} keeping up</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ show.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <!-- Binge Watch -->
            {% if binge_shows %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-purple-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Binge Watch</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">Shows members are devouring 4+ episodes in a day</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for show in binge_shows %}
                    <div class="group">
                        <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=show.tmdb_id) }}"
                                     alt="{{ show.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ show.binger_count }} binger{{ 's' if show.binger_count != 1 }}</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ show.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <!-- Night Owl -->
            {% if late_night %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-indigo-500" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Night Owl</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">What members are watching between 10pm and 3am</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for show in late_night %}
                    <div class="group">
                        <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=show.tmdb_id) }}"
                                     alt="{{ show.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ show.play_count }} late plays</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ show.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <!-- Early Bird -->
            {% if early_bird %}
            <div>
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-5 h-5 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm-.707 10.607a1 1 0 011.414-1.414l-.707-.707a1 1 0 01-1.414 1.414l.707.707zM3 11a1 1 0 100-2H2a1 1 0 100 2h1z" clip-rule="evenodd"/>
                    </svg>
                    <div>
                        <h2 class="text-lg font-bold text-slate-800 dark:text-slate-100">Early Bird</h2>
                        <p class="text-xs text-slate-500 dark:text-slate-400">What members are watching between 5am and 10am</p>
                    </div>
                </div>
                <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-3 sm:gap-4">
                    {% for show in early_bird %}
                    <div class="group">
                        <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}" class="block">
                            <div class="relative aspect-[2/3] rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-700 shadow-sm hover:shadow-lg transition-all transform group-hover:scale-105">
                                <img src="{{ url_for('main.image_proxy', type='poster', id=show.tmdb_id) }}"
                                     alt="{{ show.title }}" class="w-full h-full object-cover" loading="lazy"
                                     onerror="this.src='/static/logos/placeholder_poster.png'">
                                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                                    <p class="text-white text-[10px]">{{ show.play_count }} morning plays</p>
                                </div>
                            </div>
                        </a>
                        <div class="mt-1.5">
                            <a href="{{ url_for('main.show_detail', tmdb_id=show.tmdb_id) }}"
                               class="text-xs font-medium text-slate-800 dark:text-slate-100 hover:text-sky-600 dark:hover:text-sky-400 line-clamp-2">
                                {{ show.title }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

        {% else %}
            <div class="text-center py-12">
                <svg class="w-16 h-16 mx-auto text-slate-300 dark:text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"/>
                </svg>
                <p class="text-slate-500 dark:text-slate-400">No trending activity in the last 30 days</p>
                <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">Live watching, binge, and time-of-day data will appear here</p>
            </div>
        {% endif %}
    </div>
```

- [ ] **Step 3: Verify structure looks correct**

```bash
grep -n "id=\"popular-tab\"\|id=\"trending-tab\"\|id=\"recommended-tab\"\|id=\"upcoming-tab\"" app/templates/discover.html
```

Expected: four lines, one for each tab div, in order: popular, trending, recommended, upcoming.

- [ ] **Step 4: Commit**

```bash
git add app/templates/discover.html
git commit -m "feat: split Discover Popular tab into Popular and Trending tabs"
```

---

### Task 4: Verify in the browser

**Files:** None — read-only verification

- [ ] **Step 1: Start the dev server**

```bash
python3 run.py
```

- [ ] **Step 2: Open http://localhost:5001/discover and verify:**
  - Four tabs visible in order: Popular → Trending → Recommended (if data) → Upcoming (if configured)
  - Popular tab shows only Popular Shows and Popular Movies sections
  - Clicking Trending tab shows Watching Live, Binge Watch, Night Owl, Early Bird sections
  - Tab active-state (sky blue underline) switches correctly between tabs
  - Recommended and Upcoming tabs still function as before

- [ ] **Step 3: If everything looks correct, merge to main**

```bash
git checkout main
git merge feature/discover-trending-tab
```
