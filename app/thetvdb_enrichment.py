"""TheTVDB Enrichment Service - Primary enrichment with TVMaze fallback"""
import json
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from flask import current_app
from app.database import get_db
from app.episode_data_services import TheTVDBService, TVMazeService
from app.tvmaze_enrichment import TVMazeEnrichmentService

logger = logging.getLogger(__name__)


class TheTVDBEnrichmentService:
    def __init__(self):
        self._tvdb = None
        self._tvdb_api_key = None
        self.tvmaze_fallback = TVMazeEnrichmentService()
        self.staleness_days = 30

    def _get_tvdb_service(self) -> Optional[TheTVDBService]:
        """Lazily initialize TheTVDB service with API key from settings"""
        try:
            db = get_db()
            row = db.execute("SELECT thetvdb_api_key FROM settings LIMIT 1").fetchone()
            api_key = row['thetvdb_api_key'] if row else None
        except Exception:
            api_key = None

        if not api_key:
            return None

        # Re-create service if API key changed
        if api_key != self._tvdb_api_key:
            self._tvdb = TheTVDBService(api_key)
            self._tvdb_api_key = api_key

        return self._tvdb

    def should_enrich_show(self, show_row: Dict) -> bool:
        """Check if enrichment needed based on staleness"""
        # Check TVDB enrichment first, then TVMaze
        enriched_at = show_row.get('tvdb_enriched_at') or show_row.get('tvmaze_enriched_at')

        if not enriched_at:
            return True

        try:
            enriched_date = datetime.fromisoformat(enriched_at)
            age_days = (datetime.now() - enriched_date).days
            if age_days > self.staleness_days:
                logger.info(f"Re-enriching {show_row.get('title')} ({age_days} days old)")
                return True
        except (ValueError, TypeError):
            return True

        return False

    def enrich_show(self, show_row: Dict) -> bool:
        """Enrich show - try TVDB first, fall back to TVMaze"""
        tvdb_service = self._get_tvdb_service()

        if tvdb_service:
            success = self._enrich_from_tvdb(show_row, tvdb_service)
            if success:
                return True
            logger.warning(f"TVDB enrichment failed for '{show_row.get('title')}', trying TVMaze fallback")

        # Fallback to TVMaze
        return self.tvmaze_fallback.enrich_show(show_row)

    def _enrich_from_tvdb(self, show_row: Dict, tvdb_service: TheTVDBService) -> bool:
        """Primary enrichment from TheTVDB"""
        tvdb_id = show_row.get('tvdb_id')
        show_title = show_row.get('title', 'Unknown')
        show_db_id = show_row.get('id')

        if not tvdb_id:
            logger.warning(f"Cannot enrich '{show_title}' - missing TVDB ID")
            return False

        logger.info(f"TVDB enriching '{show_title}' (TVDB: {tvdb_id})")

        try:
            series_data = tvdb_service.get_series_extended(tvdb_id)
            if not series_data:
                return False

            metadata = self._parse_tvdb_metadata(series_data)

            db = get_db()
            self._update_show_metadata(db, show_db_id, metadata)

            characters = tvdb_service.get_series_characters(tvdb_id)
            if characters:
                self._store_cast_data(db, tvdb_id, show_db_id, characters)

            db.commit()
            logger.info(f"Successfully enriched '{show_title}' from TheTVDB")
            return True

        except Exception as e:
            logger.error(f"Error enriching '{show_title}' from TVDB: {e}", exc_info=True)
            try:
                get_db().rollback()
            except Exception:
                pass
            return False

    def _parse_tvdb_metadata(self, series_data: Dict) -> Dict:
        """Parse TheTVDB API response into metadata"""
        # Get overview from translations or direct field
        overview = ''
        translations = series_data.get('translations', {})
        if translations and translations.get('overviewTranslations'):
            for trans in translations['overviewTranslations']:
                if trans.get('language') == 'eng':
                    overview = trans.get('overview', '')
                    break
        if not overview:
            overview = series_data.get('overview', '')
        if overview:
            overview = re.sub(r'<[^>]+>', '', overview)

        # Genres
        genres = series_data.get('genres', [])
        genre_names = [g.get('name') for g in genres if g.get('name')]
        genres_json = json.dumps(genre_names) if genre_names else None

        # Network
        network_name = None
        network_country = None
        networks = series_data.get('networks', [])
        original_network = series_data.get('originalNetwork', {})
        if original_network:
            network_name = original_network.get('name')
            network_country = original_network.get('country')
        elif networks:
            network_name = networks[0].get('name')
            network_country = networks[0].get('country')

        # Runtime
        runtime = series_data.get('averageRuntime')

        # Rating/score
        rating = series_data.get('score')

        return {
            'premiered': series_data.get('firstAired'),
            'ended': series_data.get('lastAired') if series_data.get('status', {}).get('name') == 'Ended' else None,
            'tvmaze_summary': overview,  # Reuse the same column
            'genres': genres_json,
            'network_name': network_name,
            'network_country': network_country,
            'runtime': runtime,
            'tvmaze_rating': rating,  # Reuse the same column
        }

    def _update_show_metadata(self, db, show_db_id: int, metadata: Dict):
        """Update sonarr_shows with TVDB metadata"""
        db.execute("""
            UPDATE sonarr_shows
            SET premiered = ?, ended = ?,
                tvmaze_summary = ?, genres = ?, network_name = ?,
                network_country = ?, runtime = ?, tvmaze_rating = ?,
                tvdb_enriched_at = CURRENT_TIMESTAMP,
                enrichment_source = 'tvdb'
            WHERE id = ?
        """, (
            metadata.get('premiered'), metadata.get('ended'),
            metadata.get('tvmaze_summary'), metadata.get('genres'),
            metadata.get('network_name'), metadata.get('network_country'),
            metadata.get('runtime'), metadata.get('tvmaze_rating'),
            show_db_id
        ))

    def _store_cast_data(self, db, tvdb_id: int, show_db_id: int, characters: List[Dict]):
        """Store cast from TheTVDB data"""
        # Clear existing cast for this show
        db.execute("DELETE FROM show_cast WHERE show_id = ? OR show_tvdb_id = ?",
                   (show_db_id, tvdb_id))

        for idx, char in enumerate(characters):
            person_name = char.get('personName')
            character_name = char.get('name')

            if not person_name or not character_name:
                continue

            person_img = char.get('personImgURL') or None
            char_img = char.get('image') or None
            sort_order = char.get('sort') if char.get('sort') is not None else idx
            people_id = char.get('peopleId')

            # Determine if voice role from peopleType or type field
            people_type = char.get('peopleType', '')
            is_voice = 'voice' in people_type.lower() if people_type else False

            db.execute("""
                INSERT INTO show_cast (
                    show_id, show_tvdb_id, show_tvmaze_id,
                    person_id, person_name, person_image_url,
                    character_id, character_name, character_image_url,
                    cast_order, is_voice, enrichment_source
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'tvdb')
            """, (
                show_db_id, tvdb_id,
                people_id, person_name, person_img,
                char.get('id'), character_name, char_img,
                sort_order, is_voice
            ))


# Global instance
thetvdb_enrichment_service = TheTVDBEnrichmentService()
