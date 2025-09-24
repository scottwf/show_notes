#!/usr/bin/env python3

import sqlite3
import json
import requests
import re
import html as html_module
import urllib.parse
from datetime import datetime

def test_task_scraping():
    # Connect to database
    conn = sqlite3.connect('instance/shownotes.sqlite3')
    conn.row_factory = sqlite3.Row
    db = conn.cursor()
    
    # Get Show Snob site data
    site = db.execute("SELECT * FROM recap_sites WHERE site_name = 'Show Snob' AND is_active = 1").fetchone()
    if not site:
        print("Show Snob site not found!")
        return
    
    site_dict = dict(site)
    print(f"Site: {site_dict['site_name']}")
    print(f"Base URL: {site_dict['base_url']}")
    
    # Parse patterns
    link_patterns = json.loads(site_dict['link_patterns'] or '[]')
    title_patterns = json.loads(site_dict['title_patterns'] or '[]')
    content_patterns = json.loads(site_dict['content_patterns'] or '[]')
    
    print(f"Link patterns: {link_patterns}")
    print(f"Title patterns: {title_patterns}")
    print(f"Content patterns: {content_patterns}")
    
    # Get sample URLs
    sample_urls = json.loads(site_dict['sample_urls'] or '[]')
    print(f"Sample URLs: {sample_urls}")
    
    # Test with Task show
    show_title = "Task"
    print(f"\nTesting with show: {show_title}")
    
    # Check which sample URLs contain "task"
    task_urls = [url for url in sample_urls if show_title.lower() in url.lower()]
    print(f"Task URLs found: {task_urls}")
    
    if not task_urls:
        print("No Task URLs found in sample URLs!")
        return
    
    # Test scraping the first Task URL
    test_url = task_urls[0]
    print(f"\nTesting URL: {test_url}")
    
    # Headers
    headers = {
        'User-Agent': site_dict['user_agent'] or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # Fetch the page
        print("Fetching page...")
        response = requests.get(test_url, headers=headers, timeout=10)
        print(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Failed to fetch page: {response.status_code}")
            return
        
        html = response.text
        print(f"HTML length: {len(html)}")
        
        # Extract title
        print("\nExtracting title...")
        final_title = "Task Season 1 Episode 1 Recap"  # Default
        
        # Method 1: Try h1 tags first
        h1_matches = re.findall(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        print(f"H1 matches: {h1_matches}")
        if h1_matches:
            for h1_text in h1_matches:
                h1_clean = h1_text.strip()
                if not any(social in h1_clean.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                    final_title = h1_clean
                    break
        
        # Method 2: Try title tag
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title_text = title_match.group(1).strip()
            if not any(social in title_text.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                final_title = title_text
        
        print(f"Final title: {final_title}")
        
        # Decode HTML entities
        final_title = html_module.unescape(final_title)
        print(f"Decoded title: {final_title}")
        
        # Extract episode info from title
        print("\nExtracting episode info from title...")
        episode_info = None
        for i, pattern in enumerate(title_patterns):
            print(f"Testing title pattern {i+1}: {pattern}")
            try:
                match = re.search(pattern, final_title, re.IGNORECASE)
                if match:
                    print(f"  Match found: {match.groups()}")
                    if len(match.groups()) == 2:
                        episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                    elif len(match.groups()) == 1:
                        episode_info = {'season': 1, 'episode': int(match.group(1))}
                    break
                else:
                    print(f"  No match")
            except Exception as e:
                print(f"  Error with pattern: {e}")
        
        if episode_info:
            print(f"Episode info from title: {episode_info}")
        else:
            print("No episode info found in title")
        
        # If no episode info in title, try to extract from URL
        if not episode_info:
            print("\nExtracting episode info from URL...")
            parsed_url = urllib.parse.urlparse(test_url)
            path_parts = [part for part in parsed_url.path.split('/') if part]
            print(f"URL path parts: {path_parts}")
            
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
                            print(f"URL pattern match: {pattern} -> {match.groups()}")
                            if len(match.groups()) == 2:
                                episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                            elif len(match.groups()) == 1:
                                episode_info = {'season': 1, 'episode': int(match.group(1))}
                            break
                    except Exception as e:
                        print(f"Error with URL pattern {pattern}: {e}")
                if episode_info:
                    break
        
        if episode_info:
            print(f"Final episode info: {episode_info}")
        else:
            print("No episode info found anywhere!")
            return
        
        # Extract content using patterns
        print("\nExtracting content...")
        content = ""
        for i, pattern in enumerate(content_patterns):
            print(f"Testing content pattern {i+1}: {pattern}")
            try:
                match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                if match:
                    content = match.group(1)
                    print(f"  Content found, length: {len(content)}")
                    break
                else:
                    print(f"  No content match")
            except Exception as e:
                print(f"  Error with content pattern: {e}")
        
        if content:
            print("Content extraction successful!")
            # Extract paragraphs
            paragraph_pattern = r'<p[^>]*>(.*?)</p>'
            paragraphs = re.findall(paragraph_pattern, content, re.DOTALL | re.IGNORECASE)
            print(f"Found {len(paragraphs)} paragraphs")
            
            summary_parts = []
            for p in paragraphs:
                text = re.sub(r'<[^>]+>', '', p).strip()
                if text and len(text) > 50:
                    summary_parts.append(text)
            
            summary = ' '.join(summary_parts[:5])
            print(f"Summary length: {len(summary)}")
            print(f"Summary preview: {summary[:200]}...")
        else:
            print("No content found!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    conn.close()

if __name__ == "__main__":
    test_task_scraping()
