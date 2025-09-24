#!/usr/bin/env python3

import sqlite3
import json

def fix_show_snob_patterns():
    # Connect to database
    conn = sqlite3.connect('instance/shownotes.sqlite3')
    db = conn.cursor()
    
    # Generate patterns for Show Snob based on the sample URLs
    link_patterns = [
        r'<a[^>]+href="([^"]*)"[^>]*>([^<]*recap[^<]*)</a>',
        r'<a[^>]+href="([^"]*)"[^>]*>([^<]*episode[^<]*)</a>'
    ]
    
    title_patterns = [
        r'Season\s+(\d+).*Episode\s+(\d+)',
        r'S(\d+)E(\d+)',
        r'Episode\s+(\d+)',
        r'season-(\d+)-episode-(\d+)',
        r'episode-(\d+)'
    ]
    
    content_patterns = [
        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>'
    ]
    
    # Update Show Snob with the patterns
    db.execute("""
        UPDATE recap_sites 
        SET link_patterns = ?, title_patterns = ?, content_patterns = ?
        WHERE site_name = 'Show Snob'
    """, (
        json.dumps(link_patterns),
        json.dumps(title_patterns), 
        json.dumps(content_patterns)
    ))
    
    conn.commit()
    
    # Verify the update
    result = db.execute("SELECT site_name, link_patterns, title_patterns, content_patterns FROM recap_sites WHERE site_name = 'Show Snob'").fetchone()
    print("Updated Show Snob patterns:")
    print(f"Site: {result[0]}")
    print(f"Link patterns: {json.loads(result[1])}")
    print(f"Title patterns: {json.loads(result[2])}")
    print(f"Content patterns: {json.loads(result[3])}")
    
    conn.close()

if __name__ == "__main__":
    fix_show_snob_patterns()
