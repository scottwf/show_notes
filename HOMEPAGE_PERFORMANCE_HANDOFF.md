# Homepage Performance Handoff

Date: 2026-04-03

## Current Situation

There are two different ShowNotes instances in play.

- Public production domain:
  - `shownotes.chitekmedia.club`
  - Origin currently points to `http://172.16.1.140:5003`
- Local/dev machine used during this investigation:
  - host `dore`
  - IP `172.16.1.93`
  - separate repo/database/container from `172.16.1.140`

This caused confusion during testing because fixes applied on `172.16.1.93` did not affect the public site on `172.16.1.140`.

## Future Environment Split

Going forward, use:

- `shownotes.chitekmedia.club` for the public/production instance
- `sn.chitekmedia.club` for the dev instance

Any future deployment or testing plan should explicitly note which host and which domain is under test.

## Findings So Far

### 1. Backend homepage route is not the 1-minute bottleneck anymore

On the local/dev instance, instrumented timing for `/` showed roughly:

- total: about `1120ms`
- `tautulli_activity`: about `18ms`
- `homepage_stats`: about `480ms`
- `homepage_premieres`: about `510ms`
- `render_template`: about `90ms`

This means the Flask route is not taking `1.1 minutes`.

### 2. Direct app and public top-level request are both fast

Measured from the host:

- `http://localhost:5003/`
  - total about `0.004s`
- `https://shownotes.chitekmedia.club/`
  - total about `0.127s`

So the main HTML request is not the remaining issue.

### 3. Browser page load is still slow because of follow-up resource loading

Observed in browser:

- about `63 resources`
- about `11.8 MB transferred`
- about `1.1 min` total page load

This strongly points to a front-end/resource waterfall problem, especially image-heavy sections.

### 4. Images are not resized on import or cache warm

Current behavior:

- Sonarr/Radarr sync warms images by calling `_trigger_image_cache(...)`
- `/image_proxy/...` downloads the original image and writes it to disk
- no thumbnail generation exists in current committed code
- no Pillow/PIL resize logic exists in the committed path

Measured cached poster sizes on local/dev instance:

- count: `424`
- average size: about `474 KB`
- many posters are `1.4 MB` to `2.3 MB`

That means homepage card rows are using oversized poster assets for small UI slots.

### 5. Production and local/dev are on different versions

Evidence:

- Public site behavior differs from local
- local showed homepage instrumentation
- public site content/sections did not match local behavior
- Cloudflare origin confirms public traffic goes to `172.16.1.140:5003`

## Repo State On Local/Dev Machine

Current local repo state when this handoff was written:

- committed performance work exists at commit `886a41c`
- there are also uncommitted local changes in:
  - `app/routes/main.py`
  - `requirements.txt`
  - `tmp_fix_shownotes_permissions_and_redeploy.sh`

Those uncommitted changes include partial work for:

- switching homepage timing output to `print(...)`
- starting thumbnail-generation changes
- adding `Pillow` to `requirements.txt`

This partial work should be reviewed before any deployment.

## Already Completed Work

These were implemented on the local/dev copy:

1. Reduced homepage DB overhead:
   - exempted image routes from global `before_app_request` DB checks
   - added request/process caching for settings
   - cached homepage section payloads

2. Added a homepage query index:
   - `idx_plex_activity_user_media_grandparent`

3. Confirmed local container and DB migration path after fixing host permissions.

These changes are not the full final homepage solution, but they improved backend latency.

## Recommended Plan For The Next Coding Model

### Phase 1: Work on the actual public instance

Do not continue performance diagnosis only on `172.16.1.93`.

First, compare `172.16.1.140` against the local repo:

1. On `172.16.1.140`, collect:
   - `git rev-parse --short HEAD`
   - `git status --short --branch`
   - `docker ps --format '{{.Names}} {{.Ports}}' | grep '^shownotes '`
2. Inspect whether the public instance has:
   - homepage caching changes
   - homepage instrumentation
   - the new DB index
3. Decide whether to:
   - bring `140` up to the same baseline as local, or
   - re-implement directly on `140`

### Phase 2: Finish image optimization properly

Implement real thumbnail generation for posters.

Recommended approach:

1. Add `Pillow` as a dependency.
2. Extend `/image_proxy/<type>/<id>` to support a thumbnail variant, for example:
   - `/image_proxy/poster/<id>?variant=thumb`
3. When caching posters:
   - save full-size original poster
   - generate a thumbnail derivative for card/list views
4. Use sensible thumbnail settings, for example:
   - width around `240px`
   - JPEG quality around `70-80`
5. Store thumbnails under a separate path, for example:
   - `app/static/poster/thumbs/<id>.jpg`

Important:

- Keep full-size posters for detail pages
- Use thumbnails only for homepage/profile/list card grids

### Phase 3: Reduce first-load homepage payload

Cut initial section sizes.

Suggested first pass:

- recently watched: `8`
- season premieres: `8`
- series premieres: `8`
- recently added movies: `6`
- coming soon movies: `6`

If still slow, reduce further.

### Phase 4: Defer lower sections after first paint

If resource load is still heavy after thumbnails:

1. Render only top sections on initial HTML response
2. Load lower sections after first paint via:
   - small JSON endpoints, or
   - HTMX/fetch requests

Best candidates to defer:

- upcoming/series premieres
- recently added movies
- coming soon movies

### Phase 5: Re-test with exact metrics

Test both:

- direct origin: `http://172.16.1.140:5003/`
- public domain: `https://shownotes.chitekmedia.club/`

Capture:

1. top-level request timing
2. total page load time
3. resource count
4. total MB transferred
5. slowest 10 requests
6. largest 10 requests

Success target:

- initial document under `1s`
- total homepage load visually under a few seconds
- transferred bytes materially reduced from `11.8 MB`

## Immediate Priority Order

If another coding model continues this, the order should be:

1. verify code/version on `172.16.1.140`
2. finish thumbnail generation
3. point homepage cards to thumbnail assets
4. reduce section counts
5. re-test public domain
6. only then decide whether deferred loading is necessary

## Notes

- The local helper script `tmp_fix_shownotes_permissions_and_redeploy.sh` was created for operational convenience and is not part of the production solution.
- If container bind mounts on `172.16.1.140` have ownership issues, fix those first before trying to evaluate app behavior.
- Be explicit in all future notes about whether the target is:
  - production: `shownotes.chitekmedia.club`
  - dev: `sn.chitekmedia.club`
