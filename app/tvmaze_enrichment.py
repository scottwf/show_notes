"""TVMaze Enrichment Service"""
import json
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from flask import current_app
from app.database import get_db
from app.episode_data_services import TVMazeService

logger = logging.getLogger(__name__)

class TVMazeEnrichmentService:
    def __init__(self):
        self.tvmaze = TVMazeService()
        self.staleness_days = 30

    def should_enrich_show(self, show_row: Dict) -> bool:
        """Check if enrichment needed"""
        tvmaze_enriched_at = show_row.get('tvmaze_enriched_at')

        if not tvmaze_enriched_at:
            return True

        try:
            enriched_date = datetime.fromisoformat(tvmaze_enriched_at)
            age_days = (datetime.now() - enriched_date).days
            if age_days > self.staleness_days:
                logger.info(f"Re-enriching {show_row.get('title')} ({age_days} days old)")
                return True
        except (ValueError, TypeError):
            return True

        return False

    def enrich_show(self, show_row: Dict) -> bool:
        """Enrich single show with TVMaze data"""
        tvdb_id = show_row.get('tvdb_id')
        show_title = show_row.get('title', 'Unknown')
        show_db_id = show_row.get('id')

        if not tvdb_id:
            logger.warning(f"Cannot enrich '{show_title}' - missing TVDB ID")
            return False

        logger.info(f"Enriching '{show_title}' (TVDB: {tvdb_id})")

        try:
            tvmaze_data = self.tvmaze.lookup_show_by_tvdb_id(tvdb_id)
            if not tvmaze_data:
                return False

            tvmaze_id = tvmaze_data.get('id')
            if not tvmaze_id:
                logger.error(f"TVMaze data missing 'id' for '{show_title}'")
                return False

            metadata = self._parse_show_metadata(tvmaze_data)

            db = get_db()
            self._update_show_metadata(db, show_db_id, tvmaze_id, metadata)

            cast_data = self.tvmaze.get_show_cast(tvmaze_id)
            if cast_data:
                self._store_cast_data(db, tvmaze_id, cast_data)

            db.commit()
            logger.info(f"Successfully enriched '{show_title}'")
            return True

        except Exception as e:
            logger.error(f"Error enriching '{show_title}': {e}", exc_info=True)
            try:
                get_db().rollback()
            except:
                pass
            return False

    def _parse_show_metadata(self, tvmaze_data: Dict) -> Dict:
        """Parse TVMaze API response"""
        summary = tvmaze_data.get('summary', '')
        if summary:
            summary = re.sub(r'<[^>]+>', '', summary)

        network = tvmaze_data.get('network', {})
        network_name = network.get('name') if network else None
        network_country = network.get('country', {}).get('code') if network else None

        if not network_name:
            web_channel = tvmaze_data.get('webChannel', {})
            network_name = web_channel.get('name') if web_channel else None
            network_country = web_channel.get('country', {}).get('code') if web_channel else None

        genres = tvmaze_data.get('genres', [])
        genres_json = json.dumps(genres) if genres else None

        rating_obj = tvmaze_data.get('rating', {})
        rating_value = rating_obj.get('average') if rating_obj else None

        return {
            'premiered': tvmaze_data.get('premiered'),
            'end_date': tvmaze_data.get('ended'),
            'tvmaze_summary': summary,
            'genres': genres_json,
            'network_name': network_name,
            'network_country': network_country,
            'runtime': tvmaze_data.get('runtime'),
            'tvmaze_rating': rating_value,
        }

    def _update_show_metadata(self, db, show_db_id: int, tvmaze_id: int, metadata: Dict):
        """Update sonarr_shows with TVMaze metadata"""
        db.execute("""
            UPDATE sonarr_shows
            SET tvmaze_id = ?, premiered = ?, end_date = ?,
                tvmaze_summary = ?, genres = ?, network_name = ?,
                network_country = ?, runtime = ?, tvmaze_rating = ?,
                tvmaze_enriched_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            tvmaze_id, metadata.get('premiered'), metadata.get('end_date'),
            metadata.get('tvmaze_summary'), metadata.get('genres'),
            metadata.get('network_name'), metadata.get('network_country'),
            metadata.get('runtime'), metadata.get('tvmaze_rating'),
            show_db_id
        ))

    def _store_cast_data(self, db, tvmaze_id: int, cast_data: List[Dict]):
        """Store cast in show_cast table"""
        db.execute("DELETE FROM show_cast WHERE show_tvmaze_id = ?", (tvmaze_id,))

        for idx, member in enumerate(cast_data):
            person = member.get('person', {})
            character = member.get('character', {})

            person_id = person.get('id')
            person_name = person.get('name')
            character_name = character.get('name')

            if not person_id or not person_name or not character_name:
                continue

            person_img = None
            if person.get('image'):
                person_img = person['image'].get('medium') or person['image'].get('original')

            char_img = None
            if character.get('image'):
                char_img = character['image'].get('medium') or character['image'].get('original')

            db.execute("""
                INSERT INTO show_cast (
                    show_tvmaze_id, person_id, person_name,
                    character_id, character_name,
                    character_image_url, person_image_url,
                    cast_order, is_voice
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tvmaze_id, person_id, person_name,
                character.get('id'), character_name,
                char_img, person_img, idx,
                member.get('voice', False)
            ))

tvmaze_enrichment_service = TVMazeEnrichmentService()
