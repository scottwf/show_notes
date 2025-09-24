"""
Migration: Create recap_sites table for dynamic scraper management

This migration creates a table to store configuration for different recap sites,
allowing admins to add new sites and LLM-generated scraping rules.
"""

import sqlite3
import os
from datetime import datetime

def upgrade():
    """Create the recap_sites table"""
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'show_notes.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create recap_sites table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recap_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT NOT NULL UNIQUE,
            base_url TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            rate_limit_seconds INTEGER DEFAULT 30,
            user_agent TEXT,
            link_patterns TEXT,  -- JSON array of regex patterns
            title_patterns TEXT,  -- JSON array of regex patterns for episode info
            content_patterns TEXT,  -- JSON array of regex patterns for content extraction
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create index for faster lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_recap_sites_active 
        ON recap_sites(is_active)
    ''')
    
    # Insert default sites (Vulture and Showbiz Junkies)
    default_sites = [
        {
            'site_name': 'Vulture',
            'base_url': 'https://www.vulture.com',
            'is_active': 1,
            'rate_limit_seconds': 30,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'link_patterns': '["<a[^>]+href=\\"([^\\"]*\\/article\\/[^\\"]*recap[^\\"]*)\\"[^>]*>([^<]+)<\\/a>", "<a[^>]+href=\\"([^\\"]*\\/article\\/[^\\"]*recap[^\\"]*)\\"[^>]*>.*?<span[^>]*>([^<]+)<\\/span>.*?<\\/a>"]',
            'title_patterns': '["Season\\\\s+(\\\\d+).*Episode\\\\s+(\\\\d+)", "S(\\\\d+)E(\\\\d+)", "Episode\\\\s+(\\\\d+)"]',
            'content_patterns': '["<div[^>]*class=\\"[^\\"]*article-content[^\\"]*\\"[^>]*>(.*?)<\\/div>", "<div[^>]*class=\\"[^\\"]*content[^\\"]*\\"[^>]*>(.*?)<\\/div>"]'
        },
        {
            'site_name': 'Showbiz Junkies',
            'base_url': 'https://www.showbizjunkies.com',
            'is_active': 1,
            'rate_limit_seconds': 30,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'link_patterns': '["<a[^>]+href=\\"([^\\"]*\\/tv\\/[^\\"]*recap[^\\"]*)\\"[^>]*>([^<]+)<\\/a>", "<a[^>]+href=\\"([^\\"]*\\/tv-recaps\\/[^\\"]*)\\"[^>]*>([^<]+)<\\/a>"]',
            'title_patterns': '["Season\\\\s+(\\\\d+).*Episode\\\\s+(\\\\d+)", "S(\\\\d+)E(\\\\d+)", "Episode\\\\s+(\\\\d+)"]',
            'content_patterns': '["<div[^>]*class=\\"[^\\"]*entry-content[^\\"]*\\"[^>]*>(.*?)<\\/div>", "<article[^>]*>(.*?)<\\/article>"]'
        }
    ]
    
    for site in default_sites:
        cursor.execute('''
            INSERT OR IGNORE INTO recap_sites 
            (site_name, base_url, is_active, rate_limit_seconds, user_agent, 
             link_patterns, title_patterns, content_patterns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            site['site_name'], site['base_url'], site['is_active'], 
            site['rate_limit_seconds'], site['user_agent'],
            site['link_patterns'], site['title_patterns'], site['content_patterns']
        ))
    
    conn.commit()
    conn.close()
    print("✅ Created recap_sites table with default configurations")

def downgrade():
    """Remove the recap_sites table"""
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'show_notes.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS recap_sites')
    cursor.execute('DROP INDEX IF EXISTS idx_recap_sites_active')
    
    conn.commit()
    conn.close()
    print("✅ Removed recap_sites table")

if __name__ == "__main__":
    upgrade()
