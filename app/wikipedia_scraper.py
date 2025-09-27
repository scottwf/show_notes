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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
            
            # Try search
            search_results = self.wiki_api.search(show_title, results=10)
            for result in search_results:
                page = self.wiki_api.page(result)
                if page.exists() and self._is_tv_series_page(page):
                    return page.fullurl
            
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
            
            # Extract sections using mwparserfromhell
            wikitext = mwparserfromhell.parse(page.text)
            sections = self._parse_wikitext_sections(wikitext)
            
            # Extract structured data
            premise = self._extract_premise_from_sections(sections)
            cast_info = self._extract_cast_from_sections(sections)
            episodes = self._extract_episodes_from_sections(sections)
            production_info = self._extract_production_from_sections(sections)
            
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
                'method': 'wikipedia_api'
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
        
        # Find Cast section
        cast_section = self._find_section(soup, ['Cast', 'Cast and characters', 'Characters'])
        if not cast_section:
            return cast_info
        
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
    
    def _extract_episodes(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract episode information"""
        episodes = []
        
        # Look for Episodes section
        episodes_section = self._find_section(soup, ['Episodes', 'Episode list'])
        if not episodes_section:
            return episodes
        
        # Find episode table or list
        episode_table = episodes_section.find('table', class_='wikitable')
        if episode_table:
            episodes = self._extract_episodes_from_table(episode_table)
        else:
            # Try to extract from list format
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
        episode_col = self._find_column_index(headers, ['episode', 'no', '#'])
        title_col = self._find_column_index(headers, ['title', 'episode title'])
        air_date_col = self._find_column_index(headers, ['air date', 'aired', 'date'])
        description_col = self._find_column_index(headers, ['description', 'summary', 'plot'])
        
        # Extract episode data
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            episode = {}
            
            if episode_col is not None and episode_col < len(cells):
                episode['episode_number'] = cells[episode_col].get_text().strip()
            
            if title_col is not None and title_col < len(cells):
                episode['title'] = cells[title_col].get_text().strip()
            
            if air_date_col is not None and air_date_col < len(cells):
                episode['air_date'] = cells[air_date_col].get_text().strip()
            
            if description_col is not None and description_col < len(cells):
                episode['description'] = cells[description_col].get_text().strip()
            
            if episode:
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
        headings = soup.find_all(['h2', 'h3', 'h4'])
        
        for heading in headings:
            heading_text = heading.get_text().strip().lower()
            for section_name in section_names:
                if section_name.lower() in heading_text:
                    # Find the content after this heading
                    content = heading.find_next_sibling()
                    if content:
                        return content
                    
                    # Look for content in next elements
                    current = heading.next_sibling
                    while current:
                        if hasattr(current, 'name') and current.name in ['div', 'p', 'ul', 'ol', 'table']:
                            return current
                        current = current.next_sibling
        
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
                return self._parse_episodes_section_wikitext(sections[keyword])
        
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
        
        # Simple parsing - look for lists and extract actor/character pairs
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
        
        # Look for episode patterns
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


def scrape_wikipedia_show(show_title: str, rate_limit_seconds: int = 2) -> Dict:
    """
    Main function to scrape Wikipedia for a TV show
    
    Args:
        show_title: Name of the TV show to search for
        rate_limit_seconds: Delay between requests
    
    Returns:
        Dictionary containing extracted show information
    """
    scraper = WikipediaScraper(rate_limit_seconds)
    
    # Search for Wikipedia page
    page_url = scraper.search_wikipedia_page(show_title)
    if not page_url:
        return {'error': f'No Wikipedia page found for "{show_title}"'}
    
    # Extract show information
    show_info = scraper.extract_show_info(page_url)
    show_info['wikipedia_url'] = page_url
    
    return show_info


if __name__ == "__main__":
    # Test with Alien: Earth
    result = scrape_wikipedia_show("Alien: Earth")
    print(json.dumps(result, indent=2))
