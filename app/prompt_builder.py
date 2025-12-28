from typing import Dict, Any, Optional
from app.episode_data_services import episode_data_manager

def build_quote_prompt(character, show):
    return f"""You are an expert on the show {show}. Provide 2 to 3 notable quotes by the character {character}.

Return only the following markdown format:

## Quotes
quote_1: "First quote here."
quote_2: "Second quote here."
quote_3: "Third quote here."
"""


def build_relationships_prompt(character, show, season=None, episode=None):
    limit_text = f" Limit the analysis to events up to Season {season}, Episode {episode}." if season and episode else ""
    return f"""Provide only the significant relationships for the character {character} from the show {show}.{limit_text}

Use this markdown format:

## Relationships
relationship_1:
  name: "Name"
  role: "Role"
  description: "1–2 sentence description"
relationship_2:
  name: "Name"
  role: "Role"
  description: "1–2 sentence description"
"""

def build_character_prompt(character, show, season=None, episode=None, options=None, show_context=None, episode_context=None, character_context=None):
    """
    Build a character summary prompt with simplified options.
    
    options: {
        'include_relationships': True,
        'include_motivations': True,
        'include_quote': True,
        'tone': 'tv_expert'
    }
    """
    if options is None:
        options = {}

    limit_text = f" Limit the analysis to events up to Season {season}, Episode {episode}." if season and episode else ""

    # Build context information
    context_parts = []
    if show_context and show_context.get('overview'):
        context_parts.append(f"Show context: {show_context['overview']}")
    if character_context and character_context.get('actor_name'):
        context_parts.append(f"Character: {character} is played by {character_context['actor_name']}")
    if character_context and character_context.get('other_characters'):
        other_chars = ', '.join(character_context['other_characters'][:5])
        context_parts.append(f"Other characters in this episode: {other_chars}")
    if episode_context and episode_context.get('title'):
        context_parts.append(f"Episode {episode}: '{episode_context['title']}'")
    if episode_context and episode_context.get('overview'):
        context_parts.append(f"Episode context: {episode_context['overview']}")
    
    context_text = ""
    if context_parts:
        context_text = f"\n\nContext for accuracy:\n" + "\n".join(f"- {part}" for part in context_parts)

    # Simplified base prompt
    base = f"Provide a detailed character summary for {character} from {show}.{limit_text}{context_text}\n\nWrite in the voice of an expert TV analyst. Use markdown with ## headers. Be specific and detailed - avoid generic descriptions that could apply to any character.\n\nReturn only the markdown structure below. Do not include any explanations, preamble, or commentary."

    extras = []

    if options.get("include_relationships", True):
        extras.append("""
## Significant Relationships
relationship_1:
  name: "Name"
  role: "Role"
  description: "1–2 sentence description"
relationship_2:
  name: "Name"
  role: "Role"
  description: "1–2 sentence description"
""")

    if options.get("include_motivations", True):
        extras.append("""
## Primary Motivations & Inner Conflicts
description: 1 paragraph describing what drives the character and any emotional or psychological tension.
""")

    if options.get("include_quote", True):
        extras.append("""
## Notable Quote
quote: "Insert the quote here."
""")

    extras.append("""
## Character Background & Role
description: 1 paragraph describing this character's specific role, background, profession, or position in the show.
""")

    extras.append("""
## Personality & Traits
traits:
  - "Specific trait that defines this character"
  - "Another distinctive characteristic"
  - "A third defining quality"
""")

    extras.append("""
## Key Events
events:
  - "Major turning point 1"
  - "Major turning point 2"
  - "Major turning point 3"
""")

    extras.append("""
## Importance to the Story
description: Explain in 1 paragraph how this character impacts the show's plot or themes.
""")

    return base + "\n\n" + "\n\n".join(extras)

def build_grounded_character_prompt(character: str, show: str, tmdb_id: int, season: int, episode: int) -> str:
    """Build a character prompt with grounded episode data, returning standard Markdown format"""
    
    # Get show context with episode data
    show_context = episode_data_manager.get_show_context_for_prompt(tmdb_id, season, episode)
    
    # Build the grounded prompt
    prompt = f"""You are an expert TV analyst. Create a comprehensive character summary for {character} from {show}.

IMPORTANT: Use ONLY the provided episode data below. Do not make up or invent any details not present in the source material. If a specific detail is not in the data, do not invent it.

## Show Context
**Show:** {show_context.get('show_title', show)}
**Summary:** {show_context.get('show_summary', 'No show summary available')}

## Episode Data (Up to Season {season}, Episode {episode})
"""
    
    # Add episode summaries
    episodes = show_context.get('episodes', [])
    if episodes:
        prompt += "\n**Episodes:**\n"
        for ep in episodes[:20]:  # Limit to first 20 episodes to avoid token limits
            prompt += f"- Season {ep['season']}, Episode {ep['episode']}: {ep['title']}\n"
            if ep['summary']:
                prompt += f"  Summary: {ep['summary'][:400]}...\n" # Increased summary length for better context
    else:
        prompt += "\n**No episode data available for this cutoff.**\n"
    
    # Add season summaries
    seasons = show_context.get('seasons', [])
    if seasons:
        prompt += "\n**Season Summaries:**\n"
        for season_data in seasons:
            prompt += f"- {season_data['title']}: {season_data['summary'][:300]}...\n"
    
    prompt += f"""

## Instructions
Based on the episode data above, create a character summary for {character}.
Return only the following markdown format. Do not include any explanations or preamble.

## Significant Relationships
relationship_1: name: "Name" role: "Role" description: "Description based on provided episodes"
relationship_2: name: "Name" role: "Role" description: "Description based on provided episodes"

## Primary Motivations & Inner Conflicts
description: 1 paragraph describing what drives the character based on the events in the provided episodes.

## Notable Quote
quote: "A quote explicitly found in the provided summaries (if any), or construct a representative line based *strictly* on their behavior in the text."

## Character Background & Role
description: 1 paragraph describing their role and background as seen in the provided data.

## Personality & Traits
traits:
  - "Trait exposed by action in data"
  - "Another trait"
  - "A third trait"

## Key Events
events:
  - "Season X, Episode Y: Specific event from data"
  - "Season X, Episode Y: Another specific event"

## Importance to the Story
description: Explain in 1 paragraph how this character impacts the plot based on the provided episodes.

Note: If information for a section is not present in the source data, write "Not available in provided data" or skip the item.
"""
    
    return prompt

def build_grounded_show_prompt(show: str, tmdb_id: int, season: int, episode: int) -> str:
    """Build a show prompt with grounded episode data"""
    
    # Get show context with episode data
    show_context = episode_data_manager.get_show_context_for_prompt(tmdb_id, season, episode)
    
    # Build the grounded prompt
    prompt = f"""You are an expert TV analyst. Create a comprehensive show summary for {show}.

IMPORTANT: Use ONLY the provided episode data below. Do not make up or invent any details not present in the source material.

## Show Information
**Title:** {show_context.get('show_title', show)}
**Summary:** {show_context.get('show_summary', 'No show summary available')}
**Data Source:** {show_context.get('show_source', 'Unknown')}

## Episode Data (Up to Season {season}, Episode {episode})
"""
    
    # Add episode summaries
    episodes = show_context.get('episodes', [])
    if episodes:
        prompt += "\n**Episodes:**\n"
        for ep in episodes[:30]:  # Limit to first 30 episodes
            prompt += f"- Season {ep['season']}, Episode {ep['episode']}: {ep['title']}\n"
            if ep['summary']:
                prompt += f"  Summary: {ep['summary'][:150]}...\n"
    else:
        prompt += "\n**No episode data available for this cutoff.**\n"
    
    prompt += f"""

## Instructions
Based on the episode data above, create a show summary that includes:

1. **Overview** - The premise and main themes of the show
2. **Major Events** - Key plot developments up to Season {season}, Episode {episode}
3. **Character Arcs** - How main characters develop throughout the episodes
4. **Themes** - Central themes and messages of the show

## Requirements
- Use ONLY information from the provided episode data
- Include specific season/episode references for events
- If information is not available in the data, state "Not available in provided data"
- Be specific and avoid generic descriptions
- Focus on what actually happens in the episodes

Return the result in JSON format:
{{
  "overview": "Detailed description of the show's premise and themes",
  "major_events": [
    "Season X, Episode Y: Specific event description",
    "Season X, Episode Y: Another specific event"
  ],
  "character_arcs": [
    "Character Name: How they develop throughout the episodes",
    "Another Character: Their character development"
  ],
  "themes": ["Theme 1", "Theme 2", "Theme 3"],
  "data_sources": ["{show_context.get('show_source', 'Unknown')}"]
}}"""
    
    return prompt
