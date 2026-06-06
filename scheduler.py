#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent Scheduler
Automatically runs ai_agent_online.py at specified intervals
"""

import schedule
import time
import subprocess
import sys
from datetime import datetime

def run_agent():
    """AI agent run করে"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n{'='*70}")
    print(f"🕐 Running AI Agent at {timestamp}")
    print(f"{'='*70}\n")
    
    try:
        # ai_agent_online.py run করো
        result = subprocess.run(
            [sys.executable, 'ai_agent_online.py', '--mode', 'notify'],
            cwd='.',
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print(f"\n✅ Agent completed successfully at {timestamp}")
        else:
            print(f"\n⚠️ Agent finished with warnings at {timestamp}")
    
    except Exception as e:
        print(f"\n❌ Error running agent: {e}")

# ============================================================================
# SCHEDULE CONFIGURATION
# ============================================================================

# Schedule times (24-hour format)
SCHEDULE_TIMES = [
    "09:00",  # Morning - সকালে পরিকল্পনা
    "14:00",  # Afternoon - দুপুরে progress check
    "18:00",  # Evening - সন্ধ্যায় review
    "22:00"   # Night - রাতে final summary
]

# Set up scheduled jobs
for time_str in SCHEDULE_TIMES:
    schedule.every().day.at(time_str).do(run_agent)
    print(f"⏰ Scheduled: Daily at {time_str}")

print(f"\n{'='*70}")
print("🤖 AI Productivity Agent Scheduler Started")
print(f"{'='*70}")
print(f"📅 Runs {len(SCHEDULE_TIMES)} times per day")
print(f"⏰ Schedule: {', '.join(SCHEDULE_TIMES)}")
print(f"🔄 Press Ctrl+C to stop")
print(f"{'='*70}\n")

# Run immediately on start (optional - comment out if you don't want)
print("🚀 Running initial check...")
run_agent()

# Keep running
try:
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute
except KeyboardInterrupt:
    print("\n\n🛑 Scheduler stopped by user")
    sys.exit(0)
