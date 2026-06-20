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

# Fix Windows console encoding issues for emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
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
    """Loads all settings from config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print("❌ config.json file not found!")
        return None
    except json.JSONDecodeError:
        print("❌ Failed to parse config.json file!")
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
    print("⚠️ Failed to load configuration!")
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


# ============================================================================
# GOOGLE SHEETS FUNCTIONS (Same as local version)
# ============================================================================

def get_google_sheets_service():
    """Creates Google Sheets API service"""
    try:
        if CREDENTIAL_DATA:
            creds = Credentials.from_service_account_info(
                CREDENTIAL_DATA,
                scopes=SCOPES
            )
        else:
            print("❌ Google Sheets credentials not found!")
            return None
        
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Google Sheets connection error: {e}")
        return None


def read_sheet_data(service, spreadsheet_id, sheet_name):
    """Reads data from Google Sheet"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheet_name
        ).execute()
        
        values = result.get('values', [])
        return values
    
    except HttpError as e:
        print(f"❌ Error reading sheet '{sheet_name}': {e}")
        return None


# ============================================================================
# DATA PARSING FUNCTIONS (Same as local version)
# ============================================================================

def parse_planning_data(data):
    """Extracts today's task list from TASKS_PLAN sheet"""
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
                'frequency_detail': row[6] if len(row) > 6 else '',
                'skip': row[7] if len(row) > 7 else '',
                'when': row[8] if len(row) > 8 else ''  # Column I contains "Today"
            }
            
            if task['when'] and 'today' in str(task['when']).lower():
                if task['name']:
                    tasks.append(task)
        except Exception as e:
            continue
    
    return tasks


def calculate_duration_in_hours(start_str, end_str):
    """Calculates task duration in hours from start and end times"""
    try:
        start_str = start_str.strip().replace('.', ':')
        end_str = end_str.strip().replace('.', ':')
        if not start_str or not end_str:
            return 0.0
        
        # Parse times (Format e.g., "12:00 AM", "10:30 AM")
        start_time = datetime.strptime(start_str, "%I:%M %p")
        end_time = datetime.strptime(end_str, "%I:%M %p")
        
        # If end time is before start time, it means it crossed midnight
        if end_time < start_time:
            diff = (end_time - start_time).total_seconds() + 24 * 3600
        else:
            diff = (end_time - start_time).total_seconds()
            
        return diff / 3600.0
    except Exception:
        return 0.0


def filter_current_month_data(data):
    """
    Filters and returns only the rows of the TASKLIST data that belong to the current month.
    It identifies month blocks dynamically by looking for cell values matching month headers (e.g. Jun' 2026) in Column C.
    """
    import re
    
    if not data or len(data) < 2:
        return data
        
    # Match patterns like: Jun' 2026, JAN' 2026, May 2026, etc. in Column C (index 2)
    month_pattern = re.compile(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*['\s]+(20\d{2})$",
        re.IGNORECASE
    )
    
    # Identify the start index of all month blocks in the sheet
    month_blocks = [] # List of tuples: (month_name, year, start_row_idx)
    
    for idx, row in enumerate(data):
        if len(row) > 2:
            cell_val = str(row[2]).strip()
            match = month_pattern.match(cell_val)
            if match:
                month_name = match.group(1).lower()[:3]
                year = int(match.group(2))
                month_blocks.append((month_name, year, idx))
                
    if not month_blocks:
        # Default fallback: return all data if no headers found
        return data
        
    # Sort blocks by their row index in the sheet
    month_blocks.sort(key=lambda x: x[2])
    
    # Get current month and year
    now = datetime.now()
    months_map = {
        1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
        7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"
    }
    current_month = months_map[now.month]
    current_year = now.year
    
    # Find the block matching the current month and year
    target_block_idx = -1
    for i, block in enumerate(month_blocks):
        if block[0] == current_month and block[1] == current_year:
            target_block_idx = i
            break
            
    if target_block_idx == -1:
        # If current month block is not found, default to the first block (newest block at the top)
        target_block_idx = 0
        
    start_idx = month_blocks[target_block_idx][2]
    
    # The block ends where the next month block starts, or at the end of the sheet data
    if target_block_idx + 1 < len(month_blocks):
        end_idx = month_blocks[target_block_idx + 1][2]
    else:
        end_idx = len(data)
        
    # Return only the slice belonging to the current month (preserving header at index 0)
    header = [data[0]] if len(data) > 0 else []
    return header + data[start_idx:end_idx]


def parse_tasklist_data(data):
    """Extracts today's actual time log from TASKLIST sheet"""
    logs = []
    
    if not data or len(data) < 2:
        return logs
        
    # Filter only the current month block dynamically
    data = filter_current_month_data(data)
        
    today_day = str(datetime.now().day)
    
    for row_idx, row in enumerate(data):
        # We need at least up to Column D (index 3) to get the task name
        if len(row) > 3:
            # Column C (index 2) contains date
            date_val = str(row[2]).strip()
            
            # Clean and normalize date to match today_day
            normalized_day = ""
            try:
                normalized_day = str(int(float(date_val)))
            except ValueError:
                normalized_day = date_val
                
            if normalized_day == today_day:
                task_name = str(row[3]).strip()  # Column D (index 3) contains task name with tag
                
                if task_name and len(task_name) > 3:
                    start_time = str(row[5]).strip() if len(row) > 5 else '' # Column F (index 5)
                    end_time = str(row[6]).strip() if len(row) > 6 else ''   # Column G (index 6)
                    
                    # Read sheet duration from Column J (index 9)
                    sheet_duration = 0.0
                    if len(row) > 9:
                        try:
                            sheet_duration = float(str(row[9]).strip())
                        except ValueError:
                            pass
                    
                    # Perform python-side calculation for verification
                    calculated_duration = calculate_duration_in_hours(start_time, end_time)
                    
                    # Verification check: If calculated duration is valid and differs from sheet, prioritize verified one
                    if calculated_duration > 0:
                        final_duration = calculated_duration
                    else:
                        final_duration = sheet_duration
                    
                    log = {
                        'sl': date_val,
                        'task': task_name,
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration': final_duration,
                        'sheet_duration': sheet_duration,
                        'calculated_duration': calculated_duration
                    }
                    
                    # Extract tag from task name like "Sleeping (Sleep)" -> "Sleep"
                    if '(' in task_name and ')' in task_name:
                        tag = task_name[task_name.find('(')+1:task_name.find(')')]
                        log['tag'] = tag.strip()
                    else:
                        log['tag'] = ''
                    
                    logs.append(log)
    
    return logs


# ============================================================================
# MULTI-PROVIDER AI FUNCTIONS
# ============================================================================

def call_groq_api(prompt, api_key, model):
    """Calls Groq API"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a strict productivity coach. Respond concisely in Bengali."},
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
    """Calls Google Gemini API"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        headers = {"Content-Type": "application/json"}
        
        data = {
            "contents": [{
                "parts": [{
                    "text": f"You are a strict productivity coach. Respond concisely in Bengali.\n\n{prompt}"
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
    """Calls OpenAI API"""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a strict productivity coach. Respond concisely in Bengali."},
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
    """Calls Anthropic Claude API"""
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
                {"role": "user", "content": f"You are a strict productivity coach. Respond concisely in Bengali.\n\n{prompt}"}
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
    """Calls local Ollama model"""
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
    """Takes advice from multiple AI providers using a fallback chain
    
    Priority: Groq → Gemini → OpenAI → Anthropic → Local Ollama
    """
    
    prompt = f"""You are a strict productivity coach. Based on the following report, give the user a short motivational or strict message (maximum 3-4 lines, in English):

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
    return "Keep working hard! You need to improve your productivity! 💪", "Fallback"


# ============================================================================
# ANALYSIS FUNCTIONS (Same as local)
# ============================================================================

def analyze_productivity(planning_tasks, actual_logs):
    """Compares planning and actual data to analyze productivity"""
    
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
            
            productive_tags = ['erp', 'business', 'coding', 'learning', 'reading', 'work', 'family time']
            if any(pt.lower() in tag.lower() for pt in productive_tags):
                analysis['productive_activities'].append(log)
            
            waste_tags = ['social media', 'gossip', 'random', 'facebook']
            if any(wt.lower() in tag.lower() for wt in waste_tags):
                analysis['time_wasted_activities'].append(log)
    
    analysis['tags_summary'] = dict(tag_counter.most_common(10))
    
    return analysis


def generate_ai_report(planning_tasks, actual_logs, analysis):
    """Generates report using AI"""
    
    top_tags = list(analysis['tags_summary'].items())[:5]
    
    total_sleep_hours = sum(log.get('duration', 0.0) for log in analysis['sleep_activities'])
    total_productive_hours = sum(log.get('duration', 0.0) for log in analysis['productive_activities'])
    total_wasted_hours = sum(log.get('duration', 0.0) for log in analysis['time_wasted_activities'])
    
    report = f"""
📊 **Productivity Report - {datetime.now().strftime('%d %B %Y')}**

✅ Planning: {analysis['total_planned_tasks']} tasks
📝 Logged: {analysis['total_logged_activities']} activities

🏷️ Top 5 Tags:
"""
    
    for tag, count in top_tags:
        report += f"   • {tag}: {count} times\n"
    
    report += f"""
😴 Sleep: {len(analysis['sleep_activities'])} logs ({total_sleep_hours:.2f} hr)
💼 Productive: {len(analysis['productive_activities'])} logs ({total_productive_hours:.2f} hr)
⏰ Time Wasted: {len(analysis['time_wasted_activities'])} logs ({total_wasted_hours:.2f} hr)
"""

    if total_sleep_hours > 9.5:
        report += "⚠️ **Sleeping too much! Focus on your work!**\n"
    
    if total_wasted_hours > total_productive_hours:
        report += "❌ **Too much wasted time, not enough productive work!**\n"
    else:
        report += "🎉 **Good productivity! Keep it up!**\n"
    
    return report


# ============================================================================
# TELEGRAM FUNCTIONS (Same as local)
# ============================================================================

def send_telegram_message(bot_token, chat_id, message):
    """Sends message to Telegram"""
    
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
    """Sends message to multiple chats"""
    
    success_count = 0
    for chat_id in chat_ids:
        if send_telegram_message(bot_token, chat_id, message):
            success_count += 1
    return success_count


def read_telegram_ids_from_sheet(service, spreadsheet_id):
    """Reads chat IDs from telegram IDs sheet"""
    
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
    """Performs full analysis + AI advice + notification"""
    
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
            full_message = report + f"\n💬 AI says:\n{ai_advice}\n\n_Powered by {provider_used}_"
            
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
