import os
import json
import re
import sys
import requests
from datetime import datetime
from collections import Counter, defaultdict
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Fix Windows console encoding issues for emojis/UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def load_config():
    """Loads all settings from config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ config.json file not found! Please run from the Agent_AI directory.")
        sys.exit(1)

def get_google_sheets_service(config):
    """Creates Google Sheets API service"""
    creds_data = config['google_sheets']['credentials']
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return build('sheets', 'v4', credentials=creds)

def parse_tag(task_name):
    """Extracts tag from task name like 'Sleeping (Sleep)' -> 'Sleep'"""
    if not task_name:
        return ''
    if '(' in task_name and ')' in task_name:
        return task_name[task_name.find('(')+1:task_name.find(')')].strip()
    return ''

def get_behavioral_profile():
    config = load_config()
    spreadsheet_id = config['google_sheets']['spreadsheet_id']
    sheet_name = config['google_sheets']['sheets']['tasklist']
    
    print("📥 Loading all rows from Google Sheets...")
    service = get_google_sheets_service(config)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_name
    ).execute()
    
    rows = result.get('values', [])
    print(f"✅ Loaded {len(rows)} rows.")
    
    month_pattern = re.compile(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*['\s]+(20\d{2})$",
        re.IGNORECASE
    )
    
    # Organize data chronologically by month blocks
    # We will aggregate daily sleep, productive work, and wasted time
    daily_stats = defaultdict(lambda: {"sleep": 0.0, "productive": 0.0, "wasted": 0.0, "tasks": []})
    
    current_month = "unknown"
    current_year = 0
    
    all_tags = []
    wasted_examples = []
    productive_examples = []
    
    productive_tags = {'erp', 'business', 'coding', 'learning', 'reading', 'work', 'family time', 'vibe coding', 'office accounts', 'office work pmd', 'office work others', 'javascript', 'personal administrative'}
    waste_tags = {'social media', 'gossip', 'random', 'facebook', 'lewd', 'entertainment', 'listening political views', 'listening song', 'gossiping'}
    
    for idx, row in enumerate(rows):
        if idx == 0:
            continue
        if len(row) > 2:
            cell_val = str(row[2]).strip()
            match = month_pattern.match(cell_val)
            if match:
                current_month = match.group(1).lower()[:3]
                current_year = int(match.group(2))
                continue
                
        if current_month == "unknown" or len(row) <= 3:
            continue
            
        try:
            date_val = str(row[2]).strip()
            # Try to get integer day
            try:
                day = int(float(date_val))
            except ValueError:
                continue
                
            task_name = str(row[3]).strip()
            if not task_name:
                continue
                
            tag = parse_tag(task_name).lower()
            if tag:
                all_tags.append(tag)
                
            # Get duration
            duration = 0.0
            if len(row) > 9:
                try:
                    duration = float(str(row[9]).strip())
                except ValueError:
                    pass
            
            # Key identifier for unique day
            day_key = f"{current_year}-{current_month}-{day}"
            
            if 'sleep' in tag:
                daily_stats[day_key]["sleep"] += duration
            elif any(pt in tag for pt in productive_tags):
                daily_stats[day_key]["productive"] += duration
                if len(productive_examples) < 50:
                    productive_examples.append(task_name)
            elif any(wt in tag for wt in waste_tags):
                daily_stats[day_key]["wasted"] += duration
                if len(wasted_examples) < 50:
                    wasted_examples.append(task_name)
                    
            daily_stats[day_key]["tasks"].append(task_name)
        except Exception:
            continue
            
    # Calculate statistics over the last 30 active days
    active_days = sorted(daily_stats.keys())[-30:]
    if not active_days:
        print("❌ No active days found in the tasklist!")
        sys.exit(1)
        
    avg_sleep = sum(daily_stats[d]["sleep"] for d in active_days) / len(active_days)
    avg_productive = sum(daily_stats[d]["productive"] for d in active_days) / len(active_days)
    avg_wasted = sum(daily_stats[d]["wasted"] for d in active_days) / len(active_days)
    
    tag_counts = Counter(all_tags).most_common(10)
    
    # Format the profile summary
    profile_summary = f"""
=== Historical Behavioral Profile (Last 30 Active Days) ===
- Number of analyzed days: {len(active_days)}
- Average daily sleep: {avg_sleep:.2f} hours
- Average daily productive work: {avg_productive:.2f} hours
- Average daily wasted time: {avg_wasted:.2f} hours
- Productive to Wasted ratio: {avg_productive / (avg_wasted if avg_wasted > 0 else 0.1):.2f}x

- Top 10 tags in history:
"""
    for t, count in tag_counts:
        profile_summary += f"  * {t}: {count} times\n"
        
    profile_summary += "\n- Frequently logged time-wasting activities (examples):\n"
    # Take a unique sample of up to 15 time-wasting tasks
    unique_wasted = list(set(wasted_examples))[:15]
    for w in unique_wasted:
        profile_summary += f"  * {w}\n"
        
    profile_summary += "\n- Frequently logged productive activities (examples):\n"
    unique_productive = list(set(productive_examples))[:15]
    for p in unique_productive:
        profile_summary += f"  * {p}\n"
        
    return profile_summary, config

def generate_behavioral_evaluation(profile, config):
    print("🤖 Sending behavioral profile to Groq AI for critical evaluation...")
    
    api_key = config['ai_model']['online']['groq']['api_key']
    model = config['ai_model']['online']['groq']['model']
    
    prompt = f"""
You are a highly perceptive, blunt, and strict personal growth and productivity psychologist.
Analyze the following historical activity profile of the user. 
Provide a deep, critical psychological assessment of their behavior. Do not sugarcoat anything. Call out their patterns, distractions, and lack of focus.

Based on this assessment, generate:
1. A summary of who they are and what their main productivity bottleneck is (e.g., sleeping too much, escaping work via social media/lewd searches, poor time allocation).
2. exactly 10 direct, highly critical, and strict diagnostic questions/guidelines customized to their weakness. Make sure they are hard-hitting and provoke self-reflection.

Format the entire output in clean Markdown.

--- User Profile ---
{profile}
---
"""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict, blunt productivity psychologist. Respond in English."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2048
    }
    
    resp = requests.post(url, headers=headers, json=data, timeout=45)
    if resp.status_code == 200:
        result = resp.json()
        evaluation = result['choices'][0]['message']['content']
        return evaluation
    else:
        raise Exception(f"Groq API returned error {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    try:
        profile, config = get_behavioral_profile()
        evaluation = generate_behavioral_evaluation(profile, config)
        
        # Save evaluation to file
        output_file = "behavioral_evaluation.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(evaluation)
            
        print("\n" + "="*80)
        print("🤖 DEEP BEHAVIORAL EVALUATION GENERATED!")
        print("="*80)
        print(evaluation)
        print("\n" + "="*80)
        print(f"Saved evaluation report to: {os.path.abspath(output_file)}")
        print("="*80)
    except Exception as e:
        print(f"❌ Error: {e}")
