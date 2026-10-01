# -*- coding: utf-8 -*-
import os
import sys
import json
import re
import csv
import sqlite3
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path('/home/mdkamruzzamanirak_gmail_com/.openclaw/workspace/IROSCRIPT-CEO/PERSONAL AI AGENT')
COOKIE_FILE = BASE_DIR / 'tools' / 'CloakBrowserForGoogleActivity' / '1aa245cf-837c-4bf3-89e4-af24bc4a8c96.json'
DATA_DIR = BASE_DIR / 'data' / 'chrome'
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = DATA_DIR / 'scraped_google_activity_cookies.json'
OUTPUT_CSV = DATA_DIR / 'scraped_google_activity_cookies.csv'
DB_PATH = DATA_DIR / 'chrome_history_master.db'

PRODUCT_ENDPOINTS = [
    ('Main Activity Feed', 'https://myactivity.google.com/myactivity?hl=en'),
    ('Android Apps & Usage', 'https://myactivity.google.com/product/android?hl=en'),
    ('Google Search', 'https://myactivity.google.com/product/search?hl=en'),
    ('YouTube (Watch & Search)', 'https://myactivity.google.com/product/youtube?hl=en'),
    ('Google Maps & Directions', 'https://myactivity.google.com/product/maps?hl=en'),
    ('Google Play Store', 'https://myactivity.google.com/product/google_play?hl=en'),
    ('Chrome Web Activity', 'https://myactivity.google.com/product/chrome?hl=en'),
    ('AI Mode / Gemini', 'https://myactivity.google.com/product/gemini?hl=en'),
    ('Google Assistant', 'https://myactivity.google.com/product/assistant?hl=en'),
    ('Google Drive', 'https://myactivity.google.com/product/drive?hl=en'),
    ('Google News', 'https://myactivity.google.com/product/news?hl=en'),
    ('Google Shopping', 'https://myactivity.google.com/product/shopping?hl=en')
]

def clean_google_url(raw_url):
    if not raw_url:
        return ''
    if 'google.com/url?' in raw_url:
        try:
            parsed = urllib.parse.urlparse(raw_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'q' in query_params:
                return query_params['q'][0]
            if 'url' in query_params:
                return query_params['url'][0]
        except Exception:
            pass
    return raw_url

def parse_items_from_html(html, product_name):
    callbacks = re.findall(r'AF_initDataCallback\((.*?)\);</script>', html, re.DOTALL)
    extracted = []
    
    for cb in callbacks:
        if len(cb) < 800:
            continue

        data_match = re.search(r'data:\s*(\[.*\])\s*,\s*sideChannel:', cb, re.DOTALL)
        if not data_match:
            data_match = re.search(r'data:\s*(\[.*\])\s*\}\s*$', cb.strip(), re.DOTALL)
        if not data_match:
            continue

        try:
            d = json.loads(data_match.group(1))
            if not isinstance(d, list) or len(d) == 0 or not isinstance(d[0], list):
                continue

            raw_items = d[0]
            for item in raw_items:
                if not isinstance(item, list) or len(item) < 10:
                    continue

                ts_micro = item[4] if len(item) > 4 and isinstance(item[4], (int, float)) else None
                if not ts_micro or ts_micro <= 0:
                    continue

                dt_utc = datetime.fromtimestamp(ts_micro / 1_000_000, tz=timezone.utc)
                dt_bd = dt_utc + timedelta(hours=6)
                datetime_utc_str = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
                datetime_bd_str = dt_bd.strftime('%Y-%m-%d %H:%M:%S')

                app_info = item[7] if len(item) > 7 and isinstance(item[7], list) else []
                app_name = app_info[0] if len(app_info) > 0 and app_info[0] else product_name

                act_info = item[9] if len(item) > 9 and isinstance(item[9], list) else []
                title = act_info[0] if len(act_info) > 0 and act_info[0] is not None else ''
                action_type = act_info[2] if len(act_info) > 2 and act_info[2] is not None else 'Used'
                raw_url = act_info[3] if len(act_info) > 3 and act_info[3] is not None else ''
                url = clean_google_url(raw_url)

                title_clean = re.sub(r'<[^>]+>', '', title).strip()
                if not title_clean and url:
                    title_clean = url

                extracted.append({
                    'timestamp_utc': datetime_utc_str,
                    'timestamp_bd': datetime_bd_str,
                    'timestamp_micro': ts_micro,
                    'product': product_name,
                    'app_name': app_name,
                    'action': action_type,
                    'title': title_clean,
                    'url': url
                })
        except Exception:
            continue
            
    return extracted

def run_scraper():
    print(f'[{datetime.now()}] 🌐 Starting Cloud Google My Activity Scraper...')
    if not COOKIE_FILE.exists():
        print(f'❌ Cookie file not found at: {COOKIE_FILE}')
        return
        
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        cookie_data = json.load(f)

    cookies = {}
    cookie_items = cookie_data if isinstance(cookie_data, list) else cookie_data.get('cookies', [])
    for c in cookie_items:
        if isinstance(c, dict) and 'name' in c and 'value' in c:
            cookies[c['name']] = c['value']

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://myactivity.google.com/'
    })

    all_items = []
    seen = set()

    for product_name, url in PRODUCT_ENDPOINTS:
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200:
                items = parse_items_from_html(resp.text, product_name)
                added = 0
                for it in items:
                    key = (it['timestamp_micro'], it['title'], it['product'])
                    if key not in seen:
                        seen.add(key)
                        all_items.append(it)
                        added += 1
                print(f'  ✅ {product_name}: {len(items)} found ({added} new)')
            else:
                print(f'  ⚠️ {product_name}: HTTP {resp.status_code}')
        except Exception as e:
            print(f'  ❌ {product_name} error: {e}')

    all_items.sort(key=lambda x: x['timestamp_micro'], reverse=True)
    print(f'\n📊 Total Unique Activities Extracted: {len(all_items)}')

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_items, f, indent=2, ensure_ascii=False)
    print(f'💾 Saved to JSON: {OUTPUT_JSON}')

if __name__ == '__main__':
    run_scraper()
