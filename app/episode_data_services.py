"""
Episode Data Services

This module provides services to fetch episode summaries and metadata from various APIs
to create grounded, reliable summaries for LLM prompts.
"""

import requests
import time
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlite3 import Row
from app.database import get_db
from flask import has_app_context

logger = logging.getLogger(__name__)

class EpisodeDataService:
    """Base class for episode data services"""
    
    def __init__(self, provider_name: str, rate_limit: int = 60):
        self.provider_name = provider_name
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self.request_count = 0
        self.rate_limit_window = 60  # seconds
        self.use_cache = True  # Enable caching by default
    
    def _rate_limit_check(self):
        """Ensure we don't exceed rate limits"""
        current_time = time.time()
        
        # Reset counter if we're in a new window
        if current_time - self.last_request_time > self.rate_limit_window:
            self.request_count = 0
            self.last_request_time = current_time
        
        # Check if we need to wait
        if self.request_count >= self.rate_limit:
            sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
            if sleep_time > 0:
                logger.info(f"Rate limit reached for {self.provider_name}, sleeping for {sleep_time:.1f}s")
                time.sleep(sleep_time)
                self.request_count = 0
                self.last_request_time = time.time()
        
        self.request_count += 1
    
    def _get_from_cache(self, request_type: str, request_key: str) -> Optional[Dict]:
        """Get cached response if available"""
        if not self.use_cache or not has_app_context():
            return None
            
        try:
            db = get_db()
            result = db.execute(
                "SELECT response_data FROM tvmaze_cache WHERE request_type = ? AND request_key = ?",
                (request_type, request_key)
            ).fetchone()
            
            if result:
                logger.debug(f"Cache HIT: {request_type}:{request_key}")
                return json.loads(result['response_data'])
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
        
        return None
    
    def _save_to_cache(self, request_type: str, request_key: str, response_data: Dict):
        """Save response to cache"""
        if not self.use_cache or not has_app_context():
            return
            
        try:
            db = get_db()
            db.execute("""
                INSERT INTO tvmaze_cache (request_type, request_key, response_data)
                VALUES (?, ?, ?)
                ON CONFLICT(request_type, request_key) DO UPDATE SET
                    response_data = excluded.response_data,
                    cached_at = CURRENT_TIMESTAMP
            """, (request_type, request_key, json.dumps(response_data)))
            db.commit()
            logger.debug(f"Cache SAVE: {request_type}:{request_key}")
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make a rate-limited request"""
        self._rate_limit_check()
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {self.provider_name}: {e}")
            return None

class TVMazeService(EpisodeDataService):
    """Service to fetch episode data from TVMaze API"""
    
    def __init__(self):
        super().__init__("TVMaze", rate_limit=60)
        self.base_url = "https://api.tvmaze.com"
    
    def search_show(self, show_title: str) -> List[Dict]:
        """Search for a show by title"""
        url = f"{self.base_url}/search/shows"
        params = {"q": show_title}
        
        data = self._make_request(url, params)
        if not data:
            return []
        
        return data
    
    def get_show_episodes(self, tvmaze_id: int) -> List[Dict]:
        """Get all episodes for a show"""
        url = f"{self.base_url}/shows/{tvmaze_id}/episodes"
        
        data = self._make_request(url)
        if not data:
            return []
        
        return data
    
    def get_episode_by_number(self, tvmaze_id: int, season: int, episode: int) -> Optional[Dict]:
        """Get a specific episode by season and episode number"""
        url = f"{self.base_url}/shows/{tvmaze_id}/episodebynumber"
        params = {"season": season, "number": episode}
        
        return self._make_request(url, params)
    
    def get_season_episodes(self, tvmaze_id: int, season: int) -> List[Dict]:
        """Get all episodes for a specific season"""
        url = f"{self.base_url}/shows/{tvmaze_id}/episodes"
        params = {"specials": 0}  # Exclude specials
        
        data = self._make_request(url, params)
        if not data:
            return []
        
        # Filter by season
        return [ep for ep in data if ep.get('season') == season]

    def lookup_show_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict]:
        """Look up show on TVMaze using TVDB ID"""
        request_key = str(tvdb_id)
        
        # Check cache first
        cached = self._get_from_cache("tvdb_lookup", request_key)
        if cached:
            return cached
        
        # Fetch from API
        url = f"{self.base_url}/lookup/shows"
        params = {"thetvdb": tvdb_id}
        data = self._make_request(url, params)
        
        if data:
            logger.info(f"TVMaze lookup: TVDB {tvdb_id} -> TVMaze ID {data.get('id')}")
            self._save_to_cache("tvdb_lookup", request_key, data)
        
        return data
    
    def get_show_details(self, tvmaze_id: int) -> Optional[Dict]:
        """Get full show details from TVMaze by ID"""
        request_key = str(tvmaze_id)
        
        # Check cache first
        cached = self._get_from_cache("show_details", request_key)
        if cached:
            return cached
        
        # Fetch from API
        url = f"{self.base_url}/shows/{tvmaze_id}"
        data = self._make_request(url)
        
        if data:
            self._save_to_cache("show_details", request_key, data)
        
        return data

    def get_show_cast(self, tvmaze_id: int) -> List[Dict]:
        """Get cast information for a show"""
        url = f"{self.base_url}/shows/{tvmaze_id}/cast"
        data = self._make_request(url)
        if data:
            logger.info(f"Fetched {len(data)} cast members for TVMaze ID {tvmaze_id}")
        return data if data else []

class TMDBService(EpisodeDataService):
    """Service to fetch episode data from TMDB API"""
    
    def __init__(self, api_key: str):
        super().__init__("TMDB", rate_limit=40)
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
    
    def get_tv_show_details(self, tmdb_id: int) -> Optional[Dict]:
        """Get TV show details"""
        url = f"{self.base_url}/tv/{tmdb_id}"
        params = {"api_key": self.api_key}
        
        return self._make_request(url, params)
    
    def get_season_details(self, tmdb_id: int, season_number: int) -> Optional[Dict]:
        """Get season details"""
        url = f"{self.base_url}/tv/{tmdb_id}/season/{season_number}"
        params = {"api_key": self.api_key}
        
        return self._make_request(url, params)
    
    def get_episode_details(self, tmdb_id: int, season_number: int, episode_number: int) -> Optional[Dict]:
        """Get episode details"""
        url = f"{self.base_url}/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}"
        params = {"api_key": self.api_key}
        
        return self._make_request(url, params)

class EpisodeDataManager:
    """Manager class to coordinate data fetching and storage"""
    
    def __init__(self):
        self.tvmaze = TVMazeService()
        self.tmdb = None  # Will be initialized with API key from settings
    
    def initialize_tmdb(self, api_key: str):
        """Initialize TMDB service with API key"""
        if api_key:
            self.tmdb = TMDBService(api_key)
    
    def find_show_tvmaze_id(self, show_title: str, tmdb_id: int = None) -> Optional[int]:
        """Find TVMaze ID for a show"""
        # First try exact title match
        results = self.tvmaze.search_show(show_title)
        
        if not results:
            return None
        
        # If we have TMDB ID, try to match by external IDs
        if tmdb_id:
            for result in results:
                show_data = result.get('show', {})
                external_ids = show_data.get('externals', {})
                if external_ids.get('thetvdb') == tmdb_id:
                    return show_data.get('id')
        
        # Fallback to first result
        return results[0].get('show', {}).get('id')
    
    def fetch_episode_summary(self, tmdb_id: int, season: int, episode: int) -> Optional[Dict]:
        """Fetch episode summary from available sources"""
        # Try TVMaze first (free, good data)
        tvmaze_id = self.find_show_tvmaze_id("", tmdb_id)  # We'll need to get show title first
        if tvmaze_id:
            episode_data = self.tvmaze.get_episode_by_number(tvmaze_id, season, episode)
            if episode_data and episode_data.get('summary'):
                return {
                    'summary': episode_data['summary'],
                    'title': episode_data.get('name', ''),
                    'airdate': episode_data.get('airdate', ''),
                    'source': 'TVMaze',
                    'source_url': episode_data.get('_links', {}).get('self', {}).get('href', '')
                }
        
        # Try TMDB if available
        if self.tmdb:
            episode_data = self.tmdb.get_episode_details(tmdb_id, season, episode)
            if episode_data and episode_data.get('overview'):
                return {
                    'summary': episode_data['overview'],
                    'title': episode_data.get('name', ''),
                    'airdate': episode_data.get('air_date', ''),
                    'source': 'TMDB',
                    'source_url': f"https://www.themoviedb.org/tv/{tmdb_id}/season/{season}/episode/{episode}"
                }
        
        return None
    
    def store_episode_summary(self, tmdb_id: int, season: int, episode: int, 
                            summary_data: Dict, confidence: float = 1.0):
        """Store episode summary in database"""
        db = get_db()
        
        try:
            # Clean HTML tags from summary
            import re
            clean_summary = re.sub(r'<[^>]+>', '', summary_data['summary'])
            
            db.execute("""
                INSERT OR REPLACE INTO episode_summaries 
                (tmdb_id, season_number, episode_number, episode_title, normalized_summary, 
                 raw_source_data, source_provider, source_url, confidence_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tmdb_id, season, episode, summary_data.get('title', ''),
                clean_summary, json.dumps(summary_data), summary_data['source'],
                summary_data.get('source_url', ''), confidence, datetime.now()
            ))
            db.commit()
            logger.info(f"Stored episode summary for TMDB {tmdb_id} S{season}E{episode} from {summary_data['source']}")
            
        except Exception as e:
            logger.error(f"Error storing episode summary: {e}")
            db.rollback()
    
    def get_episode_summary(self, tmdb_id: int, season: int, episode: int) -> Optional[Dict]:
        """Get stored episode summary"""
        db = get_db()
        
        try:
            row = db.execute("""
                SELECT * FROM episode_summaries 
                WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?
                ORDER BY confidence_score DESC, updated_at DESC
                LIMIT 1
            """, (tmdb_id, season, episode)).fetchone()
            
            if row:
                return {
                    'summary': row['normalized_summary'],
                    'title': row['episode_title'],
                    'source': row['source_provider'],
                    'source_url': row['source_url'],
                    'confidence': row['confidence_score'],
                    'updated_at': row['updated_at']
                }
            
        except Exception as e:
            logger.error(f"Error getting episode summary: {e}")
        
        return None
    
    def get_episodes_up_to_cutoff(self, tmdb_id: int, season_cutoff: int, episode_cutoff: int) -> List[Dict]:
        """Get all episodes up to a specific cutoff (spoiler-safe)"""
        db = get_db()
        
        try:
            rows = db.execute("""
                SELECT * FROM episode_summaries 
                WHERE tmdb_id = ? 
                AND (
                    (season_number < ?) OR 
                    (season_number = ? AND episode_number <= ?)
                )
                ORDER BY season_number, episode_number
            """, (tmdb_id, season_cutoff, season_cutoff, episode_cutoff)).fetchall()
            
            episodes = []
            for row in rows:
                episodes.append({
                    'season': row['season_number'],
                    'episode': row['episode_number'],
                    'title': row['episode_title'],
                    'summary': row['normalized_summary'],
                    'source': row['source_provider']
                })
            
            return episodes
            
        except Exception as e:
            logger.error(f"Error getting episodes up to cutoff: {e}")
            return []
    
    def get_show_context_for_prompt(self, tmdb_id: int, season_cutoff: int = None, episode_cutoff: int = None) -> Dict:
        """Get comprehensive show context for LLM prompts"""
        db = get_db()
        
        try:
            # Get show summary
            show_row = db.execute("""
                SELECT * FROM show_summaries 
                WHERE tmdb_id = ? 
                ORDER BY confidence_score DESC, updated_at DESC
                LIMIT 1
            """, (tmdb_id,)).fetchone()
            
            show_context = {
                'show_title': '',
                'show_summary': '',
                'show_source': '',
                'episodes': [],
                'seasons': []
            }
            
            if show_row:
                show_context.update({
                    'show_title': show_row['show_title'],
                    'show_summary': show_row['normalized_summary'],
                    'show_source': show_row['source_provider']
                })
            
            # Get episodes up to cutoff if specified
            if season_cutoff and episode_cutoff:
                episodes = self.get_episodes_up_to_cutoff(tmdb_id, season_cutoff, episode_cutoff)
                show_context['episodes'] = episodes
                
                # Get season summaries for completed seasons
                season_rows = db.execute("""
                    SELECT * FROM season_summaries 
                    WHERE tmdb_id = ? AND season_number < ?
                    ORDER BY season_number
                """, (tmdb_id, season_cutoff)).fetchall()
                
                for season_row in season_rows:
                    show_context['seasons'].append({
                        'season': season_row['season_number'],
                        'title': season_row['season_title'],
                        'summary': season_row['normalized_summary'],
                        'source': season_row['source_provider']
                    })
            
            return show_context
            
        except Exception as e:
            logger.error(f"Error getting show context: {e}")
            return show_context
    
    def get_character_context_for_prompt(self, tmdb_id: int, character_name: str, season_cutoff: int, episode_cutoff: int) -> Dict:
        """Get character-specific context for LLM prompts"""
        db = get_db()
        
        try:
            # Get show context first
            show_context = self.get_show_context_for_prompt(tmdb_id, season_cutoff, episode_cutoff)
            
            # Get character-specific episodes (where character appears)
            character_episodes = []
            
            # This would need to be enhanced to actually find episodes where the character appears
            # For now, we'll return the show context with a note about the character
            character_context = {
                'character_name': character_name,
                'show_context': show_context,
                'character_episodes': character_episodes,
                'note': 'Character-specific episode data not yet implemented'
            }
            
            return character_context
            
        except Exception as e:
            logger.error(f"Error getting character context: {e}")
            return {'character_name': character_name, 'error': str(e)}

# Global instance
episode_data_manager = EpisodeDataManager()
