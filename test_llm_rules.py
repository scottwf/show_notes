#!/usr/bin/env python3

import requests
import json

def test_llm_rules():
    # Test the LLM rule generation endpoint
    url = "http://localhost:5000/admin/api/generate-scraping-rules"
    
    data = {
        "site_name": "Show Snob",
        "base_url": "https://showsnob.com/",
        "sample_urls": [
            "https://showsnob.com/black-rabbit-season-1-episode-8-recap-netflix",
            "https://showsnob.com/task-season-1-episode-2-recap-hbo",
            "https://showsnob.com/task-season-1-episode-1-recap"
        ]
    }
    
    print("Testing LLM rule generation...")
    print(f"Data: {json.dumps(data, indent=2)}")
    
    try:
        response = requests.post(url, json=data, timeout=30)
        print(f"Response status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                rules = result.get('rules', {})
                print(f"Generated rules:")
                print(f"Link patterns: {json.loads(rules.get('link_patterns', '[]'))}")
                print(f"Title patterns: {json.loads(rules.get('title_patterns', '[]'))}")
                print(f"Content patterns: {json.loads(rules.get('content_patterns', '[]'))}")
            else:
                print(f"Error: {result.get('error')}")
        else:
            print(f"HTTP Error: {response.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_llm_rules()
