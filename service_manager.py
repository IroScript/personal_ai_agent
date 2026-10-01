# -*- coding: utf-8 -*-
"""
Digital History Service Manager
Controls the continuous REST API service and Playwright Google My Activity ingestion worker.
Supports: start, stop, restart, status, sync-once
"""

import os
import sys
import time
import signal
import subprocess
import sqlite3
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

API_PID_FILE = LOGS_DIR / "api_service.pid"
WORKER_PID_FILE = LOGS_DIR / "playwright_worker.pid"

API_LOG = LOGS_DIR / "api_service.log"
WORKER_LOG = LOGS_DIR / "playwright_worker.log"

API_PORT = int(os.environ.get("PORT", "8085"))
API_URL = f"http://127.0.0.1:{API_PORT}"

def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def get_service_pid(pid_file: Path) -> int:
    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            if is_pid_running(pid):
                return pid
        except Exception:
            pass
    return None

def start_api_service():
    pid = get_service_pid(API_PID_FILE)
    if pid:
        print(f"ℹ️ REST API service is already running (PID: {pid}).")
        return pid

    print(f"🚀 Starting Digital History REST API on port {API_PORT}...")
    log_file = open(API_LOG, "a", encoding="utf-8")
    env = os.environ.copy()
    env["PORT"] = str(API_PORT)
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "server.api_service:app", "--host", "0.0.0.0", "--port", str(API_PORT)],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=log_file,
        env=env,
        start_new_session=True
    )
    with open(API_PID_FILE, "w") as f:
        f.write(str(proc.pid))

    # Wait for API to respond
    for _ in range(15):
        time.sleep(0.5)
        try:
            req = urllib.request.Request(f"{API_URL}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    print(f"✅ REST API Service successfully started (PID: {proc.pid}) at {API_URL}")
                    return proc.pid
        except Exception:
            pass

    print(f"⚠️ REST API process launched (PID: {proc.pid}), still initializing...")
    return proc.pid

def start_playwright_worker():
    pid = get_service_pid(WORKER_PID_FILE)
    if pid:
        print(f"ℹ️ Playwright worker is already running (PID: {pid}).")
        return pid

    print("🚀 Starting Playwright Google My Activity Continuous Ingestion Worker...")
    log_file = open(WORKER_LOG, "a", encoding="utf-8")
    env = os.environ.copy()
    env["API_URL"] = API_URL
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [str(VENV_PYTHON), "tools/playwright_google_activity_worker.py", "--daemon", "--interval", "300", "--api-url", API_URL],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=log_file,
        env=env,
        start_new_session=True
    )
    with open(WORKER_PID_FILE, "w") as f:
        f.write(str(proc.pid))

    print(f"✅ Playwright Ingestion Worker successfully started (PID: {proc.pid})")
    return proc.pid

def stop_process(pid_file: Path, service_name: str):
    pid = get_service_pid(pid_file)
    if not pid:
        print(f"ℹ️ {service_name} is not running.")
        if pid_file.exists():
            pid_file.unlink()
        return

    print(f"🛑 Stopping {service_name} (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not is_pid_running(pid):
                break
        if is_pid_running(pid):
            os.kill(pid, signal.SIGKILL)
    except Exception as e:
        print(f"Error stopping PID {pid}: {e}")

    if pid_file.exists():
        pid_file.unlink()
    print(f"✅ {service_name} stopped.")

def get_status():
    print("\n=======================================================")
    print(" 📜 DIGITAL HISTORY & TELEMETRY SYSTEM STATUS")
    print("=======================================================")

    api_pid = get_service_pid(API_PID_FILE)
    worker_pid = get_service_pid(WORKER_PID_FILE)

    print(f"◈ REST API Service:       {'🟢 RUNNING (PID: ' + str(api_pid) + ')' if api_pid else '🔴 STOPPED'}")
    print(f"◈ Playwright Sync Worker: {'🟢 RUNNING (PID: ' + str(worker_pid) + ')' if worker_pid else '🔴 STOPPED'}")
    print(f"◈ Service API URL:        {API_URL}")

    # Health check
    if api_pid:
        try:
            req = urllib.request.Request(f"{API_URL}/api/v1/stats")
            with urllib.request.urlopen(req, timeout=3) as resp:
                stats = json.loads(resp.read().decode())
                print(f"\n📊 Live SQLite Database Metrics:")
                print(f"  • SQLite Database:      {stats.get('database_file')}")
                print(f"  • File Size:            {stats.get('file_size_mb')} MB")
                counts = stats.get("counts", {})
                print(f"  • Google Activities:    {counts.get('google_activity', 0):,} rows")
                print(f"  • API Stream Events:    {counts.get('api_activity_stream', 0):,} rows")
                print(f"  • Chrome History:       {counts.get('chrome_history', 0):,} rows")
                print(f"  • Chrome Searches:      {counts.get('chrome_searches', 0):,} rows")
                print(f"  • Total Tracked Events: {counts.get('total_tracked_records', 0):,} rows")
                latest = stats.get("latest_google_activity")
                if latest:
                    print(f"  • Latest Ingested Item: [{latest.get('timestamp_utc')}] {latest.get('product')} - {latest.get('title')[:60]}")
        except Exception as e:
            print(f"  ⚠️ Could not fetch API stats: {e}")
    else:
        # Check SQLite directly
        db_path = BASE_DIR / "data" / "chrome" / "chrome_history_master.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                c = conn.cursor()
                c.execute("SELECT count(*) FROM google_activity")
                ga_cnt = c.fetchone()[0]
                c.execute("SELECT count(*) FROM history")
                h_cnt = c.fetchone()[0]
                conn.close()
                print(f"\n💾 Direct SQLite Inspection:")
                print(f"  • Google Activities: {ga_cnt:,} rows")
                print(f"  • Chrome History:    {h_cnt:,} rows")
            except Exception as e:
                print(f"  Direct SQLite error: {e}")

    print("=======================================================\n")

def run_once():
    print("▶️ Running one-time Playwright sync cycle...")
    cmd = [str(VENV_PYTHON), "tools/playwright_google_activity_worker.py", "--once", "--api-url", API_URL]
    subprocess.run(cmd, cwd=str(BASE_DIR))

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 service_manager.py [start|stop|restart|status|sync-once]")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "start":
        start_api_service()
        start_playwright_worker()
        time.sleep(1)
        get_status()
    elif action == "stop":
        stop_playwright_worker = lambda: stop_process(WORKER_PID_FILE, "Playwright Worker")
        stop_api = lambda: stop_process(API_PID_FILE, "REST API Service")
        stop_playwright_worker()
        stop_api()
    elif action == "restart":
        stop_process(WORKER_PID_FILE, "Playwright Worker")
        stop_process(API_PID_FILE, "REST API Service")
        time.sleep(1)
        start_api_service()
        start_playwright_worker()
        time.sleep(1)
        get_status()
    elif action == "status":
        get_status()
    elif action == "sync-once":
        run_once()
    else:
        print(f"Unknown action: {action}")
        print("Valid actions: start, stop, restart, status, sync-once")

if __name__ == "__main__":
    main()
