# -*- coding: utf-8 -*-
"""
Database Management Module for Digital History & Telemetry
Handles SQLite connections, WAL mode, migrations, and thread-safe operations.
"""

import os
import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "chrome" / "chrome_history_master.db"

_local = threading.local()

def get_db_path():
    path_str = os.environ.get("DIGITAL_HISTORY_DB", str(DEFAULT_DB_PATH))
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def get_db_connection():
    """Returns a thread-local SQLite connection with WAL mode enabled."""
    db_path = get_db_path()
    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes tables and indexes for google_activity and api_activity_stream."""
    conn = get_db_connection()
    try:
        with conn:
            # 1. Google My Activity dedicated table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS google_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_micro INTEGER UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    timestamp_bd TEXT NOT NULL,
                    product TEXT NOT NULL,
                    app_name TEXT,
                    action TEXT,
                    title TEXT,
                    url TEXT,
                    details TEXT,
                    raw_data TEXT,
                    source TEXT DEFAULT 'playwright_google_activity',
                    ingested_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ga_ts_micro ON google_activity(timestamp_micro);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ga_product ON google_activity(product);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ga_action ON google_activity(action);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ga_ts_utc ON google_activity(timestamp_utc);")

            # 2. General REST API streaming activities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_activity_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id TEXT UNIQUE,
                    source TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    timestamp_utc TEXT NOT NULL,
                    payload TEXT,
                    device_id TEXT,
                    user_id TEXT,
                    ingested_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_source ON api_activity_stream(source);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_type ON api_activity_stream(activity_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_ts ON api_activity_stream(timestamp_utc);")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {get_db_path()}")
