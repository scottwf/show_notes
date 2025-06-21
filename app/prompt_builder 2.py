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

def build_character_prompt(character, show, season=None, episode=None, options=None):
    """
    options: {
        'include_relationships': True,
        'include_motivations': True,
        'include_themes': False,
        'include_quote': True,
        'tone': 'tv_expert' or 'in_character'
    }
    """
    if options is None:
        options = {}

    limit_text = f" Limit the analysis to events up to Season {season}, Episode {episode}." if season and episode else ""

    base = f"Provide a structured markdown character summary for the character {character} from the show {show}.{limit_text}"

    if options.get("tone") == "in_character":
        base = (
            f"You are {character} from {show}. Reflect on your life {limit_text} in first-person."
            " Format the output as markdown with clear section headings."
        )
    else:
        base += "\n\nWrite in the voice of an expert TV analyst. Use markdown with `##` headers."

    extras = []

    if options.get("include_relationships"):
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

    if options.get("include_motivations"):
        extras.append("""
## Primary Motivations & Inner Conflicts
description: 1 paragraph describing what drives the character and any emotional or psychological tension.
""")

    if options.get("include_themes"):
        extras.append("""
## Themes & Symbolism
description: Describe the themes or archetypes the character embodies, using literary or genre references.
""")

    if options.get("include_quote"):
        extras.append("""
## Notable Quote
quote: "Insert the quote here."
The quote should stand alone without additional commentary.
""")

    extras.append("""
## Personality & Traits
traits:
  - "Adjective or descriptor 1"
  - "Adjective or descriptor 2"
  - "Adjective or descriptor 3"
If unknown, write: Not available.
""")

    extras.append("""
## Key Events
events:
  - "Major turning point 1"
  - "Major turning point 2"
  - "Major turning point 3"
Or write: Not available.
""")

    extras.append("""
## Importance to the Story
description: Explain in 1 paragraph how this character impacts the show's plot or themes, or write: Not available.
""")

    return base + "\n\n" + "\n\n".join(extras)