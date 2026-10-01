-- ============================================================
-- PERSONAL DIGITAL HISTORY & TELEMETRY PLATFORM
-- Initial SQLite Edge Schema (WAL Mode + Outbox Pattern)
-- ============================================================

-- Devices Registry
CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    device_name     TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    os_info         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sources Registry
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    source_name     TEXT NOT NULL,
    source_category TEXT NOT NULL,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    project_id      TEXT,
    start_time      TEXT NOT NULL,
    end_time        TEXT,
    boundary_reason TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Universal Telemetry Event Store (Edge Buffer / Ingestion Queue)
CREATE TABLE IF NOT EXISTS local_events (
    event_id            TEXT PRIMARY KEY,
    event_time          TEXT NOT NULL,
    ingested_at         TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    device_id           TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    event_version       INTEGER NOT NULL DEFAULT 1,
    schema_version      INTEGER NOT NULL DEFAULT 1,
    session_id          TEXT,
    project_id          TEXT,
    task_id             TEXT,
    note_id             TEXT,
    trace_id            TEXT,
    parent_event_id     TEXT,
    sequence_number     INTEGER,
    source_record_id    TEXT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    payload             TEXT NOT NULL,
    payload_hash        TEXT NOT NULL,
    content_hash        TEXT,
    confidence          TEXT NOT NULL,
    provenance          TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (device_id) REFERENCES devices(device_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_local_events_time ON local_events(event_time);
CREATE INDEX IF NOT EXISTS idx_local_events_source_time ON local_events(source_id, event_time);
CREATE INDEX IF NOT EXISTS idx_local_events_user_time ON local_events(user_id, event_time);
CREATE INDEX IF NOT EXISTS idx_local_events_idempotency_key ON local_events(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_local_events_payload_hash ON local_events(payload_hash);
CREATE INDEX IF NOT EXISTS idx_local_events_keyset ON local_events(event_time DESC, event_id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_local_events_source_record ON local_events(source_id, source_record_id) WHERE source_record_id IS NOT NULL;

-- Outbox Table for Asynchronous, Guaranteed Upstream Sync (Postgres / Cloud / BigQuery)
CREATE TABLE IF NOT EXISTS outbox_events (
    outbox_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    locked_at       TEXT,
    retry_after     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (event_id) REFERENCES local_events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outbox_processing ON outbox_events(status, retry_after, created_at);

-- Derived Non-Overlapping Time Intervals (Evidence-Based Time Investment)
CREATE TABLE IF NOT EXISTS time_intervals (
    interval_id         TEXT PRIMARY KEY,
    session_id          TEXT,
    start_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    duration_seconds    INTEGER NOT NULL,
    activity_type       TEXT NOT NULL,
    confidence          TEXT NOT NULL,
    source_event_ids    TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_time_intervals_range ON time_intervals(start_time, end_time);

-- Session External Integration Links (Decoupled Adapter for Live Note / External Projects)
CREATE TABLE IF NOT EXISTS session_links (
    link_id             TEXT PRIMARY KEY,
    session_id          TEXT,
    external_system     TEXT NOT NULL,
    external_task_id    TEXT NOT NULL,
    project_id          TEXT,
    note_id             TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_session_links_external ON session_links(external_system, external_task_id);

-- Artifacts Metadata (Screenshots, Media, Large Blobs stored outside DB)
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id         TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL,
    storage_uri         TEXT NOT NULL,
    file_hash           TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    width               INTEGER,
    height              INTEGER,
    ocr_status          TEXT NOT NULL DEFAULT 'PENDING',
    ocr_text            TEXT,
    capture_source      TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(file_hash);

-- Default Devices
INSERT OR IGNORE INTO devices (device_id, device_name, device_type, os_info) VALUES 
('desktop_windows_irak', 'Irak Windows PC', 'desktop', 'Windows 11 Pro 64-bit'),
('pixel7_irak', 'Irak Google Pixel 7', 'mobile', 'Android 14 / Google Play Services'),
('cloud_vm_debian', 'AGY Cloud Server VM', 'server', 'Debian Linux 12 x86_64');

-- Default Sources
INSERT OR IGNORE INTO sources (source_id, source_name, source_category) VALUES 
('google_activity', 'Google MyActivity Scraper', 'cloud_scraper'),
('chrome_sqlite', 'Chrome SQLite Master History', 'browser'),
('openrecall', 'OpenRecall Visual & OCR Snapshots', 'desktop_ocr'),
('android_activity', 'Android OS UsageStats & Events', 'mobile_telemetry'),
('whatsapp_bridge', 'WhatsApp Baileys Multi-Device Bridge', 'chat_bridge'),
('ai_agent', 'Antigravity Multi-Agent Runner', 'ai_runtime'),
('terminal', 'Linux / Windows Shell Commands', 'terminal');
