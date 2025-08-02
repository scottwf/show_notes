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
    options: {
        'include_relationships': True,
        'include_motivations': True,
        'include_themes': False,
        'include_quote': True,
        'tone': 'tv_expert' or 'in_character'
    }
    show_context: {
        'overview': 'Show description',
        'year': 2023,
        'genre': 'Drama'
    }
    episode_context: {
        'title': 'Episode Title',
        'overview': 'Episode description'
    }
    character_context: {
        'actor_name': 'Actor Name',
        'other_characters': ['Char1', 'Char2']
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
        other_chars = ', '.join(character_context['other_characters'][:5])  # Limit to 5 to avoid long prompts
        context_parts.append(f"Other characters in this episode: {other_chars}")
    if episode_context and episode_context.get('title'):
        context_parts.append(f"Episode {episode}: '{episode_context['title']}'")
    if episode_context and episode_context.get('overview'):
        context_parts.append(f"Episode context: {episode_context['overview']}")
    
    context_text = ""
    if context_parts:
        context_text = f"\n\nContext for accuracy:\n" + "\n".join(f"- {part}" for part in context_parts)

    # Add warning about accuracy
    accuracy_warning = f"\n\nIMPORTANT: Only describe what is definitively known about {character} specifically. Do not assume relationships or plot details from the general show description. If uncertain about {character}'s specific role or relationships, write 'Not available' rather than guessing."

    base = f"Provide a structured markdown character summary for the character {character} from the show {show}.{limit_text}{context_text}{accuracy_warning}"

    if options.get("tone") == "in_character":
        base = (
            f"You are {character} from {show}. Reflect on your life {limit_text} in first-person."
            " Format the output as markdown with clear section headings."
        )
    else:
        base += "\n\nWrite in the voice of an expert TV analyst. Use markdown with `##` headers."

    # Add forceful instruction to return only markdown
    base += "\n\nReturn only the markdown structure below. Do not include any explanations, preamble, or commentary."

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

def build_character_chat_prompt(character, show, season, episode, chat_history, show_context=None, episode_context=None, character_context=None):
    """
    Builds a prompt for a chatbot conversation about a character.
    """
    # Build context information
    context_parts = []
    if show_context and show_context.get('overview'):
        context_parts.append(f"Show context: {show_context['overview']}")
    if character_context and character_context.get('actor_name'):
        context_parts.append(f"Character: {character} is played by {character_context['actor_name']}")
    if episode_context and episode_context.get('title'):
        context_parts.append(f"Episode {episode}: '{episode_context['title']}'")
    if episode_context and episode_context.get('overview'):
        context_parts.append(f"Episode context: {episode_context['overview']}")
    
    context_text = ""
    if context_parts:
        context_text = f" Context for accuracy: " + " ".join(context_parts)

    accuracy_note = f" IMPORTANT: Only discuss what is definitively known about {character} specifically. Do not assume relationships or plot details from the general show description."

    system_prompt = f"You are a helpful assistant who knows everything about the TV show {show}. You are talking to a user who is asking questions about the character {character}. The user has only seen up to season {season}, episode {episode}, so do not reveal any spoilers beyond this point. Answer the user's questions concisely and accurately, based on the information available up to the specified episode.{context_text}{accuracy_note}"

    conversation = ""
    for message in chat_history:
        if message['role'] == 'user':
            conversation += f"User: {message['content']}\n"
        else:
            conversation += f"Assistant: {message['content']}\n"

    return f"{system_prompt}\n\n{conversation}Assistant:"