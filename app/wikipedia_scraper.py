"""
Wikipedia scraper for TV show information
Extracts premise, cast, characters, and episode summaries from Wikipedia pages
Uses wikipedia-api and mwparserfromhell for proper Wikipedia data extraction
"""

import requests
import re
import json
import html
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin
from typing import Dict, List, Optional, Tuple
import time

try:
    import wikipediaapi
    import mwparserfromhell
    WIKIPEDIA_LIBS_AVAILABLE = True
except ImportError:
    WIKIPEDIA_LIBS_AVAILABLE = False
    print("Warning: wikipedia-api and mwparserfromhell not installed. Run: pip install wikipedia-api mwparserfromhell")


class WikipediaScraper:
    """Scraper for extracting TV show information from Wikipedia"""
    
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
        """Search for a Wikipedia page for the given show title using Wikipedia API"""
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
            
            return None
            
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
    
    def _is_tv_series_page(self, page) -> bool:
        """Check if a Wikipedia page is about a TV series"""
        try:
            # Check summary for TV-related keywords
            summary = page.summary.lower()
            tv_keywords = ['television', 'tv series', 'episodes', 'season', 'broadcast']
            
            return any(keyword in summary for keyword in tv_keywords)
        except:
            return False
    
    def extract_show_info(self, url: str) -> Dict:
        """Extract comprehensive show information from Wikipedia page"""
        if self.wiki_api:
            return self._extract_with_api(url)
        else:
            return self._extract_with_requests(url)
    
    def _extract_with_api(self, url: str) -> Dict:
        """Extract show info using Wikipedia API"""
        try:
            # Extract page title from URL
            page_title = url.split('/wiki/')[-1].replace('_', ' ')
            page = self.wiki_api.page(page_title)
            
            if not page.exists():
                return {'error': 'Page not found'}
            
            # Use HTML parsing for better results
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return {'error': f'Failed to load page: {response.status_code}'}
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract structured data using HTML parsing
            premise = self._extract_premise(soup)
            cast_info = self._extract_cast(soup)
            episodes = self._extract_episodes(soup)
            production_info = self._extract_production_info(soup)
            
            # Extract tables using pandas
            tables = self._extract_tables_from_url(url)
            
            return {
                'title': page.title,
                'url': page.fullurl,
                'premise': premise,
                'cast': cast_info,
                'episodes': episodes,
                'production': production_info,
                'tables': tables,
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'method': 'wikipedia_api_html'
            }
            
        except Exception as e:
            return {'error': f'Error extracting show info with API: {str(e)}'}
    
    def _extract_with_requests(self, url: str) -> Dict:
        """Fallback extraction using requests and BeautifulSoup"""
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return {'error': f'Failed to load page: {response.status_code}'}
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract basic info
            title = self._extract_title(soup)
            premise = self._extract_premise(soup)
            cast_info = self._extract_cast(soup)
            episodes = self._extract_episodes(soup)
            production_info = self._extract_production_info(soup)
            
            # Extract tables using pandas
            tables = self._extract_tables_from_url(url)
            
            return {
                'title': title,
                'url': url,
                'premise': premise,
                'cast': cast_info,
                'episodes': episodes,
                'production': production_info,
                'tables': tables,
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'method': 'requests'
            }
            
        except Exception as e:
            return {'error': f'Error extracting show info: {str(e)}'}
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract the show title from the page"""
        # Try the main heading first
        title_elem = soup.find('h1', class_='firstHeading')
        if title_elem:
            return title_elem.get_text().strip()
        
        # Fallback to page title
        title_elem = soup.find('title')
        if title_elem:
            title = title_elem.get_text().strip()
            # Remove " - Wikipedia" suffix
            return title.replace(' - Wikipedia', '')
        
        return "Unknown Title"
    
    def _extract_premise(self, soup: BeautifulSoup) -> str:
        """Extract the show premise/overview"""
        # Look for Premise section
        premise_section = self._find_section(soup, ['Premise', 'Plot', 'Overview', 'Synopsis'])
        if premise_section:
            return self._extract_section_text(premise_section)
        
        # Fallback to first paragraph of main content
        content_div = soup.find('div', class_='mw-parser-output')
        if content_div:
            # Find first paragraph after infobox
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                text = p.get_text().strip()
                if len(text) > 100:  # Skip short paragraphs
                    return text
        
        return ""
    
    def _extract_cast(self, soup: BeautifulSoup) -> Dict:
        """Extract cast and character information"""
        cast_info = {
            'main_cast': [],
            'recurring_cast': [],
            'guest_cast': []
        }
        
        # Look for cast tables directly first
        cast_tables = soup.find_all('table', class_='wikitable')
        for table in cast_tables:
            # Check if this looks like a cast table
            headers = [th.get_text().strip().lower() for th in table.find_all(['th', 'td'])]
            if any(keyword in ' '.join(headers) for keyword in ['actor', 'character', 'cast']):
                cast_data = self._extract_cast_from_table(table)
                if cast_data:
                    cast_info['main_cast'].extend(cast_data)
                    break
        
        # If no cast table found, try section-based extraction
        if not cast_info['main_cast']:
            cast_section = self._find_section(soup, ['Cast', 'Cast and characters', 'Characters'])
            if cast_section:
                # Extract main cast
                main_cast = self._extract_cast_subsection(cast_section, ['Main', 'Starring', 'Principal cast'])
                if main_cast:
                    cast_info['main_cast'] = main_cast
                
                # Extract recurring cast
                recurring_cast = self._extract_cast_subsection(cast_section, ['Recurring', 'Supporting'])
                if recurring_cast:
                    cast_info['recurring_cast'] = recurring_cast
                
                # Extract guest cast
                guest_cast = self._extract_cast_subsection(cast_section, ['Guest', 'Special guest'])
                if guest_cast:
                    cast_info['guest_cast'] = guest_cast
        
        return cast_info
    
    def _extract_cast_from_table(self, table) -> List[Dict]:
        """Extract cast information from a table"""
        cast_data = []
        rows = table.find_all('tr')
        
        if not rows:
            return cast_data
        
        # Get headers
        header_row = rows[0]
        headers = [th.get_text().strip().lower() for th in header_row.find_all(['th', 'td'])]
        
        # Find column indices
        actor_col = self._find_column_index(headers, ['actor', 'starring', 'performer'])
        character_col = self._find_column_index(headers, ['character', 'role', 'as'])
        
        # Extract cast data
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            cast_item = {}
            
            if actor_col is not None and actor_col < len(cells):
                # Extract actor name from links if present
                actor_link = cells[actor_col].find('a')
                if actor_link:
                    cast_item['actor'] = actor_link.get_text().strip()
                else:
                    cast_item['actor'] = cells[actor_col].get_text().strip()
            
            if character_col is not None and character_col < len(cells):
                # Extract character name from links if present
                character_link = cells[character_col].find('a')
                if character_link:
                    cast_item['character'] = character_link.get_text().strip()
                else:
                    cast_item['character'] = cells[character_col].get_text().strip()
            
            # Filter out non-cast entries
            if self._is_valid_cast_entry(cast_item):
                cast_data.append(cast_item)
        
        return cast_data
    
    def _is_valid_cast_entry(self, cast_item: Dict) -> bool:
        """Check if a cast entry is valid (not a DVD title, season, etc.)"""
        if not cast_item:
            return False
        
        actor = cast_item.get('actor', '').strip()
        character = cast_item.get('character', '').strip()
        
        # Skip if both are empty
        if not actor and not character:
            return False
        
        # Skip DVD/season titles
        dvd_keywords = ['season', 'complete', 'series', 'collection', 'box set', 'dvd', 'blu-ray']
        for keyword in dvd_keywords:
            if keyword in actor.lower() or keyword in character.lower():
                return False
        
        # Skip years and date ranges
        if re.match(r'^\d{4}', actor) or re.match(r'^\d{4}', character):
            return False
        
        # Skip if it looks like a title (starts with "The")
        if actor.startswith('The ') and len(actor.split()) > 3:
            return False
        
        return True
    
    def _extract_episodes(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract episode information"""
        episodes = []
        
        # Look for episode tables directly
        tables = soup.find_all('table', class_='wikiepisodetable')
        if not tables:
            tables = soup.find_all('table', class_='wikitable')
        
        # Extract episodes from all tables that look like episode tables
        for table in tables:
            table_episodes = self._extract_episodes_from_table(table)
            if table_episodes:
                episodes.extend(table_episodes)
        
        # If no episodes found, try to find episodes section
        if not episodes:
            episodes_section = self._find_section(soup, ['Episodes', 'Episode list'])
            if episodes_section:
                tables = episodes_section.find_all('table')
                for table in tables:
                    table_episodes = self._extract_episodes_from_table(table)
                    if table_episodes:
                        episodes.extend(table_episodes)
                
                # Try list format as fallback
                if not episodes:
                    episodes = self._extract_episodes_from_list(episodes_section)
        
        return episodes
    
    def _extract_episodes_from_table(self, table) -> List[Dict]:
        """Extract episodes from a Wikipedia table format"""
        episodes = []
        rows = table.find_all('tr')
        
        if not rows:
            return episodes
        
        # Get headers
        header_row = rows[0]
        headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]
        
        # Find column indices
        episode_col = self._find_column_index(headers, ['episode', 'no', '#', 'no.', 'no.overall', 'no. inseason'])
        title_col = self._find_column_index(headers, ['title', 'episode title'])
        director_col = self._find_column_index(headers, ['directed by', 'director'])
        writer_col = self._find_column_index(headers, ['written by', 'writer'])
        air_date_col = self._find_column_index(headers, ['air date', 'aired', 'date', 'original release date'])
        viewers_col = self._find_column_index(headers, ['viewers', 'u.s. viewers', 'rating'])
        description_col = self._find_column_index(headers, ['description', 'summary', 'plot'])
        
        # Skip if this doesn't look like an episode table
        if not any(col is not None for col in [episode_col, title_col]):
            return episodes
        
        # Extract episode data
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            episode = {}
            
            # Extract episode number (try both overall and season-specific)
            if episode_col is not None and episode_col < len(cells):
                episode_text = cells[episode_col].get_text().strip()
                # Handle cases like "1" or "1 1" (overall season)
                if episode_text and episode_text.isdigit():
                    episode['episode_number'] = episode_text
                elif ' ' in episode_text:
                    parts = episode_text.split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        episode['episode_number'] = parts[0]
                        episode['season_episode'] = parts[1] if parts[1].isdigit() else parts[1]
            
            if title_col is not None and title_col < len(cells):
                # Extract title from links if present
                title_link = cells[title_col].find('a')
                if title_link:
                    episode['title'] = title_link.get_text().strip()
                else:
                    episode['title'] = cells[title_col].get_text().strip()
            
            if director_col is not None and director_col < len(cells):
                episode['directed_by'] = cells[director_col].get_text().strip()
            
            if writer_col is not None and writer_col < len(cells):
                episode['written_by'] = cells[writer_col].get_text().strip()
            
            if air_date_col is not None and air_date_col < len(cells):
                episode['air_date'] = cells[air_date_col].get_text().strip()
            
            if viewers_col is not None and viewers_col < len(cells):
                episode['viewers'] = cells[viewers_col].get_text().strip()
            
            if description_col is not None and description_col < len(cells):
                episode['description'] = cells[description_col].get_text().strip()
            
            # Only add if we have at least a title or episode number
            if episode.get('title') or episode.get('episode_number'):
                episodes.append(episode)
        
        return episodes
    
    def _extract_episodes_from_list(self, section) -> List[Dict]:
        """Extract episodes from a list format"""
        episodes = []
        
        # Look for episode lists
        episode_lists = section.find_all(['ul', 'ol'])
        for episode_list in episode_lists:
            items = episode_list.find_all('li')
            for item in items:
                text = item.get_text().strip()
                
                # Try to parse episode info from text
                episode_match = re.match(r'^(?:Episode\s+)?(\d+)(?:[\.\-\s]+)?(.+?)(?:\s*\((.+?)\))?$', text)
                if episode_match:
                    episode = {
                        'episode_number': episode_match.group(1),
                        'title': episode_match.group(2).strip(),
                        'air_date': episode_match.group(3).strip() if episode_match.group(3) else ''
                    }
                    episodes.append(episode)
        
        return episodes
    
    def _extract_production_info(self, soup: BeautifulSoup) -> Dict:
        """Extract production information"""
        production_info = {}
        
        # Look for Production section
        production_section = self._find_section(soup, ['Production', 'Development'])
        if production_section:
            # Extract key production details
            text = self._extract_section_text(production_section)
            
            # Look for creator information
            creator_match = re.search(r'(?:Created by|Developed by|Executive producer[^:]*:)\s*([^.]+)', text, re.IGNORECASE)
            if creator_match:
                production_info['creator'] = creator_match.group(1).strip()
            
            # Look for network information
            network_match = re.search(r'(?:Network|Original network|Distributed by)\s*([^.]+)', text, re.IGNORECASE)
            if network_match:
                production_info['network'] = network_match.group(1).strip()
        
        return production_info
    
    def _find_section(self, soup: BeautifulSoup, section_names: List[str]) -> Optional:
        """Find a section by heading names"""
        # First try to find by ID
        for section_name in section_names:
            section_id = section_name.lower().replace(' ', '_')
            section_span = soup.find('span', {'id': section_id})
            if section_span:
                heading = section_span.find_parent(['h2', 'h3', 'h4'])
                if heading:
                    return self._extract_section_content(heading)
        
        # Fallback to text search
        headings = soup.find_all(['h2', 'h3', 'h4'])
        
        for heading in headings:
            heading_text = heading.get_text().strip().lower()
            for section_name in section_names:
                if section_name.lower() in heading_text:
                    return self._extract_section_content(heading)
        
        return None
    
    def _extract_section_content(self, heading) -> Optional:
        """Extract content from a section heading"""
        # Find the content after this heading
        current = heading.next_sibling
        while current:
            if hasattr(current, 'name'):
                if current.name in ['div', 'p', 'ul', 'ol', 'table']:
                    return current
                elif current.name in ['span'] and 'mw-editsection' in current.get('class', []):
                    # Skip edit sections
                    pass
                else:
                    # Found a content element
                    return current
            current = current.next_sibling
        
        # If no direct sibling, look for the next heading and return everything between
        next_heading = heading.find_next(['h2', 'h3', 'h4'])
        if next_heading and heading.parent:
            # Create a container div to hold all content between headings
            container = BeautifulSoup('<div></div>', 'html.parser').div
            current = heading.next_sibling
            while current and current != next_heading:
                if hasattr(current, 'name') and current.name not in ['span']:
                    container.append(current.extract())
                current = current.next_sibling
            return container if container.contents else None
        
        return None
    
    def _find_column_index(self, headers: List[str], keywords: List[str]) -> Optional[int]:
        """Find the index of a column by keywords"""
        for i, header in enumerate(headers):
            header_lower = header.lower()
            for keyword in keywords:
                if keyword.lower() in header_lower:
                    return i
        return None
    
    def _extract_section_text(self, section) -> str:
        """Extract text content from a section"""
        if not section:
            return ""
        
        # Remove unwanted elements
        for elem in section.find_all(['table', 'div', 'span']):
            if 'infobox' in elem.get('class', []):
                elem.decompose()
        
        return section.get_text().strip()
    
    def _extract_cast_subsection(self, cast_section, subsection_names: List[str]) -> List[Dict]:
        """Extract cast information from a subsection"""
        cast_list = []
        
        # Look for subsections
        headings = cast_section.find_all(['h3', 'h4'])
        for heading in headings:
            heading_text = heading.get_text().strip().lower()
            for subsection_name in subsection_names:
                if subsection_name.lower() in heading_text:
                    # Extract cast from this subsection
                    cast_items = self._extract_cast_items(heading)
                    cast_list.extend(cast_items)
        
        # If no subsections found, try to extract from the main section
        if not cast_list:
            cast_items = self._extract_cast_items(cast_section)
            cast_list.extend(cast_items)
        
        return cast_list
    
    def _extract_cast_items(self, section) -> List[Dict]:
        """Extract individual cast items from a section"""
        cast_items = []
        
        # Look for lists
        lists = section.find_all(['ul', 'ol'])
        for cast_list in lists:
            items = cast_list.find_all('li')
            for item in items:
                cast_item = self._parse_cast_item(item.get_text())
                if cast_item:
                    cast_items.append(cast_item)
        
        return cast_items
    
    def _parse_cast_item(self, text: str) -> Optional[Dict]:
        """Parse a cast item text into actor and character"""
        # Common patterns: "Actor as Character", "Actor (Character)", etc.
        patterns = [
            r'^([^–—−-]+?)\s+as\s+(.+)$',
            r'^([^(]+?)\s*\(([^)]+)\)$',
            r'^([^–—−-]+?)\s*[–—−-]\s*(.+)$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, text.strip(), re.IGNORECASE)
            if match:
                return {
                    'actor': match.group(1).strip(),
                    'character': match.group(2).strip()
                }
        
        # If no pattern matches, treat as actor name only
        if text.strip():
            return {
                'actor': text.strip(),
                'character': ''
            }
        
        return None
    
    def _parse_wikitext_sections(self, wikitext) -> Dict[str, str]:
        """Parse wikitext into sections"""
        sections = {}
        current_section = "Introduction"
        current_content = []
        
        for node in wikitext.nodes:
            if isinstance(node, mwparserfromhell.nodes.heading.Heading):
                # Save previous section
                if current_content:
                    sections[current_section] = ''.join(current_content)
                
                # Start new section
                current_section = str(node.title).strip()
                current_content = []
            else:
                current_content.append(str(node))
        
        # Save last section
        if current_content:
            sections[current_section] = ''.join(current_content)
        
        return sections
    
    def _extract_premise_from_sections(self, sections: Dict[str, str]) -> str:
        """Extract premise from parsed sections"""
        premise_keywords = ['Premise', 'Plot', 'Overview', 'Synopsis', 'Introduction']
        
        for keyword in premise_keywords:
            if keyword in sections:
                return self._clean_wikitext(sections[keyword])
        
        # Fallback to introduction
        if 'Introduction' in sections:
            return self._clean_wikitext(sections['Introduction'])
        
        return ""
    
    def _extract_cast_from_sections(self, sections: Dict[str, str]) -> Dict:
        """Extract cast information from sections"""
        cast_info = {
            'main_cast': [],
            'recurring_cast': [],
            'guest_cast': []
        }
        
        cast_keywords = ['Cast', 'Cast and characters', 'Characters']
        
        for keyword in cast_keywords:
            if keyword in sections:
                cast_section = sections[keyword]
                cast_info.update(self._parse_cast_section_wikitext(cast_section))
                break
        
        return cast_info
    
    def _extract_episodes_from_sections(self, sections: Dict[str, str]) -> List[Dict]:
        """Extract episode information from sections"""
        episode_keywords = ['Episodes', 'Episode list', 'Season 1', 'Season 2']
        
        for keyword in episode_keywords:
            if keyword in sections:
                episodes = self._parse_episodes_section_wikitext(sections[keyword])
                if episodes:
                    return episodes
        
        return []
    
    def _extract_production_from_sections(self, sections: Dict[str, str]) -> Dict:
        """Extract production information from sections"""
        production_info = {}
        
        production_keywords = ['Production', 'Development', 'Casting', 'Filming']
        
        for keyword in production_keywords:
            if keyword in sections:
                production_section = sections[keyword]
                
                # Extract creator
                creator_match = re.search(r'(?:Created by|Developed by|Executive producer[^:]*:)\s*([^.]+)', production_section, re.IGNORECASE)
                if creator_match:
                    production_info['creator'] = creator_match.group(1).strip()
                
                # Extract network
                network_match = re.search(r'(?:Network|Original network|Distributed by)\s*([^.]+)', production_section, re.IGNORECASE)
                if network_match:
                    production_info['network'] = network_match.group(1).strip()
        
        return production_info
    
    def _extract_tables_from_url(self, url: str) -> List[Dict]:
        """Extract tables from Wikipedia page using pandas"""
        try:
            tables = pd.read_html(url)
            table_data = []
            
            for i, table in enumerate(tables):
                table_dict = {
                    'index': i,
                    'columns': table.columns.tolist(),
                    'data': table.to_dict('records'),
                    'shape': table.shape
                }
                table_data.append(table_dict)
            
            return table_data
            
        except Exception as e:
            print(f"Error extracting tables: {e}")
            return []
    
    def _clean_wikitext(self, text: str) -> str:
        """Clean wikitext markup from text"""
        if not WIKIPEDIA_LIBS_AVAILABLE:
            # Simple cleaning without mwparserfromhell
            text = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', text)  # [[link|text]] -> text
            text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)  # [[link]] -> link
            text = re.sub(r'{{[^}]+}}', '', text)  # Remove templates
            text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
            return text.strip()
        
        # Use mwparserfromhell for proper cleaning
        parsed = mwparserfromhell.parse(text)
        return str(parsed.strip_code())
    
    def _parse_cast_section_wikitext(self, cast_section: str) -> Dict:
        """Parse cast section from wikitext"""
        cast_info = {
            'main_cast': [],
            'recurring_cast': [],
            'guest_cast': []
        }
        
        # Look for cast table patterns first
        table_pattern = r'\{\|.*?\|-\s*\|\s*\[\[([^\]]+)\]\]\s*\|\s*\[\[([^\]]+)\]\]\s*\|'
        table_matches = re.findall(table_pattern, cast_section, re.DOTALL | re.IGNORECASE)
        
        if table_matches:
            for match in table_matches:
                actor = self._clean_wikitext(match[0].strip())
                character = self._clean_wikitext(match[1].strip())
                cast_info['main_cast'].append({
                    'actor': actor,
                    'character': character
                })
            return cast_info
        
        # Fallback to simple parsing - look for lists and extract actor/character pairs
        lines = cast_section.split('\n')
        current_category = 'main_cast'
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for subsection headers
            if 'recurring' in line.lower():
                current_category = 'recurring_cast'
            elif 'guest' in line.lower():
                current_category = 'guest_cast'
            elif line.startswith('*') or line.startswith('#'):
                # Extract cast member
                cast_item = self._parse_cast_item_wikitext(line)
                if cast_item:
                    cast_info[current_category].append(cast_item)
        
        return cast_info
    
    def _parse_cast_item_wikitext(self, line: str) -> Optional[Dict]:
        """Parse a single cast item from wikitext"""
        # Remove list markers
        line = re.sub(r'^[*#]+\s*', '', line)
        
        # Parse patterns like "Actor as Character" or "Actor (Character)"
        patterns = [
            r'^([^–—−-]+?)\s+as\s+(.+)$',
            r'^([^(]+?)\s*\(([^)]+)\)$',
            r'^([^–—−-]+?)\s*[–—−-]\s*(.+)$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                return {
                    'actor': self._clean_wikitext(match.group(1).strip()),
                    'character': self._clean_wikitext(match.group(2).strip())
                }
        
        # If no pattern matches, treat as actor name only
        if line.strip():
            return {
                'actor': self._clean_wikitext(line.strip()),
                'character': ''
            }
        
        return None
    
    def _parse_episodes_section_wikitext(self, episodes_section: str) -> List[Dict]:
        """Parse episodes section from wikitext"""
        episodes = []
        
        # Look for episode table patterns first
        table_pattern = r'\{\|.*?\|-\s*\|\s*(\d+)\s*\|\s*\[\[([^\]]+)\]\]\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|'
        table_matches = re.findall(table_pattern, episodes_section, re.DOTALL | re.IGNORECASE)
        
        if table_matches:
            for match in table_matches:
                episode = {
                    'episode_number': match[0].strip(),
                    'title': self._clean_wikitext(match[1].strip()),
                    'directed_by': self._clean_wikitext(match[2].strip()),
                    'written_by': self._clean_wikitext(match[3].strip()),
                    'air_date': self._clean_wikitext(match[4].strip()),
                    'viewers': self._clean_wikitext(match[5].strip())
                }
                episodes.append(episode)
            return episodes
        
        # Fallback to simple patterns
        episode_patterns = [
            r'Episode\s+(\d+)(?:[\.\-\s]+)?(.+?)(?:\s*\((.+?)\))?',
            r'(\d+)(?:[\.\-\s]+)?(.+?)(?:\s*\((.+?)\))?'
        ]
        
        lines = episodes_section.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('='):
                continue
            
            for pattern in episode_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    episode = {
                        'episode_number': match.group(1),
                        'title': self._clean_wikitext(match.group(2).strip()),
                        'air_date': self._clean_wikitext(match.group(3).strip()) if match.group(3) else ''
                    }
                    episodes.append(episode)
                    break
        
        return episodes
    
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
    
    def consolidate_show_data(self, main_data: Dict, related_pages: List[Dict]) -> Dict:
        """Consolidate data from main page and all related pages"""
        consolidated = main_data.copy()
        
        # Initialize consolidated data structures
        consolidated['all_episodes'] = main_data.get('episodes', [])
        consolidated['all_cast'] = main_data.get('cast', {})
        consolidated['all_production'] = main_data.get('production', {})
        consolidated['season_pages'] = []
        consolidated['episode_pages'] = []
        consolidated['character_pages'] = []
        
        # Process each related page
        for page_info in related_pages:
            if 'data' not in page_info or 'error' in page_info:
                continue
            
            page_data = page_info['data']
            page_type = page_info['type']
            
            if page_type == 'season':
                # Extract episodes from season pages
                season_episodes = page_data.get('episodes', [])
                if season_episodes:
                    consolidated['all_episodes'].extend(season_episodes)
                    consolidated['season_pages'].append({
                        'title': page_info['title'],
                        'url': page_info['url'],
                        'episodes': season_episodes
                    })
            
            elif page_type == 'episode':
                # Individual episode page
                episode_data = {
                    'title': page_data.get('title', page_info['title']),
                    'url': page_info['url'],
                    'premise': page_data.get('premise', ''),
                    'cast': page_data.get('cast', {}),
                    'production': page_data.get('production', {})
                }
                consolidated['episode_pages'].append(episode_data)
            
            elif page_type == 'character':
                # Character page
                character_data = {
                    'title': page_data.get('title', page_info['title']),
                    'url': page_info['url'],
                    'premise': page_data.get('premise', ''),
                    'cast': page_data.get('cast', {})
                }
                consolidated['character_pages'].append(character_data)
            
            # Merge cast information
            page_cast = page_data.get('cast', {})
            for category, members in page_cast.items():
                if category not in consolidated['all_cast']:
                    consolidated['all_cast'][category] = []
                consolidated['all_cast'][category].extend(members)
            
            # Merge production information
            page_production = page_data.get('production', {})
            consolidated['all_production'].update(page_production)
        
        # Remove duplicate episodes, prioritizing episodes with titles
        seen_episodes = set()
        unique_episodes = []
        
        # Sort episodes to prioritize those with titles
        sorted_episodes = sorted(consolidated['all_episodes'], 
                               key=lambda x: (x.get('title', '') == 'Unknown', x.get('episode_number', '')))
        
        for episode in sorted_episodes:
            episode_key = f"{episode.get('episode_number', '')}-{episode.get('title', '')}"
            if episode_key not in seen_episodes:
                seen_episodes.add(episode_key)
                unique_episodes.append(episode)
            else:
                # If we already have this episode but this one has a better title, replace it
                existing_index = next(i for i, ep in enumerate(unique_episodes) 
                                    if f"{ep.get('episode_number', '')}-{ep.get('title', '')}" == episode_key)
                if (episode.get('title', '') != 'Unknown' and 
                    unique_episodes[existing_index].get('title', '') == 'Unknown'):
                    unique_episodes[existing_index] = episode
        
        consolidated['all_episodes'] = unique_episodes
        
        # Update episode count
        consolidated['total_episodes'] = len(consolidated['all_episodes'])
        consolidated['total_related_pages'] = len(related_pages)
        
        return consolidated
    
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
            
            # Extract JSON from response (handle Ollama's thinking tags)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
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
    Main function to scrape Wikipedia for a TV show with comprehensive data
    
    Args:
        show_title: Name of the TV show to search for
        rate_limit_seconds: Delay between requests
        discover_related: Whether to discover and scrape related pages (seasons, episodes)
    
    Returns:
        Dictionary containing extracted show information from all related pages
    """
    scraper = WikipediaScraper(rate_limit_seconds)
    
    # Search for main Wikipedia page
    page_url = scraper.search_wikipedia_page(show_title)
    if not page_url:
        return {'error': f'No Wikipedia page found for "{show_title}"'}
    
    # Extract main show information
    show_info = scraper.extract_show_info(page_url)
    show_info['wikipedia_url'] = page_url
    show_info['related_pages'] = []
    
    if discover_related and 'error' not in show_info:
        # Discover and scrape related pages
        related_pages = scraper.discover_related_pages(page_url, show_title)
        
        # Scrape each related page
        for page_info in related_pages:
            try:
                related_data = scraper.extract_show_info(page_info['url'])
                if 'error' not in related_data:
                    page_info['data'] = related_data
                else:
                    page_info['error'] = related_data['error']
            except Exception as e:
                page_info['error'] = str(e)
            
            # Rate limiting between requests
            import time
            time.sleep(rate_limit_seconds)
        
        # Consolidate all data
        show_info = scraper.consolidate_show_data(show_info, related_pages)
        show_info['related_pages'] = related_pages
    
    return show_info


if __name__ == "__main__":
    # Test with Alien: Earth
    result = scrape_wikipedia_show("Alien: Earth")
    print(json.dumps(result, indent=2))
