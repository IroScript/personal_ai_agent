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
    """Runs the AI agent"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n{'='*70}")
    print(f"🕐 Running AI Agent at {timestamp}")
    print(f"{'='*70}\n")
    
    try:
        # Run ai_agent.py in dynamic mode
        result = subprocess.run(
            [sys.executable, 'ai_agent.py', '--mode', 'dynamic'],
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

# Schedule interval (minutes)
CHECK_INTERVAL_MINUTES = 30

# Set up scheduled jobs to run every 30 minutes
schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_agent)
print(f"⏰ Scheduled: Every {CHECK_INTERVAL_MINUTES} minutes")

print(f"\n{'='*70}")
print("🤖 AI Productivity Agent Scheduler Started")
print(f"{'='*70}")
print(f"📅 Mode: Dynamic AI-judged nudge")
print(f"⏰ Schedule: Running every {CHECK_INTERVAL_MINUTES} minutes")
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
