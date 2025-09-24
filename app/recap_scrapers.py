"""
Recap Scrapers

This module provides scrapers for TV recap websites to extract episode summaries
and metadata for grounding LLM responses.
"""

import requests
import re
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
import time
from sqlite3 import Row
from app.database import get_db

logger = logging.getLogger(__name__)

class BaseRecapScraper:
    """Base class for recap scrapers"""
    
    def __init__(self, site_name: str, base_url: str, rate_limit: int = 30):
        self.site_name = site_name
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self.request_count = 0
        self.rate_limit_window = 60  # seconds
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def _rate_limit_check(self):
        """Ensure we don't exceed rate limits"""
        current_time = time.time()
        
        if current_time - self.last_request_time > self.rate_limit_window:
            self.request_count = 0
            self.last_request_time = current_time
        
        if self.request_count >= self.rate_limit:
            sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
            if sleep_time > 0:
                logger.info(f"Rate limit reached for {self.site_name}, sleeping for {sleep_time:.1f}s")
                time.sleep(sleep_time)
                self.request_count = 0
                self.last_request_time = time.time()
        
        self.request_count += 1
    
    def _make_request(self, url: str, params: Dict = None) -> Optional[str]:
        """Make a rate-limited request and return HTML content"""
        self._rate_limit_check()
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Request failed for {self.site_name}: HTTP {response.status_code}")
                if response.status_code == 420:
                    logger.warning(f"Rate limited by {self.site_name} - consider adding delays")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {self.site_name}: {e}")
            return None
    
    def extract_episode_info(self, title: str) -> Optional[Dict]:
        """Extract season and episode numbers from title"""
        # Common patterns for episode titles
        patterns = [
            r'Season\s+(\d+).*Episode\s+(\d+)',
            r'S(\d+)E(\d+)',
            r'Season\s+(\d+),\s*Episode\s+(\d+)',
            r'(\d+)x(\d+)',
            r'Episode\s+(\d+).*Season\s+(\d+)',
            r'Episode\s+(\d+)',  # Just episode number (assume season 1)
            r'Recap.*Episode\s+(\d+)'  # For patterns like "Task Recap: Episode 3"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                if 'Season' in pattern and 'Episode' in pattern:
                    return {'season': int(match.group(1)), 'episode': int(match.group(2))}
                elif len(match.groups()) == 2:
                    return {'season': int(match.group(1)), 'episode': int(match.group(2))}
                elif len(match.groups()) == 1:
                    # Single episode number, assume season 1
                    return {'season': 1, 'episode': int(match.group(1))}
        
        return None
    
    def extract_episode_info_from_content(self, html: str, title: str) -> Optional[Dict]:
        """Extract episode info from page content when not in title"""
        # Look for episode info in the HTML content
        content_patterns = [
            r'Season\s+(\d+)\s+Episode\s+(\d+)',
            r'S(\d+)E(\d+)',
            r'Episode\s+(\d+)',
            r'Season\s+(\d+)'
        ]
        
        for pattern in content_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    return {'season': int(match.group(1)), 'episode': int(match.group(2))}
                elif len(match.groups()) == 1:
                    # If we only find episode number, assume season 1
                    if 'episode' in pattern.lower():
                        return {'season': 1, 'episode': int(match.group(1))}
                    # If we only find season number, assume episode 1
                    elif 'season' in pattern.lower():
                        return {'season': int(match.group(1)), 'episode': 1}
        
        return None
    
    def normalize_show_title(self, title: str) -> str:
        """Normalize show title for matching"""
        # Remove common suffixes and normalize
        title = re.sub(r'\s*recap.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*season.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*episode.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^[^:]*:\s*', '', title)  # Remove everything before colon (e.g., "Task Recap: Pissing Contest" -> "Pissing Contest")
        title = re.sub(r'[^\w\s]', '', title)  # Remove punctuation
        title = re.sub(r'\s+', ' ', title).strip()  # Normalize whitespace
        
        # Handle special cases for known shows
        if 'task' in title.lower():
            return 'Task'
        
        return title.title()
    
    def scrape_episode_summary(self, url: str) -> Optional[Dict]:
        """Scrape episode summary from a specific URL - to be implemented by subclasses"""
        raise NotImplementedError

class VultureScraper(BaseRecapScraper):
    """Scraper for Vulture TV recaps"""
    
    def __init__(self):
        super().__init__("Vulture", "https://www.vulture.com", rate_limit=30)
    
    def get_recent_recaps(self, days_back: int = 7) -> List[Dict]:
        """Get recent recaps from Vulture"""
        html = self._make_request(f"{self.base_url}/tv-recaps/")
        if not html:
            return []
        
        recaps = []
        
        # Find recap links using multiple patterns for Vulture's structure
        link_patterns = [
            r'<a[^>]+href="([^"]*\/article\/[^"]*recap[^"]*)"[^>]*>([^<]+)<\/a>',
            r'<a[^>]+href="([^"]*\/article\/[^"]*recap[^"]*)"[^>]*>.*?<span[^>]*>([^<]+)<\/span>.*?<\/a>',
            r'<a[^>]+href="([^"]*\/tv-recaps\/[^"]*)"[^>]*>([^<]+)<\/a>',
            r'<a[^>]+href="([^"]*\/article\/[^"]*episode[^"]*)"[^>]*>([^<]+)<\/a>'
        ]
        
        all_matches = []
        for pattern in link_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            all_matches.extend(matches)
        
        for url, title in all_matches:
            title = re.sub(r'<[^>]+>', '', title).strip()  # Remove HTML tags
            url = urljoin(self.base_url, url)
            
            # Skip if not a specific episode recap
            if not any(keyword in title.lower() for keyword in ['recap', 'episode', 'season']):
                continue
            
            episode_info = self.extract_episode_info(title)
            
            # If no episode info in title, try to extract from the page content
            if not episode_info:
                # For now, we'll skip recaps without episode info
                # In the future, we could fetch the page content here
                continue
            
            recaps.append({
                'title': title,
                'url': url,
                'season': episode_info['season'],
                'episode': episode_info['episode'],
                'show_title': self.normalize_show_title(title),
                'source': 'Vulture'
            })
        
        return recaps
    
    def scrape_episode_summary(self, url: str) -> Optional[Dict]:
        """Scrape episode summary from Vulture recap URL"""
        html = self._make_request(url)
        if not html:
            return None
        
        # Extract title using regex
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        
        title = title_match.group(1).strip() if title_match else "Unknown Title"
        
        # Extract episode info from title
        episode_info = self.extract_episode_info(title)
        
        # If no episode info in title, try to extract from content
        if not episode_info:
            episode_info = self.extract_episode_info_from_content(html, title)
        
        # Extract content using regex - look for article content
        content_patterns = [
            r'<div[^>]*class="[^"]*article-content[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>'
        ]
        
        content = ""
        for pattern in content_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1)
                break
        
        if not content:
            return None
        
        # Extract paragraphs from content
        paragraph_pattern = r'<p[^>]*>(.*?)</p>'
        paragraphs = re.findall(paragraph_pattern, content, re.DOTALL | re.IGNORECASE)
        
        summary_parts = []
        for p in paragraphs:
            # Clean HTML tags and get text
            text = re.sub(r'<[^>]+>', '', p).strip()
            if text and len(text) > 50:  # Skip very short paragraphs
                summary_parts.append(text)
        
        summary = ' '.join(summary_parts[:5])  # Take first 5 substantial paragraphs
        
        # If we still don't have episode info, this might be a recap without clear episode structure
        if not episode_info:
            logger.warning(f"Could not extract episode info from Vulture recap: {title}")
            return None
        
        return {
            'title': title,
            'summary': summary,
            'url': url,
            'source': 'Vulture',
            'season': episode_info['season'],
            'episode': episode_info['episode'],
            'show_title': self.normalize_show_title(title)
        }

class ShowbizJunkiesScraper(BaseRecapScraper):
    """Scraper for Showbiz Junkies TV recaps"""
    
    def __init__(self):
        super().__init__("Showbiz Junkies", "https://www.showbizjunkies.com", rate_limit=30)
    
    def get_recent_recaps(self, days_back: int = 7) -> List[Dict]:
        """Get recent recaps from Showbiz Junkies"""
        html = self._make_request(f"{self.base_url}/category/tv/tv-recaps/")
        if not html:
            return []
        
        recaps = []
        
        # Find recap links using regex - Showbiz Junkies uses /tv/ URLs
        link_patterns = [
            r'<a[^>]+href="([^"]*\/tv\/[^"]*recap[^"]*)"[^>]*>([^<]+)<\/a>',
            r'<a[^>]+href="([^"]*\/tv-recaps\/[^"]*)"[^>]*>([^<]+)<\/a>'
        ]
        
        matches = []
        for pattern in link_patterns:
            pattern_matches = re.findall(pattern, html, re.IGNORECASE)
            matches.extend(pattern_matches)
        
        for url, title in matches:
            title = re.sub(r'<[^>]+>', '', title).strip()  # Remove HTML tags
            url = urljoin(self.base_url, url)
            
            # Skip if not a specific episode recap
            if not any(keyword in title.lower() for keyword in ['recap', 'episode', 'season']):
                continue
            
            episode_info = self.extract_episode_info(title)
            if episode_info:
                recaps.append({
                    'title': title,
                    'url': url,
                    'season': episode_info['season'],
                    'episode': episode_info['episode'],
                    'show_title': self.normalize_show_title(title),
                    'source': 'Showbiz Junkies'
                })
        
        return recaps
    
    def scrape_episode_summary(self, url: str) -> Optional[Dict]:
        """Scrape episode summary from Showbiz Junkies recap URL"""
        html = self._make_request(url)
        if not html:
            return None
        
        # Extract title using regex
        title_match = re.search(r'<h1[^>]*class="[^"]*entry-title[^"]*"[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        
        title = title_match.group(1).strip() if title_match else "Unknown Title"
        
        # Extract episode info from title
        episode_info = self.extract_episode_info(title)
        
        # Extract content using regex - look for entry content
        content_patterns = [
            r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>'
        ]
        
        content = ""
        for pattern in content_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1)
                break
        
        if not content:
            return None
        
        # Extract paragraphs from content
        paragraph_pattern = r'<p[^>]*>(.*?)</p>'
        paragraphs = re.findall(paragraph_pattern, content, re.DOTALL | re.IGNORECASE)
        
        summary_parts = []
        for p in paragraphs:
            # Clean HTML tags and get text
            text = re.sub(r'<[^>]+>', '', p).strip()
            if text and len(text) > 50:  # Skip very short paragraphs
                summary_parts.append(text)
        
        summary = ' '.join(summary_parts[:5])  # Take first 5 substantial paragraphs
        
        return {
            'title': title,
            'summary': summary,
            'url': url,
            'source': 'Showbiz Junkies',
            'season': episode_info['season'] if episode_info else None,
            'episode': episode_info['episode'] if episode_info else None,
            'show_title': self.normalize_show_title(title) if episode_info else None
        }

class RecapScrapingManager:
    """Manager class to coordinate recap scraping"""
    
    def __init__(self):
        self.scrapers = {
            'vulture': VultureScraper(),
            'showbiz_junkies': ShowbizJunkiesScraper()
        }
    
    def scrape_recent_recaps(self, days_back: int = 7) -> List[Dict]:
        """Scrape recent recaps from all sources"""
        all_recaps = []
        
        for scraper_name, scraper in self.scrapers.items():
            try:
                logger.info(f"Scraping recent recaps from {scraper.site_name}")
                recaps = scraper.get_recent_recaps(days_back)
                all_recaps.extend(recaps)
                logger.info(f"Found {len(recaps)} recaps from {scraper.site_name}")
            except Exception as e:
                logger.error(f"Error scraping {scraper.site_name}: {e}")
        
        return all_recaps
    
    def scrape_show_recaps(self, show_title: str, max_episodes: int = 20) -> List[Dict]:
        """Scrape recaps for a specific show"""
        all_recaps = []
        errors = []
        
        for scraper_name, scraper in self.scrapers.items():
            try:
                logger.info(f"Scraping {show_title} recaps from {scraper.site_name}")
                recaps = scraper.get_recent_recaps(days_back=365)  # Look back a year
                
                if not recaps:
                    logger.warning(f"No recaps found from {scraper.site_name} - may be rate limited")
                    errors.append(f"{scraper.site_name}: No recaps found (possibly rate limited)")
                    continue
                
                # Filter for the specific show
                show_recaps = []
                for recap in recaps:
                    if show_title.lower() in recap['show_title'].lower():
                        show_recaps.append(recap)
                
                # If no recaps found with episode info, try a more flexible approach
                if not show_recaps and show_title.lower() in ['task']:
                    logger.info(f"No structured recaps found for {show_title}, trying flexible matching...")
                    # For shows with limited episodes, be more flexible but still filter by show title
                    for recap in recaps:
                        # Only consider recaps that actually mention the show title
                        if show_title.lower() in recap['title'].lower() or show_title.lower() in recap['show_title'].lower():
                            # Try to extract episode info from the actual page content
                            try:
                                detailed_recap = scraper.scrape_episode_summary(recap['url'])
                                if detailed_recap and detailed_recap.get('season') and detailed_recap.get('episode'):
                                    # Double-check that this recap is actually for the right show
                                    if show_title.lower() in detailed_recap.get('show_title', '').lower():
                                        show_recaps.append(detailed_recap)
                                    else:
                                        logger.warning(f"Recap from {recap['url']} is not for {show_title}")
                                else:
                                    logger.warning(f"Could not extract episode info from {recap['url']}")
                            except Exception as e:
                                logger.error(f"Error scraping detailed recap from {recap['url']}: {e}")
                
                # Sort by season/episode and take the most recent
                show_recaps.sort(key=lambda x: (x['season'], x['episode']), reverse=True)
                show_recaps = show_recaps[:max_episodes]
                
                all_recaps.extend(show_recaps)
                logger.info(f"Found {len(show_recaps)} {show_title} recaps from {scraper.site_name}")
                
            except Exception as e:
                error_msg = f"Error scraping {show_title} from {scraper.site_name}: {e}"
                logger.error(error_msg)
                errors.append(f"{scraper.site_name}: {str(e)}")
        
        if errors:
            logger.warning(f"Scraping completed with errors: {'; '.join(errors)}")
        
        return all_recaps
    
    def scrape_episode_details(self, recap_url: str, source: str) -> Optional[Dict]:
        """Scrape detailed episode summary from a specific recap URL"""
        if source.lower() == 'vulture':
            return self.scrapers['vulture'].scrape_episode_summary(recap_url)
        elif source.lower() == 'showbiz junkies':
            return self.scrapers['showbiz_junkies'].scrape_episode_summary(recap_url)
        
        return None
    
    def match_recaps_to_shows(self, recaps: List[Dict]) -> List[Dict]:
        """Match scraped recaps to shows in our database"""
        db = get_db()
        matched_recaps = []
        
        for recap in recaps:
            # Try to find matching show in database
            show_row = db.execute("""
                SELECT tmdb_id, title FROM sonarr_shows 
                WHERE LOWER(title) LIKE LOWER(?) 
                OR LOWER(title) LIKE LOWER(?)
                LIMIT 1
            """, (f"%{recap['show_title']}%", f"%{recap['show_title'].replace(' ', '%')}%")).fetchone()
            
            if show_row:
                recap['tmdb_id'] = show_row['tmdb_id']
                recap['matched_show'] = show_row['title']
                matched_recaps.append(recap)
            else:
                logger.info(f"No match found for show: {recap['show_title']}")
        
        return matched_recaps
    
    def store_recap_summaries(self, recaps: List[Dict]):
        """Store scraped recap summaries in database"""
        db = get_db()
        
        for recap in recaps:
            if not recap.get('tmdb_id') or not recap.get('season') or not recap.get('episode'):
                logger.warning(f"Skipping recap with missing data: {recap}")
                continue
            
            try:
                # Scrape detailed summary
                detailed_summary = self.scrape_episode_details(recap['url'], recap['source'])
                if not detailed_summary:
                    logger.warning(f"Could not scrape detailed summary for: {recap['url']}")
                    continue
                
                # Store in database
                db.execute("""
                    INSERT OR REPLACE INTO episode_summaries 
                    (tmdb_id, season_number, episode_number, episode_title, normalized_summary, 
                     raw_source_data, source_provider, source_url, confidence_score, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    recap['tmdb_id'], recap['season'], recap['episode'], 
                    detailed_summary['title'], detailed_summary['summary'],
                    json.dumps(detailed_summary), recap['source'], recap['url'],
                    0.9,  # High confidence for scraped recaps
                    datetime.now(), datetime.now()
                ))
                
                logger.info(f"Stored recap summary for TMDB {recap['tmdb_id']} S{recap['season']}E{recap['episode']} from {recap['source']}")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error storing recap summary: {e}")
                logger.error(f"Recap data: {recap}")
                logger.error(f"Detailed summary: {detailed_summary if 'detailed_summary' in locals() else 'Not available'}")
                
                # Check if it's a regex pattern error
                if "pattern" in error_msg.lower() and "match" in error_msg.lower():
                    logger.error(f"Regex pattern error detected - this might be from episode info extraction")
                elif "json" in error_msg.lower():
                    logger.error(f"JSON serialization error - check detailed_summary data structure")
                else:
                    logger.error(f"Database or other error: {e}")
        
        db.commit()

# Global instance
recap_scraping_manager = RecapScrapingManager()
