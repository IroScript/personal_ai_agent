# -*- coding: utf-8 -*-
"""
Digital History Activity Reporter
Generates real-time reports of newly collected data from SQLite and REST API.
Tracks state across runs in logs/last_report_state.json.
"""

import os
import sys
import json
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "chrome" / "chrome_history_master.db"
STATE_FILE = BASE_DIR / "logs" / "last_report_state.json"
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8085")

def get_report():
    report = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "api_connected": False,
        "new_activities_count": 0,
        "total_activities_count": 0,
        "new_items": [],
        "product_breakdown": {},
        "action_breakdown": {},
        "overall_counts": {}
    }

    # 1. Fetch live API stats if available
    try:
        req = urllib.request.Request(f"{API_URL}/api/v1/stats")
        with urllib.request.urlopen(req, timeout=3) as resp:
            api_data = json.loads(resp.read().decode())
            report["api_connected"] = True
            report["overall_counts"] = api_data.get("counts", {})
            report["uptime_seconds"] = api_data.get("server_uptime_seconds", 0)
    except Exception as e:
        report["api_error"] = str(e)

    # 2. Query SQLite
    if not DB_PATH.exists():
        report["error"] = "Database file does not exist"
        return report

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        
        # Load last state
        last_id = 0
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r") as f:
                    state_data = json.load(f)
                    last_id = state_data.get("last_activity_id", 0)
            except Exception:
                last_id = 0

        # Total activities
        cur.execute("SELECT count(*) FROM google_activity")
        report["total_activities_count"] = cur.fetchone()[0]

        # New items since last check
        cur.execute("""
            SELECT id, timestamp_bd, product, app_name, action, title, url, source
            FROM google_activity
            WHERE id > ?
            ORDER BY id ASC
        """, (last_id,))
        rows = [dict(r) for r in cur.fetchall()]
        report["new_activities_count"] = len(rows)
        report["new_items"] = rows

        # Breakdown by product
        cur.execute("SELECT product, count(*) as cnt FROM google_activity GROUP BY product ORDER BY cnt DESC")
        report["product_breakdown"] = {r["product"]: r["cnt"] for r in cur.fetchall()}

        # Breakdown by action
        cur.execute("SELECT action, count(*) as cnt FROM google_activity GROUP BY action ORDER BY cnt DESC")
        report["action_breakdown"] = {r["action"]: r["cnt"] for r in cur.fetchall()}

        # Update last seen state
        max_id = last_id
        if rows:
            max_id = max(r["id"] for r in rows)
        elif report["total_activities_count"] > 0:
            cur.execute("SELECT MAX(id) FROM google_activity")
            max_id = cur.fetchone()[0] or 0

        with open(STATE_FILE, "w") as f:
            json.dump({"last_activity_id": max_id, "updated_at": report["timestamp_utc"]}, f, indent=2)

    except Exception as e:
        report["db_error"] = str(e)
    finally:
        conn.close()

    return report

if __name__ == "__main__":
    rep = get_report()
    print(json.dumps(rep, indent=2, ensure_ascii=False))
