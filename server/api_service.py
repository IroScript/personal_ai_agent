# -*- coding: utf-8 -*-
"""
Continuous REST API Service for Digital History SQLite Ingestion
Exposes endpoints for high-throughput, idempotent activity ingestion.
"""

import os
import sys
import json
import time
import uuid
import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Ensure server package path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.db import get_db_connection, init_db, get_db_path

app = FastAPI(
    title="Digital History REST API Service",
    description="Continuous Ingestion REST API for Digital History, Google My Activity, and Personal Telemetry",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

START_TIME = time.time()

# ---------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------
class GoogleActivityItem(BaseModel):
    timestamp_micro: Optional[int] = None
    timestamp_utc: Optional[str] = None
    timestamp_bd: Optional[str] = None
    product: str = Field(..., description="Google product/service name, e.g. YouTube, Chrome, Search")
    app_name: Optional[str] = None
    action: Optional[str] = Field("Used", description="Action performed, e.g. Visited, Searched, Watched, Used")
    title: Optional[str] = None
    url: Optional[str] = None
    details: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    source: Optional[str] = "playwright_google_activity"

class GoogleActivityBatchRequest(BaseModel):
    activities: List[GoogleActivityItem]

class GenericApiEvent(BaseModel):
    activity_id: Optional[str] = None
    source: str = Field(..., description="Source application or collector name")
    activity_type: str = Field(..., description="Type of event/activity")
    title: Optional[str] = None
    url: Optional[str] = None
    timestamp_utc: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    device_id: Optional[str] = "azure_vm"
    user_id: Optional[str] = "irak"

class ChromeHistoryItem(BaseModel):
    profile_folder: Optional[str] = "Profile_Irak_Master"
    signed_in_email: Optional[str] = "mdkamruzzamanirak@gmail.com"
    profile_display_name: Optional[str] = "Irak Mahmud"
    datetime_utc: Optional[str] = None
    timestamp: Optional[int] = None
    title: Optional[str] = None
    url: str
    visit_count: Optional[int] = 1
    typed_count: Optional[int] = 0

# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def fill_timestamps(item: GoogleActivityItem):
    now_utc = datetime.now(timezone.utc)
    if not item.timestamp_micro:
        item.timestamp_micro = int(now_utc.timestamp() * 1_000_000)
    
    if not item.timestamp_utc:
        dt_utc = datetime.fromtimestamp(item.timestamp_micro / 1_000_000, tz=timezone.utc)
        item.timestamp_utc = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
    
    if not item.timestamp_bd:
        dt_utc = datetime.fromtimestamp(item.timestamp_micro / 1_000_000, tz=timezone.utc)
        dt_bd = dt_utc + timedelta(hours=6)
        item.timestamp_bd = dt_bd.strftime('%Y-%m-%d %H:%M:%S')

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/health")
def health():
    db_ok = False
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1;").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "Digital History REST API Service",
        "uptime_seconds": int(time.time() - START_TIME),
        "database_connected": db_ok,
        "database_path": str(get_db_path()),
        "current_time_utc": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/v1/activity")
def ingest_single_activity(item: GoogleActivityItem):
    fill_timestamps(item)
    ingested_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    raw_json = json.dumps(item.raw_data or {}, ensure_ascii=False)
    
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO google_activity (
                    timestamp_micro, timestamp_utc, timestamp_bd, product, app_name,
                    action, title, url, details, raw_data, source, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.timestamp_micro, item.timestamp_utc, item.timestamp_bd,
                item.product, item.app_name, item.action, item.title, item.url,
                item.details, raw_json, item.source, ingested_at
            ))
            inserted = cursor.rowcount > 0
            row_id = cursor.lastrowid if inserted else None
        return {
            "status": "success",
            "inserted": inserted,
            "row_id": row_id,
            "timestamp_micro": item.timestamp_micro,
            "product": item.product
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/v1/activity/batch")
def ingest_activity_batch(batch: GoogleActivityBatchRequest):
    if not batch.activities:
        return {"status": "success", "total_received": 0, "inserted": 0, "duplicates": 0}

    ingested_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    inserted_count = 0
    duplicates_count = 0

    try:
        with conn:
            for item in batch.activities:
                fill_timestamps(item)
                raw_json = json.dumps(item.raw_data or {}, ensure_ascii=False)
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO google_activity (
                        timestamp_micro, timestamp_utc, timestamp_bd, product, app_name,
                        action, title, url, details, raw_data, source, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.timestamp_micro, item.timestamp_utc, item.timestamp_bd,
                    item.product, item.app_name, item.action, item.title, item.url,
                    item.details, raw_json, item.source, ingested_at
                ))
                if cursor.rowcount > 0:
                    inserted_count += 1
                else:
                    duplicates_count += 1

        return {
            "status": "success",
            "total_received": len(batch.activities),
            "inserted": inserted_count,
            "duplicates": duplicates_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/v1/events")
def ingest_generic_event(event: GenericApiEvent):
    now_utc = datetime.now(timezone.utc)
    activity_id = event.activity_id or str(uuid.uuid4())
    ts_utc = event.timestamp_utc or now_utc.strftime('%Y-%m-%d %H:%M:%S')
    ingested_at = now_utc.strftime('%Y-%m-%d %H:%M:%S')
    raw_payload = json.dumps(event.payload or {}, ensure_ascii=False)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO api_activity_stream (
                    activity_id, source, activity_type, title, url,
                    timestamp_utc, payload, device_id, user_id, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                activity_id, event.source, event.activity_type, event.title, event.url,
                ts_utc, raw_payload, event.device_id, event.user_id, ingested_at
            ))
            inserted = cursor.rowcount > 0
        return {
            "status": "success",
            "inserted": inserted,
            "activity_id": activity_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/v1/history")
def ingest_chrome_history(item: ChromeHistoryItem):
    now_utc = datetime.now(timezone.utc)
    ts_str = item.datetime_utc or now_utc.strftime('%Y-%m-%d %H:%M:%S')
    ts_epoch = item.timestamp or int(now_utc.timestamp())

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.execute("""
                INSERT INTO history (
                    profile_folder, signed_in_email, profile_display_name,
                    datetime_utc, timestamp, title, url, visit_count, typed_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.profile_folder, item.signed_in_email, item.profile_display_name,
                ts_str, ts_epoch, item.title, item.url, item.visit_count, item.typed_count
            ))
            row_id = cursor.lastrowid
        return {
            "status": "success",
            "inserted": True,
            "history_id": row_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/v1/activity")
def list_activities(
    product: Optional[str] = Query(None, description="Filter by product e.g. YouTube, Chrome"),
    action: Optional[str] = Query(None, description="Filter by action e.g. Visited, Searched"),
    search: Optional[str] = Query(None, description="Search in title or url"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    conn = get_db_connection()
    try:
        query = "SELECT * FROM google_activity WHERE 1=1"
        params = []
        if product:
            query += " AND product = ?"
            params.append(product)
        if action:
            query += " AND action = ?"
            params.append(action)
        if search:
            query += " AND (title LIKE ? OR url LIKE ?)"
            params.append(f"%{search}%")
            params.append(f"%{search}%")

        query += " ORDER BY timestamp_micro DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        return {
            "status": "success",
            "count": len(rows),
            "offset": offset,
            "limit": limit,
            "items": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/v1/stats")
def get_stats():
    conn = get_db_connection()
    try:
        def count_table(table_name):
            try:
                cur = conn.execute(f"SELECT count(*) FROM {table_name}")
                return cur.fetchone()[0]
            except Exception:
                return 0

        google_activities_count = count_table("google_activity")
        api_stream_count = count_table("api_activity_stream")
        chrome_history_count = count_table("history")
        searches_count = count_table("searches")

        # Latest activity
        cur = conn.execute("SELECT timestamp_utc, product, title FROM google_activity ORDER BY timestamp_micro DESC LIMIT 1")
        latest_act = cur.fetchone()
        latest_act_dict = dict(latest_act) if latest_act else None

        db_path = get_db_path()
        file_size_bytes = db_path.stat().st_size if db_path.exists() else 0

        return {
            "status": "success",
            "database_file": str(db_path),
            "file_size_mb": round(file_size_bytes / (1024 * 1024), 2),
            "counts": {
                "google_activity": google_activities_count,
                "api_activity_stream": api_stream_count,
                "chrome_history": chrome_history_count,
                "chrome_searches": searches_count,
                "total_tracked_records": google_activities_count + api_stream_count + chrome_history_count + searches_count
            },
            "latest_google_activity": latest_act_dict,
            "server_uptime_seconds": int(time.time() - START_TIME)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8085"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Starting Digital History Ingestion REST API on {host}:{port}...")
    uvicorn.run(app, host=host, port=port, log_level="info")
