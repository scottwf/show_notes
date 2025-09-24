#!/usr/bin/env python3

import sqlite3
import json
import requests
import re
import html as html_module
import urllib.parse
from datetime import datetime

def test_show_scraping():
    # Connect to database
    conn = sqlite3.connect('instance/shownotes.sqlite3')
    conn.row_factory = sqlite3.Row
    db = conn.cursor()
    
    # Test with Task show
    show_title = "Task"
    tmdb_id = "253941"  # Task show ID
    
    print(f"Testing show scraping for: {show_title} (TMDB ID: {tmdb_id})")
    
    # Get active recap sites from database
    sites = db.execute("""
        SELECT site_name, base_url, link_patterns, title_patterns, content_patterns, 
               rate_limit_seconds, user_agent, sample_urls
        FROM recap_sites 
        WHERE is_active = 1
    """).fetchall()
    
    print(f"Found {len(sites)} active recap sites")
    
    if not sites:
        print("No active recap sites configured!")
        return
    
    # Scrape recaps using dynamic patterns
    all_recaps = []
    
    for site in sites:
        try:
            site_name = site['site_name']
            base_url = site['base_url']
            link_patterns = json.loads(site['link_patterns'] or '[]')
            title_patterns = json.loads(site['title_patterns'] or '[]')
            content_patterns = json.loads(site['content_patterns'] or '[]')
            
            print(f"\nSite {site_name}:")
            print(f"  Link patterns: {len(link_patterns)}")
            print(f"  Title patterns: {len(title_patterns)}")
            print(f"  Content patterns: {len(content_patterns)}")
            
            if not link_patterns or not title_patterns or not content_patterns:
                print(f"  WARNING: Empty patterns for {site_name}")
                continue
            
            rate_limit = site['rate_limit_seconds'] or 30
            user_agent = site['user_agent'] or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            
            headers = {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            site_recaps = []
            
            # First, try to use sample URLs if they contain our show
            sample_urls = json.loads(site['sample_urls'] or '[]')
            print(f"  Sample URLs: {len(sample_urls)}")
            
            for sample_url in sample_urls:
                if sample_url and show_title.lower() in sample_url.lower():
                    print(f"  Found matching sample URL: {sample_url}")
                    try:
                        # Extract title from URL for initial matching
                        parsed_url = urllib.parse.urlparse(sample_url)
                        path_parts = [part for part in parsed_url.path.split('/') if part]
                        url_title = path_parts[-1].replace('-', ' ').title() if path_parts else sample_url
                        
                        # Scrape the detailed recap directly
                        detailed_recap = scrape_detailed_recap(
                            sample_url, url_title, site_name, title_patterns, content_patterns, headers
                        )
                        if detailed_recap:
                            detailed_recap['tmdb_id'] = tmdb_id
                            detailed_recap['source'] = site_name
                            site_recaps.append(detailed_recap)
                            print(f"  Successfully scraped: {detailed_recap['title']}")
                        
                        # Rate limiting
                        import time
                        time.sleep(rate_limit)
                        
                    except Exception as e:
                        print(f"  Error scraping sample URL {sample_url}: {e}")
                        continue
            
            all_recaps.extend(site_recaps)
            print(f"  Found {len(site_recaps)} recaps from {site_name}")
            
        except Exception as e:
            print(f"Error processing site {site_name}: {e}")
            continue
    
    print(f"\nTotal recaps found: {len(all_recaps)}")
    for recap in all_recaps:
        print(f"  - {recap['title']} (S{recap['season']}E{recap['episode']}) from {recap['source']}")
    
    conn.close()

def scrape_detailed_recap(url, title, site_name, title_patterns, content_patterns, headers):
    """Scrape detailed recap from a specific URL using dynamic patterns"""
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"    HTTP {response.status_code} for {url}")
            return None
        
        html = response.text
        
        # Extract title - try multiple methods
        final_title = title
        
        # Method 1: Try h1 tags first
        h1_matches = re.findall(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        if h1_matches:
            for h1_text in h1_matches:
                h1_clean = h1_text.strip()
                if not any(social in h1_clean.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                    final_title = h1_clean
                    break
        
        # Method 2: Try title tag if h1 didn't work
        if final_title == title:
            title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                title_text = title_match.group(1).strip()
                if not any(social in title_text.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                    final_title = title_text
        
        # Method 3: Extract from URL if title tag is overridden
        if final_title == title or any(social in final_title.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
            parsed_url = urllib.parse.urlparse(url)
            path_parts = [part for part in parsed_url.path.split('/') if part]
            if path_parts:
                url_title = path_parts[-1].replace('-', ' ').title()
                final_title = url_title
        
        # Decode HTML entities
        final_title = html_module.unescape(final_title)
        
        # Extract episode info from title
        episode_info = None
        for pattern in title_patterns:
            try:
                match = re.search(pattern, final_title, re.IGNORECASE)
                if match:
                    if len(match.groups()) == 2:
                        episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                    elif len(match.groups()) == 1:
                        episode_info = {'season': 1, 'episode': int(match.group(1))}
                    break
            except Exception as e:
                print(f"    Error with title pattern '{pattern}': {e}")
                continue
        
        # If no episode info in title, try to extract from URL
        if not episode_info:
            parsed_url = urllib.parse.urlparse(url)
            path_parts = [part for part in parsed_url.path.split('/') if part]
            
            # Look for episode patterns in URL path
            url_patterns = [
                r'episode-(\d+)',  # episode-3
                r'episode(\d+)',   # episode3
                r's(\d+)e(\d+)',   # s1e3
                r'season-(\d+)-episode-(\d+)',  # season-1-episode-3
                r'season(\d+)episode(\d+)',     # season1episode3
            ]
            
            for part in path_parts:
                for pattern in url_patterns:
                    try:
                        match = re.search(pattern, part, re.IGNORECASE)
                        if match:
                            if len(match.groups()) == 2:
                                episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                            elif len(match.groups()) == 1:
                                episode_info = {'season': 1, 'episode': int(match.group(1))}
                            break
                    except Exception as e:
                        print(f"    Error with URL pattern '{pattern}': {e}")
                        continue
                if episode_info:
                    break
        
        if not episode_info:
            print(f"    No episode info found for {url}")
            return None
        
        # Extract content using patterns
        content = ""
        for pattern in content_patterns:
            try:
                match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                if match:
                    content = match.group(1)
                    break
            except Exception as e:
                print(f"    Error with content pattern '{pattern}': {e}")
                continue
        
        if not content:
            print(f"    No content found for {url}")
            return None
        
        # Extract paragraphs from content
        paragraph_pattern = r'<p[^>]*>(.*?)</p>'
        paragraphs = re.findall(paragraph_pattern, content, re.DOTALL | re.IGNORECASE)
        
        summary_parts = []
        for p in paragraphs:
            text = re.sub(r'<[^>]+>', '', p).strip()
            if text and len(text) > 50:
                summary_parts.append(text)
        
        summary = ' '.join(summary_parts[:5])
        
        if not summary:
            print(f"    No summary extracted for {url}")
            return None
        
        return {
            'title': final_title,
            'season': episode_info['season'],
            'episode': episode_info['episode'],
            'summary': summary,
            'url': url,
            'source_provider': site_name
        }
        
    except Exception as e:
        print(f"    Error scraping detailed recap from {url}: {e}")
        return None

if __name__ == "__main__":
    test_show_scraping()
