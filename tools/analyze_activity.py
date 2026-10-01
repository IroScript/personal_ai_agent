# -*- coding: utf-8 -*-
"""
OpenRecall & Chrome Activity Analyzer for Personal AI Agent
Queries local/remote recall.db and chrome_history_master.db
Provides coaching metrics: Focus Time, Vibe Coding, Distractions, Top Tools
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta

DATA_DIR = "/home/mdkamruzzamanirak_gmail_com/.openclaw/workspace/IROSCRIPT-CEO/PERSONAL AI AGENT/data"
RECALL_DB = os.path.join(DATA_DIR, "openrecall", "recall.db")
CHROME_DB = os.path.join(DATA_DIR, "chrome", "chrome_history_master.db")

def get_coaching_summary():
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "openrecall_status": "not_found",
        "chrome_status": "not_found",
        "stats": {}
    }
    
    if os.path.exists(RECALL_DB):
        try:
            conn = sqlite3.connect(f"file:{RECALL_DB}?mode=ro", uri=True)
            cur = conn.cursor()
            report["openrecall_status"] = "active"
            
            # Total records
            cur.execute("SELECT count(*) FROM entries")
            report["stats"]["total_snapshots"] = cur.fetchone()[0]
            
            # Recent 10 activities
            cur.execute("SELECT timestamp, app, title FROM entries ORDER BY timestamp DESC LIMIT 10")
            report["stats"]["recent_activities"] = [
                {"time": r[0], "app": r[1], "title": r[2]} for r in cur.fetchall()
            ]
            
            # Top Applications
            cur.execute("SELECT app, count(*) as cnt FROM entries GROUP BY app ORDER BY cnt DESC LIMIT 8")
            report["stats"]["top_apps"] = [
                {"app": r[0] or "Unknown", "count": r[1]} for r in cur.fetchall()
            ]
            
            conn.close()
        except Exception as e:
            report["openrecall_error"] = str(e)
            
    if os.path.exists(CHROME_DB):
        try:
            conn = sqlite3.connect(f"file:{CHROME_DB}?mode=ro", uri=True)
            cur = conn.cursor()
            report["chrome_status"] = "active"
            
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            report["chrome_tables"] = [r[0] for r in cur.fetchall()]
            conn.close()
        except Exception as e:
            report["chrome_error"] = str(e)
            
    return report

if __name__ == "__main__":
    summary = get_coaching_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
