#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Productivity Agent
Google Sheets + Ollama Gemma + Telegram Integration
একটা single file এ সম্পূর্ণ system
"""

import os
import json
import sys
import subprocess
import requests
from datetime import datetime
from collections import Counter
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load configuration from config.json
def load_config():
    """config.json থেকে সব settings load করে"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print("❌ config.json file পাওয়া যাচ্ছে না!")
        return None
    except json.JSONDecodeError:
        print("❌ config.json file ঠিকমতো parse করতে পারিনি!")
        return None

# Load config
CONFIG = load_config()

if CONFIG:
    # Google Sheets credential - config.json এর ভিতর থেকেই নিব
    CREDENTIAL_DATA = CONFIG['google_sheets']['credentials']
    SPREADSHEET_ID = CONFIG['google_sheets']['spreadsheet_id']
    PLANNING_SHEET = CONFIG['google_sheets']['sheets']['planning']
    TASKLIST_SHEET = CONFIG['google_sheets']['sheets']['tasklist']
    TELEGRAM_IDS_SHEET = CONFIG['google_sheets']['sheets']['telegram_ids']
    OLLAMA_MODEL = CONFIG['ai_model']['name']
    TELEGRAM_BOT_TOKEN = CONFIG['telegram']['bot_token']
    TELEGRAM_CHAT_IDS = CONFIG['telegram']['chat_ids']
else:
    print("⚠️ Config load করতে পারিনি! Default values ব্যবহার করছি...")
    CREDENTIAL_DATA = None
    SPREADSHEET_ID = ""
    PLANNING_SHEET = "TASKS_PLAN"
    TASKLIST_SHEET = "TASKLIST"
    TELEGRAM_IDS_SHEET = "telegram IDs"
    OLLAMA_MODEL = "gemma3:1b"
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_IDS = []

# Google Sheets API scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


# ============================================================================
# GOOGLE SHEETS FUNCTIONS
# ============================================================================

def get_google_sheets_service():
    """Google Sheets API service create করে"""
    try:
        # Credential data config.json থেকে সরাসরি নিই
        if CREDENTIAL_DATA:
            creds = Credentials.from_service_account_info(
                CREDENTIAL_DATA,
                scopes=SCOPES
            )
        else:
            print("❌ Google Sheets credentials পাওয়া যাচ্ছে না!")
            return None
        
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Google Sheets connection error: {e}")
        return None


def read_sheet_data(service, spreadsheet_id, sheet_name):
    """Google Sheet থেকে data read করে"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheet_name
        ).execute()
        
        values = result.get('values', [])
        return values
    
    except HttpError as e:
        print(f"❌ Sheet '{sheet_name}' পড়তে error: {e}")
        return None


# ============================================================================
# DATA PARSING FUNCTIONS
# ============================================================================

def parse_planning_data(data):
    """TASKS_PLAN sheet থেকে আজকের task list বের করে
    
    Expected columns:
    A: Sl
    B: Planning (task name)
    C: Tag
    D: Target Time in Minute
    E: Frequency (Daily/Weekly)
    F: Description
    G: Frequency (Today/Weekly indicator)
    """
    tasks = []
    
    if not data or len(data) < 2:
        return tasks
    
    # Skip header (row 1)
    for row in data[1:]:
        if len(row) < 4:  # At least need columns A-D
            continue
        
        try:
            task = {
                'sl': row[0] if len(row) > 0 else '',
                'name': row[1] if len(row) > 1 else '',
                'tag': row[2] if len(row) > 2 else '',
                'target_time': row[3] if len(row) > 3 else '',
                'frequency': row[4] if len(row) > 4 else '',
                'description': row[5] if len(row) > 5 else '',
                'when': row[6] if len(row) > 6 else ''
            }
            
            # Filter: শুধু "Today" tasks নেব
            if task['when'] and 'today' in str(task['when']).lower():
                if task['name']:  # Only add if task has a name
                    tasks.append(task)
        except Exception as e:
            continue
    
    return tasks


def parse_tasklist_data(data):
    """TASKLIST sheet থেকে আজকের actual time log বের করে
    
    Actual structure from your sheet:
    A: Sl number (1, 2, 3)
    B: Empty or number
    C: Date (তারিখ - 1, 2, 3...)
    D: Task name with tag (e.g., "Sleeping (Sleep)", "With Iroan (Family Time)")
    E: Time info or duration
    """
    logs = []
    
    if not data or len(data) < 2:
        return logs
    
    # প্রথমে Jun' 2026 section খুঁজি
    current_month = None
    in_current_month = False
    
    for row_idx, row in enumerate(data):
        # Month header খুঁজি
        if len(row) > 0 and isinstance(row[0], str):
            if "jun" in str(row[0]).lower() and "2026" in str(row[0]).lower():
                in_current_month = True
                current_month = row[0]
                continue
        
        # Parse করি - Column D তে task name থাকে
        if len(row) >= 4:
            task_name = row[3] if len(row) > 3 else ''  # Column D
            
            if task_name and task_name.strip() and len(task_name) > 3:
                try:
                    log = {
                        'sl': row[0] if len(row) > 0 else '',
                        'date': row[2] if len(row) > 2 else '',  # Column C - date
                        'task': task_name,  # Column D - task name
                        'time_or_duration': row[4] if len(row) > 4 else '',  # Column E
                        'extra_info': row[5] if len(row) > 5 else ''
                    }
                    
                    # Extract tag from task name (text in parentheses)
                    if '(' in task_name and ')' in task_name:
                        tag = task_name[task_name.find('(')+1:task_name.find(')')]
                        log['tag'] = tag
                    else:
                        log['tag'] = ''
                    
                    logs.append(log)
                except Exception as e:
                    continue
    
    return logs


# ============================================================================
# AI ANALYSIS FUNCTIONS
# ============================================================================

def analyze_productivity(planning_tasks, actual_logs):
    """Planning আর actual data তুলনা করে productivity analysis করে"""
    
    analysis = {
        'total_planned_tasks': len(planning_tasks),
        'total_logged_activities': len(actual_logs),
        'tags_summary': {},
        'sleep_activities': [],
        'productive_activities': [],
        'time_wasted_activities': []
    }
    
    # Tag-wise activity count
    tag_counter = Counter()
    
    for log in actual_logs:
        tag = log.get('tag', 'Unknown')
        if tag:
            tag_counter[tag] += 1
            
            # Sleep detection
            if 'sleep' in tag.lower():
                analysis['sleep_activities'].append(log)
            
            # Productive tags
            productive_tags = ['ERP', 'Business', 'Coding', 'Learning', 'Reading', 'Work']
            if any(pt.lower() in tag.lower() for pt in productive_tags):
                analysis['productive_activities'].append(log)
            
            # Time wasted tags
            waste_tags = ['Social Media', 'Gossip', 'Random', 'Facebook']
            if any(wt.lower() in tag.lower() for wt in waste_tags):
                analysis['time_wasted_activities'].append(log)
    
    analysis['tags_summary'] = dict(tag_counter.most_common(10))
    
    return analysis


def generate_ai_report(planning_tasks, actual_logs, analysis):
    """AI দিয়ে report তৈরি করে"""
    
    top_tags = list(analysis['tags_summary'].items())[:5]
    
    report = f"""
📊 **Productivity Report - {datetime.now().strftime('%d %B %Y')}**

✅ Planning: {analysis['total_planned_tasks']} টি task
📝 Logged: {analysis['total_logged_activities']} টি activity

🏷️ Top 5 Tags:
"""
    
    for tag, count in top_tags:
        report += f"   • {tag}: {count} বার\n"
    
    report += f"""
😴 Sleep: {len(analysis['sleep_activities'])} টি
💼 Productive: {len(analysis['productive_activities'])} টি
⏰ Time Wasted: {len(analysis['time_wasted_activities'])} টি

"""
    
    # Judgment
    if len(analysis['sleep_activities']) > 5:
        report += "⚠️ **বেশি ঘুমাচ্ছো! কাজে মন দাও!**\n"
    
    if len(analysis['time_wasted_activities']) > len(analysis['productive_activities']):
        report += "❌ **সময় নষ্ট বেশি, productive কাজ কম!**\n"
    else:
        report += "🎉 **ভালো productivity! চালিয়ে যাও!**\n"
    
    return report


# ============================================================================
# TELEGRAM FUNCTIONS
# ============================================================================

def send_telegram_message(bot_token, chat_id, message):
    """Telegram এ message পাঠায়"""
    
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except:
        return False


def send_to_multiple_chats(bot_token, chat_ids, message):
    """একাধিক chat এ message পাঠায়"""
    
    success_count = 0
    for chat_id in chat_ids:
        if send_telegram_message(bot_token, chat_id, message):
            success_count += 1
    return success_count


def read_telegram_ids_from_sheet(service, spreadsheet_id):
    """telegram IDs sheet থেকে chat IDs পড়ে"""
    
    try:
        data = read_sheet_data(service, spreadsheet_id, TELEGRAM_IDS_SHEET)
        if not data:
            return []
        
        chat_ids = []
        for row in data[1:]:
            if len(row) > 0 and row[0]:
                chat_id = str(row[0]).strip()
                if chat_id:
                    chat_ids.append(chat_id)
        return chat_ids
    except:
        return []


# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def test_sheet_reading():
    """Google Sheet থেকে data read করে parse করে দেখায়"""
    
    print("="*70)
    print("🧪 AI PRODUCTIVITY AGENT - Data Reading Test")
    print("="*70)
    
    # Check config loaded
    if not CONFIG:
        print(f"\n❌ Config file load করতে পারিনি!")
        return False
    
    print(f"✅ Config loaded from config.json\n")
    
    # Connect to Google Sheets
    print("🔌 Google Sheets এ connect করছি...")
    service = get_google_sheets_service()
    
    if not service:
        return False
    
    print("✅ Connection successful!\n")
    
    # ========================================
    # 1. Read TASKS_PLAN Sheet
    # ========================================
    print("="*70)
    print("📋 STEP 1: Reading TASKS_PLAN (Planning Sheet)")
    print("="*70)
    
    planning_data = read_sheet_data(service, SPREADSHEET_ID, PLANNING_SHEET)
    
    if not planning_data:
        print(f"❌ '{PLANNING_SHEET}' sheet পড়তে পারিনি!")
        return False
    
    print(f"✅ Total {len(planning_data)} rows in planning sheet")
    
    # Parse planning data
    today_tasks = parse_planning_data(planning_data)
    
    print(f"\n📌 আজকের জন্য {len(today_tasks)} টি task পাওয়া গেছে:\n")
    print("-" * 70)
    
    for i, task in enumerate(today_tasks[:10], 1):
        print(f"{i}. {task['name']}")
        print(f"   Tag: {task['tag']}")
        print(f"   Target: {task['target_time']}")
        print(f"   Frequency: {task['frequency']}")
        print()
    
    if len(today_tasks) > 10:
        print(f"... আরও {len(today_tasks) - 10} টি task আছে\n")
    
    # ========================================
    # 2. Read TASKLIST Sheet
    # ========================================
    print("="*70)
    print("📊 STEP 2: Reading TASKLIST (Actual Time Tracking)")
    print("="*70)
    
    tasklist_data = read_sheet_data(service, SPREADSHEET_ID, TASKLIST_SHEET)
    
    if not tasklist_data:
        print(f"❌ '{TASKLIST_SHEET}' sheet পড়তে পারিনি!")
        return False
    
    print(f"✅ Total {len(tasklist_data)} rows in tasklist sheet")
    
    # Parse tasklist data
    actual_logs = parse_tasklist_data(tasklist_data)
    
    print(f"\n📝 মোট {len(actual_logs)} টি activity log পাওয়া গেছে")
    print(f"\nপ্রথম ১০টি log:\n")
    print("-" * 70)
    
    for i, log in enumerate(actual_logs[:10], 1):
        print(f"{i}. {log['task']}")
        print(f"   Date: {log['date']} | Tag: {log.get('tag', 'N/A')} | Duration: {log['time_or_duration']}")
    
    if len(actual_logs) > 10:
        print(f"\n... আরও {len(actual_logs) - 10} টি log entry আছে\n")
    
    # ========================================
    # 3. Summary
    # ========================================
    print("="*70)
    print("📊 SUMMARY")
    print("="*70)
    
    print(f"""
✅ Data Reading Successful!

Planning Sheet:
   • Total rows: {len(planning_data)}
   • Today's tasks: {len(today_tasks)}

Tasklist Sheet:
   • Total rows: {len(tasklist_data)}
   • Activity logs: {len(actual_logs)}

🎯 Next Steps:
   1. ✅ Google Sheet connection - WORKING
   2. ✅ Data parsing - WORKING  
   3. ⏳ AI analysis - Coming next
   4. ⏳ Telegram integration - Coming next
""")
    
    return True


# ============================================================================
# FULL ANALYSIS & NOTIFICATION FUNCTION
# ============================================================================

def run_full_analysis():
    """সম্পূর্ণ analysis চালায় এবং notification পাঠায়"""
    
    print("\n" + "="*70)
    print("🤖 AI PRODUCTIVITY ANALYSIS")
    print("="*70 + "\n")
    
    # Connect to Google Sheets
    service = get_google_sheets_service()
    if not service:
        return False
    
    # Read data
    print("📥 Data loading...")
    planning_data = read_sheet_data(service, SPREADSHEET_ID, PLANNING_SHEET)
    tasklist_data = read_sheet_data(service, SPREADSHEET_ID, TASKLIST_SHEET)
    
    if not planning_data or not tasklist_data:
        print("❌ Data পড়তে পারিনি!")
        return False
    
    # Parse data
    today_tasks = parse_planning_data(planning_data)
    actual_logs = parse_tasklist_data(tasklist_data)
    
    print(f"✅ Planning: {len(today_tasks)} tasks")
    print(f"✅ Logged: {len(actual_logs)} activities\n")
    
    # Analyze
    print("🔍 Analyzing productivity...")
    analysis = analyze_productivity(today_tasks, actual_logs)
    
    # Generate report
    print("📊 Generating report...\n")
    report = generate_ai_report(today_tasks, actual_logs, analysis)
    
    print(report)
    
    # Get AI advice (optional - comment out যদি Ollama না চাও)
    # ai_advice = ask_ollama_for_advice(report)
    # print(f"\n🤖 AI Advice:\n{ai_advice}\n")
    
    # Send to Telegram
    if TELEGRAM_BOT_TOKEN:
        print("="*70)
        print("📱 Sending to Telegram...")
        print("="*70 + "\n")
        
        # Read chat IDs from sheet if not manually set
        chat_ids = TELEGRAM_CHAT_IDS
        if not chat_ids:
            chat_ids = read_telegram_ids_from_sheet(service, SPREADSHEET_ID)
        
        if chat_ids:
            # Combine report + AI advice
            full_message = report
            # if ai_advice:
            #     full_message += f"\n💬 AI বলছে:\n{ai_advice}"
            
            success = send_to_multiple_chats(TELEGRAM_BOT_TOKEN, chat_ids, full_message)
            print(f"✅ {success}/{len(chat_ids)} টি chat এ message পাঠানো হয়েছে!")
        else:
            print("⚠️ কোনো Telegram chat ID পাওয়া যায়নি!")
            print("   TELEGRAM_CHAT_IDS list এ manually ID দাও অথবা")
            print("   'telegram IDs' sheet এ chat IDs রাখো")
    else:
        print("\n⚠️ Telegram bot token set করা নেই!")
        print("   TELEGRAM_BOT_TOKEN variable এ token দাও")
    
    return True


# ============================================================================
# MAIN PROGRAM
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Productivity Agent')
    parser.add_argument('--mode', choices=['test', 'analyze', 'notify'], 
                       default='test',
                       help='Run mode: test (data reading), analyze (full analysis), notify (analysis + telegram)')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("🚀 AI PRODUCTIVITY AGENT")
    print("   Google Sheets + Ollama Gemma + Telegram")
    print("="*70 + "\n")
    
    if args.mode == 'test':
        # Phase 1: Test data reading
        success = test_sheet_reading()
        
        if success:
            print("\n" + "="*70)
            print("✅ Phase 1 Complete - Data Reading Working!")
            print("="*70)
            print("\n💡 Next: Run with --mode analyze for full analysis")
            print("   Example: python ai_agent.py --mode analyze")
        else:
            print("\n" + "="*70)
            print("❌ Test Failed")
            print("="*70)
    
    elif args.mode == 'analyze':
        # Phase 2: Full analysis (without telegram)
        success = run_full_analysis()
        
        if success:
            print("\n" + "="*70)
            print("✅ Analysis Complete!")
            print("="*70)
    
    elif args.mode == 'notify':
        # Phase 3: Analysis + Telegram notification
        success = run_full_analysis()
        
        if success:
            print("\n" + "="*70)
            print("✅ Notification Sent!")
            print("="*70)
