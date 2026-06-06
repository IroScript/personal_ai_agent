#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Productivity Agent - Main Script
Google Sheets + Multiple AI Providers (Groq, Gemini, OpenAI, Anthropic, Local) + Telegram
Fallback chain: Groq → Gemini → OpenAI → Anthropic → Local Ollama
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

CONFIG = load_config()

if CONFIG:
    CREDENTIAL_DATA = CONFIG['google_sheets']['credentials']
    SPREADSHEET_ID = CONFIG['google_sheets']['spreadsheet_id']
    PLANNING_SHEET = CONFIG['google_sheets']['sheets']['planning']
    TASKLIST_SHEET = CONFIG['google_sheets']['sheets']['tasklist']
    TELEGRAM_IDS_SHEET = CONFIG['google_sheets']['sheets']['telegram_ids']
    
    # AI Provider settings
    AI_PROVIDERS = CONFIG['ai_model']['online']
    LOCAL_MODEL = CONFIG['ai_model']['local']
    
    TELEGRAM_BOT_TOKEN = CONFIG['telegram']['bot_token']
    TELEGRAM_CHAT_IDS = CONFIG['telegram']['chat_ids']
else:
    print("⚠️ Config load করতে পারিনি!")
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


# ============================================================================
# GOOGLE SHEETS FUNCTIONS (Same as local version)
# ============================================================================

def get_google_sheets_service():
    """Google Sheets API service create করে"""
    try:
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
# DATA PARSING FUNCTIONS (Same as local version)
# ============================================================================

def parse_planning_data(data):
    """TASKS_PLAN sheet থেকে আজকের task list বের করে"""
    tasks = []
    
    if not data or len(data) < 2:
        return tasks
    
    for row in data[1:]:
        if len(row) < 4:
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
            
            if task['when'] and 'today' in str(task['when']).lower():
                if task['name']:
                    tasks.append(task)
        except Exception as e:
            continue
    
    return tasks


def parse_tasklist_data(data):
    """TASKLIST sheet থেকে আজকের actual time log বের করে"""
    logs = []
    
    if not data or len(data) < 2:
        return logs
    
    for row_idx, row in enumerate(data):
        if len(row) > 0 and isinstance(row[0], str):
            if "jun" in str(row[0]).lower() and "2026" in str(row[0]).lower():
                in_current_month = True
                continue
        
        if len(row) >= 4:
            task_name = row[3] if len(row) > 3 else ''
            
            if task_name and task_name.strip() and len(task_name) > 3:
                try:
                    log = {
                        'sl': row[0] if len(row) > 0 else '',
                        'date': row[2] if len(row) > 2 else '',
                        'task': task_name,
                        'time_or_duration': row[4] if len(row) > 4 else '',
                        'extra_info': row[5] if len(row) > 5 else ''
                    }
                    
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
# MULTI-PROVIDER AI FUNCTIONS
# ============================================================================

def call_groq_api(prompt, api_key, model):
    """Groq API call করে"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "তুমি একজন strict productivity coach। সংক্ষেপে বাংলায় উত্তর দাও।"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            print(f"⚠️ Groq API error: {response.status_code}")
            return None
    
    except Exception as e:
        print(f"⚠️ Groq API call failed: {e}")
        return None


def call_gemini_api(prompt, api_key, model):
    """Google Gemini API call করে"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        headers = {"Content-Type": "application/json"}
        
        data = {
            "contents": [{
                "parts": [{
                    "text": f"তুমি একজন strict productivity coach। সংক্ষেপে বাংলায় উত্তর দাও।\n\n{prompt}"
                }]
            }]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"⚠️ Gemini API error: {response.status_code}")
            return None
    
    except Exception as e:
        print(f"⚠️ Gemini API call failed: {e}")
        return None


def call_openai_api(prompt, api_key, model):
    """OpenAI API call করে"""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "তুমি একজন strict productivity coach। সংক্ষেপে বাংলায় উত্তর দাও।"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            print(f"⚠️ OpenAI API error: {response.status_code}")
            return None
    
    except Exception as e:
        print(f"⚠️ OpenAI API call failed: {e}")
        return None


def call_anthropic_api(prompt, api_key, model):
    """Anthropic Claude API call করে"""
    try:
        url = "https://api.anthropic.com/v1/messages"
        
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "max_tokens": 500,
            "messages": [
                {"role": "user", "content": f"তুমি একজন strict productivity coach। সংক্ষেপে বাংলায় উত্তর দাও।\n\n{prompt}"}
            ]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['content'][0]['text']
        else:
            print(f"⚠️ Anthropic API error: {response.status_code}")
            return None
    
    except Exception as e:
        print(f"⚠️ Anthropic API call failed: {e}")
        return None


def call_local_ollama(prompt, model):
    """Local Ollama model call করে"""
    try:
        result = subprocess.run(
            ['ollama', 'run', model, prompt],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode == 0:
            response = result.stdout.strip()
            if ">>>" in response:
                response = response.split(">>>")[0].strip()
            return response
        else:
            print(f"⚠️ Ollama error: {result.stderr}")
            return None
    
    except Exception as e:
        print(f"⚠️ Ollama call failed: {e}")
        return None


def get_ai_advice(report):
    """Multiple AI providers থেকে fallback chain দিয়ে advice নেয়
    
    Priority: Groq → Gemini → OpenAI → Anthropic → Local Ollama
    """
    
    prompt = f"""তুমি একজন strict productivity coach। নিচের report দেখে user কে একটা ছোট motivational বা strict message দাও (maximum 3-4 লাইন, বাংলায়):

{report}

Message:"""
    
    providers_tried = []
    
    # 1. Try Groq first
    if AI_PROVIDERS['groq']['enabled'] and AI_PROVIDERS['groq']['api_key']:
        print("🔹 Trying Groq API...")
        providers_tried.append("Groq")
        response = call_groq_api(
            prompt,
            AI_PROVIDERS['groq']['api_key'],
            AI_PROVIDERS['groq']['model']
        )
        if response:
            print(f"✅ Got response from Groq!")
            return response, "Groq"
    
    # 2. Try Gemini
    if AI_PROVIDERS['gemini']['enabled'] and AI_PROVIDERS['gemini']['api_key']:
        print("🔹 Trying Gemini API...")
        providers_tried.append("Gemini")
        response = call_gemini_api(
            prompt,
            AI_PROVIDERS['gemini']['api_key'],
            AI_PROVIDERS['gemini']['model']
        )
        if response:
            print(f"✅ Got response from Gemini!")
            return response, "Gemini"
    
    # 3. Try OpenAI
    if AI_PROVIDERS['openai']['enabled'] and AI_PROVIDERS['openai']['api_key']:
        print("🔹 Trying OpenAI API...")
        providers_tried.append("OpenAI")
        response = call_openai_api(
            prompt,
            AI_PROVIDERS['openai']['api_key'],
            AI_PROVIDERS['openai']['model']
        )
        if response:
            print(f"✅ Got response from OpenAI!")
            return response, "OpenAI"
    
    # 4. Try Anthropic
    if AI_PROVIDERS['anthropic']['enabled'] and AI_PROVIDERS['anthropic']['api_key']:
        print("🔹 Trying Anthropic API...")
        providers_tried.append("Anthropic")
        response = call_anthropic_api(
            prompt,
            AI_PROVIDERS['anthropic']['api_key'],
            AI_PROVIDERS['anthropic']['model']
        )
        if response:
            print(f"✅ Got response from Anthropic!")
            return response, "Anthropic"
    
    # 5. Fallback to Local Ollama
    print("🔹 Trying Local Ollama...")
    providers_tried.append("Local Ollama")
    response = call_local_ollama(prompt, LOCAL_MODEL['model_name'])
    if response:
        print(f"✅ Got response from Local Ollama!")
        return response, "Local Ollama"
    
    # If all failed
    print(f"❌ All providers failed. Tried: {', '.join(providers_tried)}")
    return "Keep working hard! তোমার productivity improve করতে হবে! 💪", "Fallback"


# ============================================================================
# ANALYSIS FUNCTIONS (Same as local)
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
    
    tag_counter = Counter()
    
    for log in actual_logs:
        tag = log.get('tag', 'Unknown')
        if tag:
            tag_counter[tag] += 1
            
            if 'sleep' in tag.lower():
                analysis['sleep_activities'].append(log)
            
            productive_tags = ['ERP', 'Business', 'Coding', 'Learning', 'Reading', 'Work']
            if any(pt.lower() in tag.lower() for pt in productive_tags):
                analysis['productive_activities'].append(log)
            
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
    
    if len(analysis['sleep_activities']) > 5:
        report += "⚠️ **বেশি ঘুমাচ্ছো! কাজে মন দাও!**\n"
    
    if len(analysis['time_wasted_activities']) > len(analysis['productive_activities']):
        report += "❌ **সময় নষ্ট বেশি, productive কাজ কম!**\n"
    else:
        report += "🎉 **ভালো productivity! চালিয়ে যাও!**\n"
    
    return report


# ============================================================================
# TELEGRAM FUNCTIONS (Same as local)
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
# MAIN ANALYSIS FUNCTION
# ============================================================================

def run_full_analysis():
    """সম্পূর্ণ analysis + AI advice + notification"""
    
    print("\n" + "="*70)
    print("🤖 AI PRODUCTIVITY ANALYSIS (Online Multi-Provider)")
    print("="*70 + "\n")
    
    service = get_google_sheets_service()
    if not service:
        return False
    
    print("📥 Loading data...")
    planning_data = read_sheet_data(service, SPREADSHEET_ID, PLANNING_SHEET)
    tasklist_data = read_sheet_data(service, SPREADSHEET_ID, TASKLIST_SHEET)
    
    if not planning_data or not tasklist_data:
        return False
    
    today_tasks = parse_planning_data(planning_data)
    actual_logs = parse_tasklist_data(tasklist_data)
    
    print(f"✅ Planning: {len(today_tasks)} tasks")
    print(f"✅ Logged: {len(actual_logs)} activities\n")
    
    print("🔍 Analyzing...")
    analysis = analyze_productivity(today_tasks, actual_logs)
    
    report = generate_ai_report(today_tasks, actual_logs, analysis)
    print(report)
    
    # Get AI advice with fallback chain
    print("\n" + "="*70)
    print("🤖 Getting AI Advice...")
    print("="*70)
    ai_advice, provider_used = get_ai_advice(report)
    print(f"\n💬 AI Advice (via {provider_used}):\n{ai_advice}\n")
    
    # Send to Telegram
    if TELEGRAM_BOT_TOKEN:
        print("="*70)
        print("📱 Sending to Telegram...")
        
        chat_ids = TELEGRAM_CHAT_IDS or read_telegram_ids_from_sheet(service, SPREADSHEET_ID)
        
        if chat_ids:
            full_message = report + f"\n💬 AI বলছে:\n{ai_advice}\n\n_Powered by {provider_used}_"
            
            success = send_to_multiple_chats(TELEGRAM_BOT_TOKEN, chat_ids, full_message)
            print(f"✅ Sent to {success}/{len(chat_ids)} chats!")
        else:
            print("⚠️ No chat IDs found!")
    else:
        print("\n⚠️ Telegram bot token not set!")
    
    return True


# ============================================================================
# MAIN PROGRAM
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Productivity Agent (Online)')
    parser.add_argument('--mode', choices=['analyze', 'notify'], 
                       default='analyze',
                       help='Run mode: analyze (analysis only), notify (analysis + telegram)')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("🚀 AI PRODUCTIVITY AGENT - ONLINE VERSION")
    print("   Multi-Provider: Groq → Gemini → OpenAI → Anthropic → Local")
    print("="*70 + "\n")
    
    success = run_full_analysis()
    
    if success:
        print("\n" + "="*70)
        print("✅ Analysis Complete!")
        print("="*70)
    else:
        print("\n" + "="*70)
        print("❌ Analysis Failed")
        print("="*70)
