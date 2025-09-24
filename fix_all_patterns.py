#!/usr/bin/env python3

import sqlite3
import json

def fix_all_patterns():
    # Connect to database
    conn = sqlite3.connect('instance/shownotes.sqlite3')
    db = conn.cursor()
    
    # Common patterns that work for most recap sites
    link_patterns = [
        r'<a[^>]+href="([^"]*)"[^>]*>([^<]*recap[^<]*)</a>',
        r'<a[^>]+href="([^"]*)"[^>]*>([^<]*episode[^<]*)</a>'
    ]
    
    title_patterns = [
        r'Season\s+(\d+).*Episode\s+(\d+)',
        r'S(\d+)E(\d+)',
        r'Episode\s+(\d+)',
        r'episode-(\d+)',
        r'season-(\d+)-episode-(\d+)'
    ]
    
    content_patterns = [
        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>'
    ]
    
    # Update all sites with empty patterns
    sites_to_fix = ['Showbiz Junkies', 'The Review Geek']
    
    for site_name in sites_to_fix:
        db.execute("""
            UPDATE recap_sites 
            SET link_patterns = ?, title_patterns = ?, content_patterns = ?
            WHERE site_name = ? AND (link_patterns = '[]' OR link_patterns IS NULL)
        """, (
            json.dumps(link_patterns),
            json.dumps(title_patterns), 
            json.dumps(content_patterns),
            site_name
        ))
        
        print(f"Updated {site_name} patterns")
    
    conn.commit()
    
    # Show all sites and their patterns
    results = db.execute("SELECT site_name, link_patterns, title_patterns, content_patterns FROM recap_sites WHERE is_active = 1").fetchall()
    
    print("\nAll active sites and their patterns:")
    for result in results:
        site_name, link_p, title_p, content_p = result
        print(f"\n{site_name}:")
        print(f"  Link patterns: {json.loads(link_p) if link_p else 'None'}")
        print(f"  Title patterns: {json.loads(title_p) if title_p else 'None'}")
        print(f"  Content patterns: {json.loads(content_p) if content_p else 'None'}")
    
    conn.close()

if __name__ == "__main__":
    fix_all_patterns()
