"""
Wikipedia scraper for TV show information
Extracts premise, cast, characters, and episode summaries from Wikipedia pages
Uses LLM (Ollama) for intelligent parsing and data extraction
"""

import requests
import re
import json
import time
from bs4 import BeautifulSoup
from urllib.parse import quote
from typing import Dict, List, Optional
import time

try:
    import wikipediaapi
    WIKIPEDIA_LIBS_AVAILABLE = True
except ImportError:
    WIKIPEDIA_LIBS_AVAILABLE = False
    print("Warning: wikipedia-api not installed. Run: pip install wikipedia-api")


class WikipediaScraper:
    """Scraper for extracting TV show information from Wikipedia using LLM"""
    
    def __init__(self, rate_limit_seconds: int = 2):
        self.rate_limit_seconds = rate_limit_seconds
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ShowNotes/1.0 (https://shownotes.chitekmedia.club) - Educational TV Show Information Scraper',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Initialize Wikipedia API if available
        if WIKIPEDIA_LIBS_AVAILABLE:
            self.wiki_api = wikipediaapi.Wikipedia(
                user_agent='ShowNotes/1.0 (https://shownotes.chitekmedia.club)',
                language='en',
                extract_format=wikipediaapi.ExtractFormat.WIKI
            )
        else:
            self.wiki_api = None
    
    def search_wikipedia_page(self, show_title: str) -> Optional[str]:
        """Search for a Wikipedia page for the given show title"""
        if self.wiki_api:
            return self._search_with_api(show_title)
        else:
            return self._search_with_requests(show_title)
    
    def _search_with_api(self, show_title: str) -> Optional[str]:
        """Search using Wikipedia API"""
        try:
            # Try direct page first
            page = self.wiki_api.page(show_title)
            if page.exists():
                # Check if this is the right type of page
                if self._is_disambiguation_or_wrong_type(page.text, show_title):
                    # Try TV series specific search
                    return self._search_tv_series_specific(show_title)
                return page.fullurl
            
            # Try variations
            variations = [
                f"{show_title} (TV series)",
                f"{show_title} (television series)",
                f"{show_title} (TV show)",
                f"{show_title} (television show)"
            ]
            
            for variation in variations:
                page = self.wiki_api.page(variation)
                if page.exists():
                    return page.fullurl
            
            # Try search using requests fallback
            return self._search_with_requests(show_title)
            
        except Exception as e:
            print(f"Error searching Wikipedia API for {show_title}: {e}")
            return None
    
    def _search_with_requests(self, show_title: str) -> Optional[str]:
        """Fallback search using requests"""
        try:
            # Try direct page first
            direct_url = f"https://en.wikipedia.org/wiki/{quote(show_title.replace(' ', '_'))}"
            response = self.session.get(direct_url, timeout=10)
            
            if response.status_code == 200 and "Wikipedia, the free encyclopedia" in response.text:
                # Check if this is a disambiguation page or wrong content type
                if self._is_disambiguation_or_wrong_type(response.text, show_title):
                    # Try TV series specific search
                    return self._search_tv_series_specific(show_title)
                return direct_url
            
            # If direct fails, try search
            search_url = "https://en.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'search',
                'srsearch': f"{show_title} television series",
                'srlimit': 5
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'query' in data and 'search' in data['query']:
                    for result in data['query']['search']:
                        title = result['title']
                        snippet = result.get('snippet', '').lower()
                        
                        # Check if it's a TV series
                        if any(keyword in snippet for keyword in ['television', 'tv series', 'episodes', 'season']):
                            page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                            return page_url
            
            return None
            
        except Exception as e:
            print(f"Error searching Wikipedia for {show_title}: {e}")
            return None
    
    def _is_disambiguation_or_wrong_type(self, content: str, show_title: str) -> bool:
        """Check if the page is a disambiguation page or wrong content type (e.g., band instead of TV show)"""
        # Check if content is HTML or plain text
        if '<html' in content or '<div' in content:
            # HTML content - use BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Check for disambiguation patterns
            disambiguation_patterns = [
                "this article is about",
                "for the", "see",
                "disambiguation",
                "may refer to:",
                "can refer to:"
            ]
            
            # Look in the first paragraph or infobox
            first_paragraph = soup.find('div', class_='mw-parser-output')
            if first_paragraph:
                first_p = first_paragraph.find('p')
                if first_p:
                    text = first_p.get_text().lower()
                    for pattern in disambiguation_patterns:
                        if pattern in text:
                            return True
            
            # Also check for specific disambiguation text patterns
            page_text = soup.get_text().lower()
            if "this article is about" in page_text and "for the" in page_text:
                return True
            
            # Check infobox for genre/type
            infobox = soup.find('table', class_='infobox')
            if infobox:
                infobox_text = infobox.get_text().lower()
                for indicator in ['band', 'musical group', 'album', 'song', 'music']:
                    if indicator in infobox_text:
                        return True
        else:
            # Plain text content (from API) - check directly
            text = content.lower()
            
            # Check for disambiguation patterns
            if "this article is about" in text and "for the" in text:
                return True
        
        # Check if it's clearly not a TV show (e.g., band, movie, book)
        non_tv_indicators = [
            "band", "musical group", "album", "song", "music",
            "film", "movie", "book", "novel", "author"
        ]
        
        # Check the beginning of the content for non-TV indicators
        content_start = content.lower()[:500]  # First 500 characters
        for indicator in non_tv_indicators:
            if indicator in content_start:
                return True
        
        return False
    
    def _search_tv_series_specific(self, show_title: str) -> Optional[str]:
        """Search specifically for TV series pages"""
        try:
            # Try with (TV series) suffix
            tv_series_variations = [
                f"{show_title} (TV series)",
                f"{show_title} (television series)",
                f"{show_title} (TV show)",
                f"{show_title} (television show)",
                f"{show_title} (series)"
            ]
            
            for variation in tv_series_variations:
                url = f"https://en.wikipedia.org/wiki/{quote(variation.replace(' ', '_'))}"
                response = self.session.get(url, timeout=10)
                
                if response.status_code == 200 and "Wikipedia, the free encyclopedia" in response.text:
                    # Verify this is actually a TV series page
                    if not self._is_disambiguation_or_wrong_type(response.text, show_title):
                        return url
            
            # Try search API with TV-specific terms
            search_url = "https://en.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'search',
                'srsearch': f'"{show_title}" (television OR "TV series" OR "TV show")',
                'srlimit': 10
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'query' in data and 'search' in data['query']:
                    for result in data['query']['search']:
                        title = result['title']
                        snippet = result.get('snippet', '').lower()
                        
                        # Strong preference for TV series indicators
                        if any(keyword in snippet for keyword in ['television series', 'tv series', 'episodes', 'season', 'broadcast']):
                            page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                            # Double-check by fetching the page
                            page_response = self.session.get(page_url, timeout=10)
                            if page_response.status_code == 200:
                                if not self._is_disambiguation_or_wrong_type(page_response.text, show_title):
                                    return page_url
            
            return None
            
        except Exception as e:
            print(f"Error in TV series specific search for {show_title}: {e}")
            return None
    
    def _extract_raw_content(self, soup: BeautifulSoup) -> str:
        """Extract clean text content from Wikipedia page for LLM processing"""
        # Remove navigation, infoboxes, and other non-content elements
        for element in soup.find_all(['nav', 'table', 'div'], class_=['navbox', 'infobox', 'sidebar', 'metadata']):
            element.decompose()
        
        # Remove edit links and other Wikipedia-specific elements
        for element in soup.find_all(['span'], class_=['mw-editsection', 'reference']):
            element.decompose()
        
        # Get main content area
        content = soup.find('div', {'id': 'mw-content-text'}) or soup.find('div', {'class': 'mw-body-content'})
        if not content:
            content = soup
        
        # Extract text with some structure
        text_parts = []
        
        # Add title
        title = soup.find('h1', {'id': 'firstHeading'})
        if title:
            text_parts.append(f"Title: {title.get_text().strip()}")
        
        # Add main headings and content
        for heading in content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip()
            if heading_text and not heading_text.startswith('['):  # Skip empty or reference headings
                text_parts.append(f"\n{heading_text}")
                
                # Add content under this heading - look for the next heading
                next_heading = heading.find_next(['h2', 'h3', 'h4'])
                current = heading.next_sibling
                content_text = []
                
                while current and current != next_heading:
                    if hasattr(current, 'name'):
                        if current.name in ['p', 'li', 'ul', 'ol', 'table']:
                            para_text = current.get_text().strip()
                            if para_text and len(para_text) > 10:  # Include shorter text too
                                content_text.append(para_text)
                    current = current.next_sibling
                
                if content_text:
                    text_parts.append('\n'.join(content_text[:5]))  # Include more content
        
        return '\n'.join(text_parts)
    
    def _parse_with_llm(self, show_title: str, raw_content: str, page_url: str) -> Dict:
        """Use LLM to parse and structure Wikipedia content"""
        try:
            from app.llm_services import get_llm_response
            from app.database import get_db_connection
            
            # Create a comprehensive prompt for the LLM
            prompt = f"""
You are a TV show information extractor. Analyze this Wikipedia content and extract structured data.

Show: "{show_title}"

Wikipedia Content:
{raw_content[:6000]}

Extract information and return ONLY this JSON format (no other text):

{{
    "title": "Show Title",
    "premise": "Brief plot summary",
    "cast": {{
        "main_cast": [
            {{"actor": "Actor Name", "character": "Character Name"}}
        ],
        "recurring_cast": [
            {{"actor": "Actor Name", "character": "Character Name"}}
        ]
    }},
    "episodes": [
        {{
            "episode_number": "1",
            "title": "Episode Title",
            "air_date": "Date",
            "directed_by": "Director",
            "written_by": "Writer"
        }}
    ],
    "production": {{
        "created_by": "Creator",
        "network": "Network",
        "genre": "Genre",
        "country": "Country",
        "language": "Language"
    }}
}}

Instructions:
1. Look for cast lists in "Cast" or "Characters" sections
2. Look for episode lists in "Episodes" sections or tables
3. Extract premise from "Plot" or "Premise" sections
4. Find production info in infoboxes or "Production" sections
5. If no information found, use empty arrays []
6. Return ONLY the JSON object
"""
            
            # Get LLM response (this will automatically log to database)
            response, error = get_llm_response(prompt, provider='ollama')
            
            if error or not response:
                return {'error': f'Failed to get LLM response: {error or "Unknown error"}'}
            
            # Parse JSON response - extract JSON from Ollama response
            import json
            import re
            
            # Extract JSON from response (handle Ollama's thinking tags and extra text)
            # Look for the first complete JSON object
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # Fallback: try to find JSON between first { and last }
                start = response.find('{')
                end = response.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_str = response[start:end+1]
                else:
                    json_str = response.strip()
            
            try:
                result = json.loads(json_str)
                
                # Add metadata
                result['wikipedia_url'] = page_url
                result['scraped_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                result['method'] = 'llm_parsing'
                
                # Ensure required fields exist
                if 'cast' not in result:
                    result['cast'] = {'main_cast': [], 'recurring_cast': []}
                if 'episodes' not in result:
                    result['episodes'] = []
                if 'production' not in result:
                    result['production'] = {}
                
                # Store the parsed data in the database
                self._store_wikipedia_data(show_title, result)
                
                return result
                
            except json.JSONDecodeError as e:
                return {'error': f'Failed to parse LLM response as JSON: {e}'}
                
        except Exception as e:
            return {'error': f'Error in LLM parsing: {str(e)}'}
    
    def _store_wikipedia_data(self, show_title: str, data: Dict) -> None:
        """Store parsed Wikipedia data in the database"""
        try:
            from app.database import get_db_connection
            import json
            
            db = get_db_connection()
            
            # Store in a new table for Wikipedia data
            db.execute('''
                CREATE TABLE IF NOT EXISTS wikipedia_show_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    show_title TEXT NOT NULL,
                    title TEXT,
                    premise TEXT,
                    cast_data TEXT,  -- JSON string
                    episodes_data TEXT,  -- JSON string
                    production_data TEXT,  -- JSON string
                    wikipedia_url TEXT,
                    scraped_at TEXT,
                    method TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert the data
            db.execute('''
                INSERT INTO wikipedia_show_data 
                (show_title, title, premise, cast_data, episodes_data, production_data, 
                 wikipedia_url, scraped_at, method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                show_title,
                data.get('title', ''),
                data.get('premise', ''),
                json.dumps(data.get('cast', {})),
                json.dumps(data.get('episodes', [])),
                json.dumps(data.get('production', {})),
                data.get('wikipedia_url', ''),
                data.get('scraped_at', ''),
                data.get('method', 'llm_parsing')
            ))
            
            db.commit()
            
        except Exception as e:
            print(f"Error storing Wikipedia data: {e}")
            # Don't fail the whole operation if database storage fails
    
    def discover_related_pages(self, main_url: str, show_title: str) -> List[Dict]:
        """Discover related Wikipedia pages (seasons, episodes, characters)"""
        related_pages = []
        
        try:
            response = self.session.get(main_url, timeout=15)
            if response.status_code != 200:
                return related_pages
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all internal Wikipedia links
            links = soup.find_all('a', href=True)
            
            for link in links:
                href = link.get('href', '')
                link_text = link.get_text().strip()
                
                # Skip external links and non-Wikipedia links
                if not href.startswith('/wiki/') or href.startswith('/wiki/File:') or href.startswith('/wiki/Category:'):
                    continue
                
                # Convert to full URL
                full_url = f"https://en.wikipedia.org{href}"
                
                # Check if this looks like a related page
                page_type = self._classify_related_page(link_text, href, show_title)
                if page_type:
                    related_pages.append({
                        'url': full_url,
                        'title': link_text,
                        'type': page_type,
                        'href': href
                    })
            
            # Remove duplicates and limit results
            seen_urls = set()
            unique_pages = []
            for page in related_pages:
                if page['url'] not in seen_urls and len(unique_pages) < 20:  # Limit to 20 related pages
                    seen_urls.add(page['url'])
                    unique_pages.append(page)
            
            return unique_pages
            
        except Exception as e:
            print(f"Error discovering related pages: {e}")
            return related_pages
    
    def _classify_related_page(self, link_text: str, href: str, show_title: str) -> Optional[str]:
        """Classify a Wikipedia link as a related page type"""
        text_lower = link_text.lower()
        href_lower = href.lower()
        show_lower = show_title.lower()
        
        # Episode list pages (prioritize these)
        if any(keyword in text_lower for keyword in ['list of', 'episodes']) and show_lower in text_lower:
            return 'season'
        
        # Individual episode pages
        if any(keyword in text_lower for keyword in ['episode', 'pilot']) and show_lower in text_lower:
            if not any(keyword in text_lower for keyword in ['list of', 'episodes']):
                return 'episode'
        
        # Season pages
        if any(keyword in text_lower for keyword in ['season', 'series']) and show_lower in text_lower:
            return 'season'
        
        # Character pages
        if show_lower in text_lower and any(keyword in text_lower for keyword in ['character', 'cast']):
            return 'character'
        
        # Show-specific pages
        if show_lower in text_lower and any(keyword in text_lower for keyword in ['breaking bad', 'alien earth']):
            if not any(keyword in text_lower for keyword in ['disambiguation', 'category', 'file']):
                return 'show_related'
        
        return None


def scrape_wikipedia_show_with_llm(show_title: str, rate_limit_seconds: int = 2, discover_related: bool = True) -> Dict:
    """
    Scrape Wikipedia for a TV show using LLM for intelligent parsing and summarization
    
    Args:
        show_title: Name of the TV show to search for
        rate_limit_seconds: Delay between requests
        discover_related: Whether to discover and scrape related pages (seasons, episodes)
    
    Returns:
        Dictionary containing extracted and LLM-processed show information
    """
    scraper = WikipediaScraper(rate_limit_seconds)
    
    # Search for main Wikipedia page
    page_url = scraper.search_wikipedia_page(show_title)
    if not page_url:
        return {'error': f'No Wikipedia page found for "{show_title}"'}
    
    # Get raw HTML content
    try:
        response = scraper.session.get(page_url, timeout=15)
        if response.status_code != 200:
            return {'error': f'Failed to load page: {response.status_code}'}
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract raw text content for LLM processing
        raw_content = scraper._extract_raw_content(soup)
        
        # Use LLM to parse and structure the information
        llm_result = scraper._parse_with_llm(show_title, raw_content, page_url)
        
        # Add related pages if requested
        if discover_related and 'error' not in llm_result:
            related_pages = scraper.discover_related_pages(page_url, show_title)
            llm_result['related_pages'] = related_pages
            llm_result['total_related_pages'] = len(related_pages)
        
        return llm_result
        
    except Exception as e:
        return {'error': f'Error scraping Wikipedia: {str(e)}'}


def scrape_wikipedia_show(show_title: str, rate_limit_seconds: int = 2, discover_related: bool = True) -> Dict:
    """
    Legacy function - now uses LLM parsing by default
    """
    return scrape_wikipedia_show_with_llm(show_title, rate_limit_seconds, discover_related)


if __name__ == "__main__":
    # Test with Alien: Earth
    result = scrape_wikipedia_show_with_llm("Alien: Earth")
    print(json.dumps(result, indent=2))