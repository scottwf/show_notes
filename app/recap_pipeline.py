"""
Subtitle-First Season Recap Pipeline

Generates episode and season summaries using:
  1. Episode subtitles from the local DB (primary evidence)
  2. Episode descriptions from Sonarr (guardrails)
  3. Cast lists from show_cast (prevents character hallucination)

Supports:
  - Spoiler-aware cutoffs (episode-level)
  - Confidence-flagged extractions (High / Medium / Low)
  - Caching keyed on show/season/cutoff/model/prompt version
  - Optional OpenAI polish step (prose only, no new facts)
  - Rubric-based scoring to decide whether OpenAI polish is warranted

Core pipeline steps
-------------------
  1. Fetch subtitle lines from `subtitles` table
  2. Clean lines (strip sound cues, normalise whitespace)
  3. Chunk by approximate wall-clock duration (~10–15 min per chunk)
  4. Per-chunk extraction via local Ollama model → JSON with confidence flags
  5. Episode synthesis: merge chunk JSON into a narrative episode summary
  6. Season synthesis: combine episode summaries into a season recap
  7. (Optional) Score for OpenAI upgrade; if warranted, polish with OpenAI

Entry points
------------
  generate_episode_recap(tmdb_id, season_number, episode_number, ...)
  generate_season_recap(tmdb_id, season_number, ...)
  get_episode_recap(...)   – retrieve cached result
  get_season_recap(...)    – retrieve cached result
"""

import json
import re
import time
import logging
from typing import Optional

from flask import current_app
from .database import get_db, get_setting

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_VERSION = "1"
DEFAULT_LOCAL_MODEL = "gpt-oss:20b"
CHUNK_DURATION_SECONDS = 600   # ~10 min of dialogue per chunk
LOW_CONFIDENCE_RE = re.compile(
    r"\[(?:music|sound|applause|laughter|sighs?|gasps?|groans?|crying|"
    r"indistinct|inaudible|door|phone|knock|bell|whistle|noise|sfx)[^\]]*\]",
    re.IGNORECASE,
)
SPEAKER_STRIP_RE = re.compile(r"^[\w\s\-\[\]\(\)]{1,30}:\s+")


# ─────────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_time_to_seconds(time_str: str) -> float:
    """Convert SRT/VTT timestamp 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' to seconds."""
    try:
        time_str = time_str.replace(",", ".")
        parts = time_str.split(":")
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + s
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 – Subtitle cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _clean_line(line: str) -> Optional[str]:
    """
    Clean a single subtitle line.

    Returns None if the line contains only a sound-effect cue and should be
    dropped entirely; otherwise returns the cleaned string.
    """
    # Drop lines that are purely sound cues
    stripped = LOW_CONFIDENCE_RE.sub("", line).strip()
    if not stripped:
        return None
    # Remove any residual HTML tags (e.g. <i>, <b>)
    stripped = re.sub(r"<[^>]+>", "", stripped).strip()
    # Normalise internal whitespace
    stripped = " ".join(stripped.split())
    return stripped if stripped else None


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 – Chunking
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_subtitles(rows, chunk_duration: int = CHUNK_DURATION_SECONDS):
    """
    Group subtitle rows into time-based chunks.

    Args:
        rows: iterable of sqlite3.Row with (start_time, end_time, speaker, line)
        chunk_duration: target seconds per chunk (default ~10 min)

    Returns:
        list of lists, each inner list is a sequence of cleaned text lines
    """
    chunks = []
    current_chunk = []
    chunk_start = None

    for row in rows:
        clean = _clean_line(row["line"])
        if not clean:
            continue

        ts = _parse_time_to_seconds(row["start_time"])
        if chunk_start is None:
            chunk_start = ts

        if ts - chunk_start >= chunk_duration and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            chunk_start = ts

        # Optionally prefix with speaker name
        speaker = row["speaker"]
        text = f"{speaker}: {clean}" if speaker else clean
        current_chunk.append(text)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 – Chunk-level extraction prompt
# ─────────────────────────────────────────────────────────────────────────────

_CHUNK_EXTRACTION_PROMPT = """\
You are an assistant that extracts factual information from TV episode dialogue.
Your only source of truth is the transcript excerpt below. Do NOT invent facts.

Show: {show_title}
Season {season_number}, Episode {episode_number}: "{episode_title}"
Episode description: {episode_overview}
Known cast for this episode: {cast_list}

Transcript excerpt (approximately {chunk_index} of {total_chunks}):
---
{transcript}
---

Extract the following as JSON with this exact schema:
{{
  "events": [
    {{"description": "...", "confidence": "high|medium|low"}}
  ],
  "character_actions": [
    {{"character": "...", "action": "...", "confidence": "high|medium|low"}}
  ],
  "relationship_changes": [
    {{"characters": "...", "change": "...", "confidence": "high|medium|low"}}
  ]
}}

Confidence guide:
  high   – clearly stated in the dialogue
  medium – implied or strongly suggested
  low    – possible but uncertain; only one mention or indirect

Only use character names that appear in the known cast list above.
Output raw JSON only – no prose, no markdown fences.
"""


def _build_chunk_extraction_prompt(
    chunk_lines,
    episode_info: dict,
    cast_names: list,
    chunk_index: int,
    total_chunks: int,
) -> str:
    return _CHUNK_EXTRACTION_PROMPT.format(
        show_title=episode_info.get("show_title", "Unknown"),
        season_number=episode_info["season_number"],
        episode_number=episode_info["episode_number"],
        episode_title=episode_info.get("title", ""),
        episode_overview=episode_info.get("overview", "No description available."),
        cast_list=", ".join(cast_names) if cast_names else "Not available",
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        transcript="\n".join(chunk_lines),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 – Episode synthesis prompt
# ─────────────────────────────────────────────────────────────────────────────

_EPISODE_SYNTHESIS_PROMPT = """\
You are writing an accurate episode recap for a TV show.
Use ONLY the extracted facts below — do not add new information.

Show: {show_title}
Season {season_number}, Episode {episode_number}: "{episode_title}"
Known cast: {cast_list}

Extracted facts (JSON):
{facts_json}

Write a cohesive episode recap (150–250 words) that:
- Covers all high-confidence events first
- Includes medium-confidence events with appropriate hedging ("appears to", "seems to")
- Omits or footnotes low-confidence items with "(unconfirmed)"
- Does NOT introduce characters not in the known cast list
- Uses past tense, narrative style

Output the recap text only – no headers, no JSON, no markdown.
"""


def _build_episode_synthesis_prompt(
    chunk_results: list,
    episode_info: dict,
    cast_names: list,
) -> str:
    # Flatten all chunk facts into a single JSON array for clarity
    merged = {"events": [], "character_actions": [], "relationship_changes": []}
    for chunk in chunk_results:
        for key in merged:
            merged[key].extend(chunk.get(key, []))

    return _EPISODE_SYNTHESIS_PROMPT.format(
        show_title=episode_info.get("show_title", "Unknown"),
        season_number=episode_info["season_number"],
        episode_number=episode_info["episode_number"],
        episode_title=episode_info.get("title", ""),
        cast_list=", ".join(cast_names) if cast_names else "Not available",
        facts_json=json.dumps(merged, indent=2),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 – Season recap synthesis prompt
# ─────────────────────────────────────────────────────────────────────────────

_SEASON_RECAP_PROMPT = """\
You are a TV critic writing a comprehensive season recap.
Use ONLY the episode summaries provided below — do not add new information.

Show: {show_title}
Season: {season_number}
Show overview: {show_overview}
Main cast this season: {cast_list}

Episode summaries:
{episode_summaries}

Write a season recap (400–600 words) covering:
## Season Premise
One paragraph overview of the season's central conflict.

## Major Arcs
Key story arcs and how they developed.

## Key Turning Points
The most significant moments that changed the course of the season.

## Character Trajectories
How the main characters evolved over the season.

## Unresolved Threads
Open questions or storylines entering the next season.

Guidelines:
- Write as a narrative recap, not episode-by-episode
- Spoilers are appropriate — this is a recap for viewers who watched the season
- Do NOT introduce characters not present in the episode summaries or cast list
- Use markdown headers as shown above
"""


def _build_season_recap_prompt(
    episode_summaries: list,
    show_info: dict,
    cast_names: list,
) -> str:
    ep_text = "\n\n".join(
        f"Episode {s['episode_number']}: {s['summary']}" for s in episode_summaries
    )
    return _SEASON_RECAP_PROMPT.format(
        show_title=show_info.get("title", "Unknown"),
        season_number=show_info["season_number"],
        show_overview=show_info.get("overview", "N/A"),
        cast_list=", ".join(cast_names) if cast_names else "Not available",
        episode_summaries=ep_text,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Optional OpenAI polish
# ─────────────────────────────────────────────────────────────────────────────

_POLISH_PROMPT = """\
You are a professional TV recap editor.
Improve the clarity and narrative flow of the recap below.
You MUST NOT add new facts, characters, or events.
You MUST NOT remove or contradict any information from the source recap.

Source recap:
{source_text}

Rewrite the recap with improved prose and flow, preserving all section headers
and every factual claim from the source. Keep the same approximate length.
"""


def score_openai_upgrade(
    season_recap_text: str,
    episode_summaries: list,
    user_importance: int = 2,
    freshness_risk: int = 1,
) -> int:
    """
    Score a season recap on the 0–10 rubric to decide whether OpenAI polish
    is warranted and which tier to use.

    Args:
        season_recap_text: raw season recap from local model
        episode_summaries: list of {'episode_number', 'summary', 'chunks'} dicts
        user_importance: 0–3 (default 2)
        freshness_risk: 0–2 (default 1 = moderate)

    Returns:
        integer score 0–10
    """
    # Narrative complexity: based on number of episodes in the season
    ep_count = len(episode_summaries)
    if ep_count >= 20:
        narrative_complexity = 3
    elif ep_count >= 10:
        narrative_complexity = 2
    elif ep_count >= 5:
        narrative_complexity = 1
    else:
        narrative_complexity = 0

    # Density of low-confidence flags in the recap text
    low_conf_count = season_recap_text.lower().count("(unconfirmed)")
    if low_conf_count >= 5:
        low_conf_density = 2
    elif low_conf_count >= 2:
        low_conf_density = 1
    else:
        low_conf_density = 0

    total = user_importance + narrative_complexity + freshness_risk + low_conf_density
    return min(total, 10)


def _select_openai_model(score: int) -> Optional[str]:
    """Map rubric score to OpenAI model tier. Returns None if local only."""
    if score <= 3:
        return None
    elif score <= 6:
        return "gpt-4o-mini"
    else:
        return "gpt-4o"


def _polish_with_openai(source_text: str, openai_model: str) -> tuple:
    """
    Polish season recap prose using OpenAI.

    Returns:
        tuple: (polished_text or None, error_message or None, cost_usd or 0)
    """
    from .llm_services import get_llm_response

    prompt = _POLISH_PROMPT.format(source_text=source_text)
    polished, error = get_llm_response(prompt, llm_model_name=openai_model, provider="openai")
    if error:
        return None, error, 0.0

    # Estimate cost (OpenAI charges vary; approximate)
    chars = len(prompt) + len(polished or "")
    tokens_approx = chars // 4
    if openai_model == "gpt-4o-mini":
        cost = tokens_approx * 0.00000015
    else:
        cost = tokens_approx * 0.000005
    return polished, None, cost


# ─────────────────────────────────────────────────────────────────────────────
# Cache key helper
# ─────────────────────────────────────────────────────────────────────────────

def _episode_cache_key(
    tmdb_id: int,
    season_number: int,
    episode_number: int,
    spoiler_cutoff: Optional[int],
    local_model: str,
    prompt_version: str,
) -> dict:
    return {
        "show_tmdb_id": tmdb_id,
        "season_number": season_number,
        "episode_number": episode_number,
        "spoiler_cutoff_episode": spoiler_cutoff if spoiler_cutoff is not None else 0,
        "local_model": local_model,
        "prompt_version": prompt_version,
    }


def _season_cache_key(
    tmdb_id: int,
    season_number: int,
    spoiler_cutoff: Optional[int],
    local_model: str,
    prompt_version: str,
    openai_model_version: Optional[str],
) -> dict:
    return {
        "show_tmdb_id": tmdb_id,
        "season_number": season_number,
        "spoiler_cutoff_episode": spoiler_cutoff if spoiler_cutoff is not None else 0,
        "local_model": local_model,
        "prompt_version": prompt_version,
        "openai_model_version": openai_model_version or "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_show_info(db, tmdb_id: int) -> Optional[dict]:
    row = db.execute(
        "SELECT title, overview FROM sonarr_shows WHERE tmdb_id = ?", (tmdb_id,)
    ).fetchone()
    return dict(row) if row else None


def _get_episode_info(db, tmdb_id: int, season_number: int, episode_number: int) -> Optional[dict]:
    row = db.execute("""
        SELECT e.title, e.overview, e.episode_number, ss.season_number
        FROM sonarr_episodes e
        JOIN sonarr_seasons ss ON ss.id = e.season_id
        JOIN sonarr_shows s ON s.id = ss.show_id
        WHERE s.tmdb_id = ? AND ss.season_number = ? AND e.episode_number = ?
    """, (tmdb_id, season_number, episode_number)).fetchone()
    return dict(row) if row else None


def _get_cast_names(db, tmdb_id: int) -> list:
    rows = db.execute("""
        SELECT DISTINCT character_name
        FROM show_cast
        JOIN sonarr_shows ON sonarr_shows.id = show_cast.show_id
        WHERE sonarr_shows.tmdb_id = ?
            AND character_name IS NOT NULL
            AND character_name != ''
        ORDER BY cast_order
        LIMIT 50
    """, (tmdb_id,)).fetchall()
    return [r["character_name"] for r in rows]


def _get_subtitle_rows(
    db, tmdb_id: int, season_number: int, episode_number: int
):
    return db.execute("""
        SELECT start_time, end_time, speaker, line
        FROM subtitles
        WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?
        ORDER BY start_time
    """, (tmdb_id, season_number, episode_number)).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# LLM call helper with JSON parsing
# ─────────────────────────────────────────────────────────────────────────────

def _call_local_model(prompt: str, model: str) -> tuple:
    """
    Call the local Ollama model.

    Returns:
        tuple: (response_text or None, error_message or None)
    """
    from .llm_services import get_llm_response
    return get_llm_response(prompt, llm_model_name=model, provider="ollama")


def _parse_json_response(text: str) -> Optional[dict]:
    """Extract and parse JSON from a model response, handling markdown fences."""
    if not text:
        return None
    # Strip optional markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # Try to extract first JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_episode_recap(
    tmdb_id: int,
    season_number: int,
    episode_number: int,
    spoiler_cutoff: Optional[int] = None,
    local_model: str = DEFAULT_LOCAL_MODEL,
    prompt_version: str = PROMPT_VERSION,
    force: bool = False,
) -> tuple:
    """
    Generate (or return cached) a subtitle-backed episode summary.

    Args:
        tmdb_id: show TMDB ID
        season_number: season number
        episode_number: episode number
        spoiler_cutoff: if set, only include this episode if episode_number <=
                        spoiler_cutoff (otherwise returns early)
        local_model: Ollama model name
        prompt_version: bump this when prompts change to invalidate cache
        force: regenerate even if a cached result exists

    Returns:
        tuple: (summary_text or None, error_message or None)
    """
    db = get_db()
    logger = current_app.logger

    # Spoiler guard
    if spoiler_cutoff is not None and episode_number > spoiler_cutoff:
        return None, f"Episode {episode_number} is beyond spoiler cutoff {spoiler_cutoff}"

    key = _episode_cache_key(tmdb_id, season_number, episode_number, spoiler_cutoff, local_model, prompt_version)

    # Check cache
    if not force:
        cached = db.execute("""
            SELECT summary_text, status, error_message FROM episode_recaps
            WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?
              AND spoiler_cutoff_episode = ? AND local_model = ? AND prompt_version = ?
              AND status = 'completed'
        """, (
            key["show_tmdb_id"], key["season_number"], key["episode_number"],
            key["spoiler_cutoff_episode"], key["local_model"], key["prompt_version"],
        )).fetchone()
        if cached:
            logger.debug(f"Episode recap cache hit: tmdb={tmdb_id} S{season_number}E{episode_number}")
            return cached["summary_text"], None

    # Gather data
    show_info = _get_show_info(db, tmdb_id)
    if not show_info:
        return None, f"Show not found for tmdb_id={tmdb_id}"

    ep_info = _get_episode_info(db, tmdb_id, season_number, episode_number)
    if not ep_info:
        return None, f"Episode not found: tmdb={tmdb_id} S{season_number}E{episode_number}"
    ep_info["show_title"] = show_info["title"]

    subtitle_rows = _get_subtitle_rows(db, tmdb_id, season_number, episode_number)
    cast_names = _get_cast_names(db, tmdb_id)

    if not subtitle_rows:
        return None, f"No subtitles found for tmdb={tmdb_id} S{season_number}E{episode_number}"

    # Mark as generating
    db.execute("""
        INSERT INTO episode_recaps
            (show_tmdb_id, season_number, episode_number, spoiler_cutoff_episode,
             local_model, prompt_version, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'generating', CURRENT_TIMESTAMP)
        ON CONFLICT(show_tmdb_id, season_number, episode_number,
                    spoiler_cutoff_episode, local_model, prompt_version)
        DO UPDATE SET status='generating', updated_at=CURRENT_TIMESTAMP
    """, (
        key["show_tmdb_id"], key["season_number"], key["episode_number"],
        key["spoiler_cutoff_episode"], key["local_model"], key["prompt_version"],
    ))
    db.commit()

    t_start = time.perf_counter()

    # Step 2: chunk
    chunks = _chunk_subtitles(subtitle_rows)
    logger.info(
        f"Episode recap: tmdb={tmdb_id} S{season_number}E{episode_number} "
        f"— {len(subtitle_rows)} subtitle lines → {len(chunks)} chunks"
    )

    # Step 3: per-chunk extraction
    chunk_results = []
    for i, chunk_lines in enumerate(chunks, start=1):
        prompt = _build_chunk_extraction_prompt(
            chunk_lines, ep_info, cast_names, i, len(chunks)
        )
        raw, err = _call_local_model(prompt, local_model)
        if err:
            logger.warning(f"Chunk {i}/{len(chunks)} extraction failed: {err}")
            continue
        parsed = _parse_json_response(raw)
        if parsed:
            chunk_results.append(parsed)
        else:
            logger.warning(f"Could not parse JSON from chunk {i} response")

    if not chunk_results:
        error = "All chunk extractions failed or produced no parseable output"
        _mark_episode_recap_failed(db, key, error)
        return None, error

    # Step 4: episode synthesis
    synth_prompt = _build_episode_synthesis_prompt(chunk_results, ep_info, cast_names)
    summary_text, err = _call_local_model(synth_prompt, local_model)
    if err:
        _mark_episode_recap_failed(db, key, err)
        return None, err

    runtime = time.perf_counter() - t_start

    # Persist
    chunks_json = json.dumps(chunk_results)
    db.execute("""
        UPDATE episode_recaps SET
            summary_text = ?, raw_chunks_json = ?, status = 'completed',
            runtime_seconds = ?, error_message = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?
          AND spoiler_cutoff_episode = ? AND local_model = ? AND prompt_version = ?
    """, (
        summary_text, chunks_json, round(runtime, 2),
        key["show_tmdb_id"], key["season_number"], key["episode_number"],
        key["spoiler_cutoff_episode"], key["local_model"], key["prompt_version"],
    ))
    db.commit()

    logger.info(
        f"Episode recap completed: tmdb={tmdb_id} S{season_number}E{episode_number} "
        f"model={local_model} runtime={runtime:.1f}s"
    )
    return summary_text, None


def _mark_episode_recap_failed(db, key: dict, error: str):
    db.execute("""
        UPDATE episode_recaps SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP
        WHERE show_tmdb_id=? AND season_number=? AND episode_number=?
          AND spoiler_cutoff_episode=? AND local_model=? AND prompt_version=?
    """, (
        error,
        key["show_tmdb_id"], key["season_number"], key["episode_number"],
        key["spoiler_cutoff_episode"], key["local_model"], key["prompt_version"],
    ))
    db.commit()


def generate_season_recap(
    tmdb_id: int,
    season_number: int,
    spoiler_cutoff: Optional[int] = None,
    local_model: str = DEFAULT_LOCAL_MODEL,
    prompt_version: str = PROMPT_VERSION,
    openai_polish: bool = False,
    force: bool = False,
    user_importance: int = 2,
    freshness_risk: int = 1,
) -> tuple:
    """
    Generate (or return cached) a subtitle-backed season recap.

    This runs generate_episode_recap for every eligible episode, then
    synthesises a season-level narrative.  Optionally scores the result on
    the 0-10 rubric and polishes it with OpenAI.

    Args:
        tmdb_id: show TMDB ID
        season_number: target season
        spoiler_cutoff: highest episode number to include (None = all)
        local_model: Ollama model name
        prompt_version: cache invalidation key
        openai_polish: if True, always attempt OpenAI polish (ignores score)
        force: regenerate even if cached
        user_importance: rubric score component 0-3
        freshness_risk: rubric score component 0-2

    Returns:
        tuple: (recap_text or None, error_message or None)
    """
    db = get_db()
    logger = current_app.logger

    cutoff_val = spoiler_cutoff if spoiler_cutoff is not None else 0

    # Check cache.
    # - no polish requested  → look for any completed row with openai_model_version = ''
    # - polish requested      → look for a completed row that has polished text
    if not force:
        if openai_polish:
            cached = db.execute("""
                SELECT recap_text, openai_polished_text FROM season_recaps
                WHERE show_tmdb_id = ? AND season_number = ? AND spoiler_cutoff_episode = ?
                  AND local_model = ? AND prompt_version = ?
                  AND status = 'completed'
                  AND openai_polished_text IS NOT NULL AND openai_polished_text != ''
                ORDER BY updated_at DESC LIMIT 1
            """, (tmdb_id, season_number, cutoff_val, local_model, prompt_version)).fetchone()
        else:
            cached = db.execute("""
                SELECT recap_text, openai_polished_text FROM season_recaps
                WHERE show_tmdb_id = ? AND season_number = ? AND spoiler_cutoff_episode = ?
                  AND local_model = ? AND prompt_version = ? AND openai_model_version = ''
                  AND status = 'completed'
                ORDER BY updated_at DESC LIMIT 1
            """, (tmdb_id, season_number, cutoff_val, local_model, prompt_version)).fetchone()

        if cached:
            logger.debug(f"Season recap cache hit: tmdb={tmdb_id} S{season_number}")
            final = cached["openai_polished_text"] or cached["recap_text"]
            return final, None

    # openai_model_version is "" until we know which model will be used
    openai_model_version = ""

    key = _season_cache_key(
        tmdb_id, season_number, spoiler_cutoff, local_model, prompt_version, openai_model_version
    )

    # Gather show data
    show_info = _get_show_info(db, tmdb_id)
    if not show_info:
        return None, f"Show not found for tmdb_id={tmdb_id}"
    show_info["season_number"] = season_number

    # Get list of episodes for this season
    episodes = db.execute("""
        SELECT e.episode_number, e.title, e.overview
        FROM sonarr_episodes e
        JOIN sonarr_seasons ss ON ss.id = e.season_id
        JOIN sonarr_shows s ON s.id = ss.show_id
        WHERE s.tmdb_id = ? AND ss.season_number = ?
          AND e.episode_number > 0
        ORDER BY e.episode_number
    """, (tmdb_id, season_number)).fetchall()

    if not episodes:
        return None, f"No episodes found for tmdb={tmdb_id} season={season_number}"

    if spoiler_cutoff is not None:
        episodes = [e for e in episodes if e["episode_number"] <= spoiler_cutoff]

    if not episodes:
        return None, "No episodes within spoiler cutoff"

    cast_names = _get_cast_names(db, tmdb_id)

    # Mark generating
    db.execute("""
        INSERT INTO season_recaps
            (show_tmdb_id, season_number, spoiler_cutoff_episode,
             local_model, prompt_version, openai_model_version, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'generating', CURRENT_TIMESTAMP)
        ON CONFLICT(show_tmdb_id, season_number, spoiler_cutoff_episode,
                    local_model, prompt_version, openai_model_version)
        DO UPDATE SET status='generating', updated_at=CURRENT_TIMESTAMP
    """, (
        key["show_tmdb_id"], key["season_number"], key["spoiler_cutoff_episode"],
        key["local_model"], key["prompt_version"], key["openai_model_version"],
    ))
    db.commit()

    t_start = time.perf_counter()

    # Step 3-4: generate individual episode recaps
    episode_summaries = []
    first_error = None
    for ep in episodes:
        ep_num = ep["episode_number"]
        summary, err = generate_episode_recap(
            tmdb_id, season_number, ep_num,
            spoiler_cutoff=spoiler_cutoff,
            local_model=local_model,
            prompt_version=prompt_version,
            force=force,
        )
        if summary:
            episode_summaries.append({"episode_number": ep_num, "summary": summary})
        else:
            logger.warning(f"Episode recap failed for E{ep_num}: {err}")
            if not first_error:
                first_error = err

    if not episode_summaries:
        error = first_error or "No episode recaps could be generated"
        _mark_season_recap_failed(db, key, error)
        return None, error

    # Step 5: season synthesis
    season_prompt = _build_season_recap_prompt(episode_summaries, show_info, cast_names)
    recap_text, err = _call_local_model(season_prompt, local_model)
    if err:
        _mark_season_recap_failed(db, key, err)
        return None, err

    # Optional OpenAI polish
    polished_text = None
    openai_cost = 0.0
    openai_model_used = ""

    if openai_polish:
        score = score_openai_upgrade(recap_text, episode_summaries, user_importance, freshness_risk)
        openai_tier = _select_openai_model(score)
        logger.info(f"OpenAI upgrade score: {score}/10 → model: {openai_tier or 'local only'}")
        if openai_tier:
            polished, polish_err, openai_cost = _polish_with_openai(recap_text, openai_tier)
            if polish_err:
                logger.warning(f"OpenAI polish failed: {polish_err}")
            else:
                polished_text = polished
                openai_model_used = openai_tier

    runtime = time.perf_counter() - t_start

    # Persist
    db.execute("""
        UPDATE season_recaps SET
            recap_text = ?, openai_polished_text = ?, openai_model_version = ?,
            openai_cost_usd = ?, runtime_seconds = ?, status = 'completed',
            error_message = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE show_tmdb_id = ? AND season_number = ? AND spoiler_cutoff_episode = ?
          AND local_model = ? AND prompt_version = ? AND openai_model_version = ?
    """, (
        recap_text, polished_text, openai_model_used,
        openai_cost, round(runtime, 2),
        key["show_tmdb_id"], key["season_number"], key["spoiler_cutoff_episode"],
        key["local_model"], key["prompt_version"], key["openai_model_version"],
    ))
    db.commit()

    logger.info(
        f"Season recap completed: tmdb={tmdb_id} S{season_number} "
        f"model={local_model} runtime={runtime:.1f}s openai_cost=${openai_cost:.4f}"
    )
    final_text = polished_text or recap_text
    return final_text, None


def _mark_season_recap_failed(db, key: dict, error: str):
    db.execute("""
        UPDATE season_recaps SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP
        WHERE show_tmdb_id=? AND season_number=? AND spoiler_cutoff_episode=?
          AND local_model=? AND prompt_version=? AND openai_model_version=?
    """, (
        error,
        key["show_tmdb_id"], key["season_number"], key["spoiler_cutoff_episode"],
        key["local_model"], key["prompt_version"], key["openai_model_version"],
    ))
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval helpers (for display)
# ─────────────────────────────────────────────────────────────────────────────

def get_episode_recap(
    tmdb_id: int,
    season_number: int,
    episode_number: int,
    spoiler_cutoff: Optional[int] = None,
    local_model: str = DEFAULT_LOCAL_MODEL,
    prompt_version: str = PROMPT_VERSION,
) -> Optional[dict]:
    """Return the most recently completed episode recap, or None."""
    db = get_db()
    cutoff = spoiler_cutoff if spoiler_cutoff is not None else 0
    row = db.execute("""
        SELECT summary_text, local_model, runtime_seconds, updated_at
        FROM episode_recaps
        WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ?
          AND spoiler_cutoff_episode = ? AND local_model = ? AND prompt_version = ?
          AND status = 'completed'
        ORDER BY updated_at DESC LIMIT 1
    """, (tmdb_id, season_number, episode_number, cutoff, local_model, prompt_version)).fetchone()
    return dict(row) if row else None


def get_season_recap(
    tmdb_id: int,
    season_number: int,
    spoiler_cutoff: Optional[int] = None,
    local_model: str = DEFAULT_LOCAL_MODEL,
    prompt_version: str = PROMPT_VERSION,
) -> Optional[dict]:
    """Return the most recently completed season recap (polished if available), or None."""
    db = get_db()
    cutoff = spoiler_cutoff if spoiler_cutoff is not None else 0
    row = db.execute("""
        SELECT recap_text, openai_polished_text, openai_model_version,
               local_model, runtime_seconds, openai_cost_usd, updated_at
        FROM season_recaps
        WHERE show_tmdb_id = ? AND season_number = ? AND spoiler_cutoff_episode = ?
          AND local_model = ? AND prompt_version = ?
          AND status = 'completed'
        ORDER BY updated_at DESC LIMIT 1
    """, (tmdb_id, season_number, cutoff, local_model, prompt_version)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["display_text"] = result["openai_polished_text"] or result["recap_text"]
    return result


def get_recap_pipeline_status(tmdb_id: Optional[int] = None) -> dict:
    """
    Return queue/status counts for the recap pipeline admin view.

    Args:
        tmdb_id: if supplied, scope to one show; otherwise global

    Returns:
        dict with episode/season counts by status
    """
    db = get_db()
    where = "WHERE show_tmdb_id = ?" if tmdb_id else ""
    params = (tmdb_id,) if tmdb_id else ()

    def _counts(table):
        rows = db.execute(
            f"SELECT status, COUNT(*) as cnt FROM {table} {where} GROUP BY status",
            params,
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    ep_counts = _counts("episode_recaps")
    sn_counts = _counts("season_recaps")

    return {
        "episode_recaps": ep_counts,
        "season_recaps": sn_counts,
        "episode_total": sum(ep_counts.values()),
        "season_total": sum(sn_counts.values()),
    }
