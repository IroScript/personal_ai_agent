# -*- coding: utf-8 -*-
"""
Playwright Google My Activity Continuous Ingestion Worker
Uses Playwright with Chrome and authenticated session cookies to extract
Google My Activity stream and stream it to the REST API and SQLite database.
"""

import os
import sys
import json
import time
import re
import argparse
import urllib.parse
import sqlite3
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
COOKIE_FILE = BASE_DIR / "tools" / "CloakBrowserForGoogleActivity" / "1aa245cf-837c-4bf3-89e4-af24bc4a8c96.json"
CACHED_JSON = BASE_DIR / "data" / "chrome" / "scraped_google_activity_cookies.json"
DB_PATH = BASE_DIR / "data" / "chrome" / "chrome_history_master.db"
DEFAULT_API_URL = os.environ.get("API_URL", "http://127.0.0.1:8085")

PRODUCT_ENDPOINTS = [
    ('Main Activity Feed', 'https://myactivity.google.com/myactivity?hl=en'),
    ('Android Apps & Usage', 'https://myactivity.google.com/product/android?hl=en'),
    ('Google Search', 'https://myactivity.google.com/product/search?hl=en'),
    ('YouTube (Watch & Search)', 'https://myactivity.google.com/product/youtube?hl=en'),
    ('Google Maps & Directions', 'https://myactivity.google.com/product/maps?hl=en'),
    ('Google Play Store', 'https://myactivity.google.com/product/google_play?hl=en'),
    ('Chrome Web Activity', 'https://myactivity.google.com/product/chrome?hl=en'),
    ('AI Mode / Gemini', 'https://myactivity.google.com/product/gemini?hl=en'),
]

def clean_google_url(raw_url: str) -> str:
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

def load_cookies():
    if not COOKIE_FILE.exists():
        print(f"⚠️ Warning: Cookie file not found at {COOKIE_FILE}")
        return []
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_items_from_html(html: str, product_name: str) -> list:
    """Parses activities from AF_initDataCallback or JSON embedded structures."""
    extracted = []
    callbacks = re.findall(r'AF_initDataCallback\((.*?)\);</script>', html, re.DOTALL)
    for cb in callbacks:
        if len(cb) < 500:
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
                    'timestamp_micro': int(ts_micro),
                    'timestamp_utc': dt_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    'timestamp_bd': dt_bd.strftime('%Y-%m-%d %H:%M:%S'),
                    'product': product_name,
                    'app_name': app_name,
                    'action': action_type,
                    'title': title_clean,
                    'url': url,
                    'details': None,
                    'raw_data': {'raw_item': item},
                    'source': 'playwright_google_activity'
                })
        except Exception:
            continue

    return extracted

def parse_cached_json_items() -> list:
    """Loads existing items from scraped_google_activity_cookies.json with microsecond timestamps."""
    if not CACHED_JSON.exists():
        return []
    try:
        with open(CACHED_JSON, 'r', encoding='utf-8') as f:
            raw_items = json.load(f)
    except Exception as e:
        print(f"Error loading cached JSON: {e}")
        return []

    items = []
    base_ts = int(datetime(2026, 9, 17, 9, 44, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)

    for idx, r in enumerate(raw_items):
        action_text = r.get("action_text", "")
        app_service = r.get("app_service", "Google")
        context_details = r.get("context_details", "")
        
        # Determine action and title
        action = "Used"
        title = action_text
        if action_text.startswith("Visited "):
            action = "Visited"
            title = action_text[len("Visited "):]
        elif action_text.startswith("Searched for "):
            action = "Searched"
            title = action_text[len("Searched for "):]
        elif action_text.startswith("Watched "):
            action = "Watched"
            title = action_text[len("Watched "):]

        # Synthesize unique timestamp descending
        ts_micro = base_ts - (idx * 60_000_000)
        dt_utc = datetime.fromtimestamp(ts_micro / 1_000_000, tz=timezone.utc)
        dt_bd = dt_utc + timedelta(hours=6)

        items.append({
            'timestamp_micro': ts_micro,
            'timestamp_utc': dt_utc.strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp_bd': dt_bd.strftime('%Y-%m-%d %H:%M:%S'),
            'product': app_service,
            'app_name': app_service,
            'action': action,
            'title': title,
            'url': None,
            'details': context_details,
            'raw_data': r,
            'source': 'playwright_cached_google_activity'
        })
    return items

def scrape_with_playwright() -> list:
    """Uses Playwright to navigate Google My Activity pages and extract activities."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not found in current environment!")
        return []

    raw_cookies = load_cookies()
    if not raw_cookies:
        print("❌ No cookies available for Playwright scraping!")
        return []

    cookies_to_add = []
    for c in raw_cookies:
        cookie_dict = {
            'name': c['name'],
            'value': c['value'],
            'domain': c['domain'],
            'path': c.get('path', '/'),
        }
        if c.get('secure') is not None:
            cookie_dict['secure'] = c['secure']
        if c.get('httpOnly') is not None:
            cookie_dict['httpOnly'] = c['httpOnly']
        cookies_to_add.append(cookie_dict)

    all_items = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        context.add_cookies(cookies_to_add)
        page = context.new_page()

        for product_name, url in PRODUCT_ENDPOINTS:
            try:
                print(f"  🔍 [Playwright] Navigating to {product_name}...")
                page.goto(url, wait_until='networkidle', timeout=25000)
                html = page.content()

                # 1. Parse from script callbacks
                items = parse_items_from_html(html, product_name)
                
                # 2. Parse from DOM cards if script callbacks empty
                if not items:
                    # Look for activity cards
                    cards = page.query_selector_all('c-wiz div[role="article"], div[data-item-id]')
                    for card in cards:
                        try:
                            card_text = card.inner_text().strip()
                            if card_text:
                                lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                                if lines:
                                    now_u = datetime.now(timezone.utc)
                                    ts_m = int(now_u.timestamp() * 1_000_000)
                                    items.append({
                                        'timestamp_micro': ts_m,
                                        'timestamp_utc': now_u.strftime('%Y-%m-%d %H:%M:%S'),
                                        'timestamp_bd': (now_u + timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S'),
                                        'product': product_name,
                                        'app_name': product_name,
                                        'action': 'Activity Card',
                                        'title': lines[0][:200],
                                        'url': page.url,
                                        'details': ' \n '.join(lines[1:4]),
                                        'raw_data': {'lines': lines},
                                        'source': 'playwright_dom_card'
                                    })
                        except Exception:
                            continue

                added = 0
                for it in items:
                    key = (it['timestamp_micro'], it['title'], it['product'])
                    if key not in seen:
                        seen.add(key)
                        all_items.append(it)
                        added += 1

                print(f"  ✅ {product_name}: {len(items)} extracted ({added} unique)")
            except Exception as e:
                print(f"  ⚠️ {product_name} scan error: {e}")

        browser.close()

    return all_items

def ingest_into_rest_api(items: list, api_url: str = DEFAULT_API_URL) -> dict:
    """Sends batch of items to the REST API server."""
    if not items:
        return {"status": "skipped", "inserted": 0, "duplicates": 0}

    url = f"{api_url.rstrip('/')}/api/v1/activity/batch"
    payload = {"activities": items}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"⚠️ REST API returned HTTP {resp.status_code}: {resp.text}")
            return {"status": "error", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        print(f"⚠️ Failed to connect to REST API at {url}: {e}")
        return {"status": "connection_error", "error": str(e)}

def ingest_direct_sqlite(items: list) -> dict:
    """Direct SQLite fallback ingestion in case REST API is unavailable."""
    if not items:
        return {"inserted": 0, "duplicates": 0}
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    inserted = 0
    duplicates = 0
    ingested_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    try:
        with conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            for it in items:
                raw_json = json.dumps(it.get('raw_data') or {}, ensure_ascii=False)
                cur = conn.execute("""
                    INSERT OR IGNORE INTO google_activity (
                        timestamp_micro, timestamp_utc, timestamp_bd, product, app_name,
                        action, title, url, details, raw_data, source, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    it['timestamp_micro'], it['timestamp_utc'], it['timestamp_bd'],
                    it['product'], it.get('app_name'), it.get('action'),
                    it.get('title'), it.get('url'), it.get('details'),
                    raw_json, it.get('source', 'direct_sqlite'), ingested_at
                ))
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    duplicates += 1
        return {"inserted": inserted, "duplicates": duplicates}
    except Exception as e:
        print(f"❌ Direct SQLite insert failed: {e}")
        return {"error": str(e)}
    finally:
        conn.close()

def run_sync_cycle(api_url: str = DEFAULT_API_URL):
    print(f"\n==================================================")
    print(f"🕒 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Google My Activity Sync Cycle")
    print(f"==================================================")

    # 1. Scrape via Playwright
    playwright_items = scrape_with_playwright()

    # 2. Also incorporate cached historical activities
    cached_items = parse_cached_json_items()
    print(f"📦 Cached historical items available: {len(cached_items)}")

    # Combine items, unique by timestamp_micro
    combined = {}
    for it in cached_items:
        combined[it['timestamp_micro']] = it
    for it in playwright_items:
        combined[it['timestamp_micro']] = it

    total_items = list(combined.values())
    print(f"📊 Total items prepared for ingestion: {len(total_items)}")

    # 3. Ingest via REST API
    api_res = ingest_into_rest_api(total_items, api_url=api_url)
    print(f"🌐 REST API Ingestion Result: {api_res}")

    # 4. If REST API had error or was not reachable, fallback to direct SQLite
    if api_res.get("status") in ["error", "connection_error"]:
        print("🔄 Falling back to direct SQLite insertion...")
        sqlite_res = ingest_direct_sqlite(total_items)
        print(f"💾 Direct SQLite Ingestion Result: {sqlite_res}")

    return len(total_items)

def main():
    parser = argparse.ArgumentParser(description="Playwright Google My Activity Ingestion Worker")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background daemon loop")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds between sync cycles (default: 300)")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL, help=f"Target REST API URL (default: {DEFAULT_API_URL})")
    args = parser.parse_args()

    if args.daemon:
        print(f"🔁 Starting Continuous Daemon Mode (Interval: {args.interval}s, API: {args.api_url})...")
        while True:
            try:
                run_sync_cycle(api_url=args.api_url)
            except Exception as e:
                print(f"❌ Error in sync cycle: {e}")
            print(f"⏳ Sleeping for {args.interval} seconds...")
            time.sleep(args.interval)
    else:
        run_sync_cycle(api_url=args.api_url)

if __name__ == "__main__":
    main()
