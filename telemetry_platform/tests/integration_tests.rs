use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use std::sync::Arc;
use telemetry_platform::api::handlers::AppState;
use telemetry_platform::api::routes::create_router;
use telemetry_platform::domain::events::TelemetryEvent;
use telemetry_platform::domain::evidence::{ActivityType, ConfidenceLevel};
use telemetry_platform::domain::time::TimeInterval;
use telemetry_platform::infrastructure::database::{
    AuditRepository, EventFilter, EventRepository, IngestStatus, SqliteStorage,
};
use telemetry_platform::infrastructure::outbox::{MockOutboxSink, OutboxWorker};
use tower::ServiceExt;
use uuid::Uuid;

#[tokio::test]
async fn test_event_identity_and_four_idempotency_cases() {
    let storage = SqliteStorage::new("sqlite::memory:").await.unwrap();

    let t1 = Utc.with_ymd_and_hms(2026, 9, 16, 10, 0, 0).unwrap();
    let t2 = Utc.with_ymd_and_hms(2026, 9, 16, 10, 5, 0).unwrap();

    // CASE 1: NEW EVENT
    let event1 = TelemetryEvent::with_options(
        "chrome_sqlite".to_string(),
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        t1,
        serde_json::json!({"url": "https://youtube.com"}),
        ConfidenceLevel::Proven,
        serde_json::json!({"source": "history"}),
        Some("chrome_row_101".to_string()),
        None,
    );
    let res1 = storage.save_event(&event1).await.unwrap();
    assert_eq!(res1.event_id, event1.event_id);
    assert!(matches!(res1.status, IngestStatus::Created));

    // CASE 2: DUPLICATE EVENT (Same source_record_id or same idempotency key)
    let event1_retry = TelemetryEvent::with_options(
        "chrome_sqlite".to_string(),
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        t1,
        serde_json::json!({"url": "https://youtube.com"}),
        ConfidenceLevel::Proven,
        serde_json::json!({"source": "history"}),
        Some("chrome_row_101".to_string()),
        None,
    );
    let res2 = storage.save_event(&event1_retry).await.unwrap();
    assert_eq!(res2.event_id, event1.event_id);
    assert!(matches!(res2.status, IngestStatus::AlreadyExists));

    // CASE 3: SAME CONTENT / DIFFERENT EVENT
    // Same payload ("https://youtube.com"), but different time (10:05:00) and different source record!
    // Must NOT be rejected as duplicate!
    let event2 = TelemetryEvent::with_options(
        "chrome_sqlite".to_string(),
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        t2,
        serde_json::json!({"url": "https://youtube.com"}),
        ConfidenceLevel::Proven,
        serde_json::json!({"source": "history"}),
        Some("chrome_row_102".to_string()),
        None,
    );
    let res3 = storage.save_event(&event2).await.unwrap();
    assert_eq!(res3.event_id, event2.event_id);
    assert!(
        matches!(res3.status, IngestStatus::Created),
        "Same payload at different time must be treated as a new event"
    );

    // CASE 4: INVALID EVENT (Missing required identity fields)
    let invalid_event = TelemetryEvent::new(
        "".to_string(), // Empty source_id
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        t1,
        serde_json::json!({}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
    );
    let res4 = storage.save_event(&invalid_event).await.unwrap();
    assert!(matches!(res4.status, IngestStatus::Invalid(_)));

    // Verify local_events count in DB: exactly 2 events (event1 and event2)
    let pool = storage.get_pool();
    let total: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM local_events")
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(total, 2);
}

#[tokio::test]
async fn test_batch_ingestion_limits_and_validation() {
    let storage = SqliteStorage::new("sqlite::memory:").await.unwrap();
    let app = create_router(AppState {
        storage: Arc::new(storage),
    });

    // 1. Empty batch -> 400 Bad Request
    let empty_batch_req = serde_json::json!({
        "batch_id": "batch_001",
        "source_id": "chrome_sqlite",
        "device_id": "desktop_windows_irak",
        "events": []
    });
    let res_empty = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/events/batch")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&empty_batch_req).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res_empty.status(), StatusCode::BAD_REQUEST);

    // 2. Normal batch with 5 valid events
    let mut normal_events = Vec::new();
    for i in 0..5 {
        normal_events.push(serde_json::json!({
            "source_id": "chrome_sqlite",
            "device_id": "desktop_windows_irak",
            "user_id": "irak_master",
            "event_type": "url_visit",
            "source_record_id": format!("visit_{}", i),
            "payload": {"url": format!("https://example.com/{}", i)}
        }));
    }
    let normal_batch_req = serde_json::json!({
        "batch_id": "batch_normal",
        "source_id": "chrome_sqlite",
        "device_id": "desktop_windows_irak",
        "events": normal_events
    });

    let res_normal = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/events/batch")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&normal_batch_req).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res_normal.status(), StatusCode::OK);

    // 3. Batch with partial duplicates and 1 invalid
    let mixed_events = vec![
        // Duplicate
        serde_json::json!({
            "source_id": "chrome_sqlite",
            "device_id": "desktop_windows_irak",
            "user_id": "irak_master",
            "event_type": "url_visit",
            "source_record_id": "visit_0",
            "payload": {"url": "https://example.com/0"}
        }),
        // New
        serde_json::json!({
            "source_id": "chrome_sqlite",
            "device_id": "desktop_windows_irak",
            "user_id": "irak_master",
            "event_type": "url_visit",
            "source_record_id": "visit_99",
            "payload": {"url": "https://example.com/99"}
        }),
        // Invalid (empty source_id)
        serde_json::json!({
            "source_id": "",
            "device_id": "desktop_windows_irak",
            "user_id": "irak_master",
            "event_type": "url_visit",
            "payload": {}
        }),
    ];
    let mixed_batch_req = serde_json::json!({
        "batch_id": "batch_mixed",
        "source_id": "chrome_sqlite",
        "device_id": "desktop_windows_irak",
        "events": mixed_events
    });

    let res_mixed = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/events/batch")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&mixed_batch_req).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res_mixed.status(), StatusCode::OK);

    // 4. Oversized batch (>500 events) -> 400 Bad Request
    let mut huge_events = Vec::new();
    for i in 0..501 {
        huge_events.push(serde_json::json!({
            "source_id": "chrome_sqlite",
            "device_id": "desktop_windows_irak",
            "user_id": "irak_master",
            "event_type": "url_visit",
            "source_record_id": format!("huge_{}", i),
            "payload": {}
        }));
    }
    let huge_batch_req = serde_json::json!({
        "batch_id": "batch_huge",
        "source_id": "chrome_sqlite",
        "device_id": "desktop_windows_irak",
        "events": huge_events
    });

    let res_huge = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/events/batch")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&huge_batch_req).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res_huge.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_keyset_pagination_and_filtering() {
    let storage = SqliteStorage::new("sqlite::memory:").await.unwrap();
    let base_time = Utc.with_ymd_and_hms(2026, 9, 16, 12, 0, 0).unwrap();

    // Ingest 15 events spaced 1 minute apart
    for i in 0..15 {
        let event = TelemetryEvent::with_options(
            if i % 2 == 0 { "chrome_sqlite".to_string() } else { "whatsapp_bridge".to_string() },
            "desktop_windows_irak".to_string(),
            "irak_master".to_string(),
            if i % 2 == 0 { "url_visit".to_string() } else { "message_sent".to_string() },
            base_time + Duration::minutes(i),
            serde_json::json!({"seq": i}),
            ConfidenceLevel::Proven,
            serde_json::json!({}),
            Some(format!("rec_{}", i)),
            None,
        );
        storage.save_event(&event).await.unwrap();
    }

    // Page 1: limit 5
    let filter1 = EventFilter {
        limit: 5,
        ..Default::default()
    };
    let page1 = storage.list_events_paginated(&filter1).await.unwrap();
    assert_eq!(page1.items.len(), 5);
    assert!(page1.has_more);
    assert!(page1.next_cursor.is_some());

    // Page 2: with cursor
    let filter2 = EventFilter {
        limit: 5,
        cursor: page1.next_cursor.clone(),
        ..Default::default()
    };
    let page2 = storage.list_events_paginated(&filter2).await.unwrap();
    assert_eq!(page2.items.len(), 5);
    assert!(page2.has_more);
    assert!(page2.next_cursor.is_some());

    // Page 3: with cursor
    let filter3 = EventFilter {
        limit: 5,
        cursor: page2.next_cursor.clone(),
        ..Default::default()
    };
    let page3 = storage.list_events_paginated(&filter3).await.unwrap();
    assert_eq!(page3.items.len(), 5);
    assert!(!page3.has_more);
    assert!(page3.next_cursor.is_none());

    // Filtering test: source_id = "whatsapp_bridge"
    let filter_source = EventFilter {
        source_id: Some("whatsapp_bridge".to_string()),
        limit: 50,
        ..Default::default()
    };
    let page_source = storage.list_events_paginated(&filter_source).await.unwrap();
    assert_eq!(page_source.items.len(), 7); // odd numbers 1, 3, 5, 7, 9, 11, 13
}

#[tokio::test]
async fn test_time_investment_audit_real_computation() {
    let storage = Arc::new(SqliteStorage::new("sqlite::memory:").await.unwrap());
    let t_base = Utc.with_ymd_and_hms(2026, 9, 16, 8, 0, 0).unwrap();

    // 1. AI Processing: 10 mins (8:00 - 8:10)
    let ai1 = TimeInterval {
        start_time: t_base,
        end_time: t_base + Duration::minutes(10),
        activity_type: ActivityType::AiProcessing,
        confidence: ConfidenceLevel::Proven,
        source_event_ids: vec!["ai_1".to_string()],
    };

    // 2. AI Processing Overlapping: 15 mins (8:05 - 8:20, overlaps 5 mins with ai1)
    // Union should be [8:00 - 8:20] = 20 mins (1200 seconds), NOT 25 mins!
    let ai2 = TimeInterval {
        start_time: t_base + Duration::minutes(5),
        end_time: t_base + Duration::minutes(20),
        activity_type: ActivityType::AiProcessing,
        confidence: ConfidenceLevel::Proven,
        source_event_ids: vec!["ai_2".to_string()],
    };

    // 3. User Interaction: 2 mins (8:25 - 8:27) = 120 seconds
    let user1 = TimeInterval {
        start_time: t_base + Duration::minutes(25),
        end_time: t_base + Duration::minutes(27),
        activity_type: ActivityType::UserInteraction,
        confidence: ConfidenceLevel::Proven,
        source_event_ids: vec!["u_1".to_string()],
    };

    // 4. External App: 5 mins (8:30 - 8:35) = 300 seconds
    let ext1 = TimeInterval {
        start_time: t_base + Duration::minutes(30),
        end_time: t_base + Duration::minutes(35),
        activity_type: ActivityType::ExternalApp,
        confidence: ConfidenceLevel::Proven,
        source_event_ids: vec!["ext_1".to_string()],
    };

    storage.save_intervals(&[ai1, ai2, user1, ext1], None).await.unwrap();

    let app = create_router(AppState { storage });

    let uri = format!(
        "/api/v1/audit/time-investment?start_time={}&end_time={}",
        t_base.to_rfc3339(),
        (t_base + Duration::hours(1)).to_rfc3339()
    );

    let res = app
        .oneshot(
            Request::builder()
                .uri(&uri)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(res.status(), StatusCode::OK);

    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let audit_resp: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap();

    // Verify non-zero real computed values!
    let total_ai = audit_resp["total_ai_processing_seconds"].as_i64().unwrap();
    let total_user = audit_resp["total_proven_user_active_seconds"].as_i64().unwrap();
    let total_ext = audit_resp["total_proven_external_app_seconds"].as_i64().unwrap();

    assert_eq!(total_ai, 20 * 60, "Overlapping AI intervals must union to 20 minutes");
    assert_eq!(total_user, 2 * 60, "User active time must be 2 minutes");
    assert_eq!(total_ext, 5 * 60, "External app time must be 5 minutes");
}

#[tokio::test]
async fn test_outbox_worker_lifecycle_and_retry() {
    let storage = Arc::new(SqliteStorage::new("sqlite::memory:").await.unwrap());
    let sink = Arc::new(MockOutboxSink::new());
    let worker = OutboxWorker::with_options(storage.clone(), sink.clone(), 3, 60);

    // 1. Ingest event
    let event1 = TelemetryEvent::new(
        "terminal".to_string(),
        "cloud_vm_debian".to_string(),
        "irak_master".to_string(),
        "command_exec".to_string(),
        Utc::now(),
        serde_json::json!({"cmd": "cargo test"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
    );
    storage.save_event(&event1).await.unwrap();

    // Verify outbox has 1 PENDING
    let pool = storage.get_pool();
    let pending_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM outbox_events WHERE status = 'PENDING'")
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(pending_count, 1);

    // 2. Process outbox with successful sink
    let summary = worker.process_batch(10).await.unwrap();
    assert_eq!(summary.processed, 1);
    assert_eq!(summary.succeeded, 1);
    assert_eq!(summary.failed, 0);

    // Verify status updated to SYNCED
    let synced_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM outbox_events WHERE status = 'SYNCED'")
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(synced_count, 1);
    assert_eq!(sink.get_sent_count().await, 1);

    // 3. Test Failure & Retry Backoff
    let event2 = TelemetryEvent::new(
        "terminal".to_string(),
        "cloud_vm_debian".to_string(),
        "irak_master".to_string(),
        "command_exec".to_string(),
        Utc::now(),
        serde_json::json!({"cmd": "git push"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
    );
    storage.save_event(&event2).await.unwrap();

    // Set sink to simulate failure
    sink.set_should_fail(true);
    let fail_summary = worker.process_batch(10).await.unwrap();
    assert_eq!(fail_summary.processed, 1);
    assert_eq!(fail_summary.failed, 1);

    // Verify retry_count incremented and retry_after set
    let (retry_count, last_error): (i64, String) = sqlx::query_as(
        "SELECT retry_count, last_error FROM outbox_events WHERE event_id = ?"
    )
    .bind(&event2.event_id)
    .fetch_one(pool)
    .await
    .unwrap();

    assert_eq!(retry_count, 1);
    assert!(last_error.contains("simulated"));
}

#[tokio::test]
async fn test_session_linking_api() {
    let storage = Arc::new(SqliteStorage::new("sqlite::memory:").await.unwrap());
    let app = create_router(AppState { storage });

    let link_req = serde_json::json!({
        "external_system": "rust_task_live_note",
        "external_task_id": "card_chunk_1042",
        "session_id": "sess_default",
        "project_id": "personal_ai",
        "note_id": "note_55"
    });

    let res = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/sessions/link")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&link_req).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(res.status(), StatusCode::OK);

    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let json_resp: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap();
    assert_eq!(json_resp["status"], "linked");
    assert_eq!(json_resp["external_system"], "rust_task_live_note");
    assert_eq!(json_resp["external_task_id"], "card_chunk_1042");
}

#[tokio::test]
async fn test_concurrent_idempotency_race_conditions() {
    let storage = Arc::new(SqliteStorage::new("sqlite::memory:").await.unwrap());

    // Pair A: Concurrent insert with SAME idempotency_key
    let key_a = "explicit_race_key_999".to_string();
    let event_a1 = TelemetryEvent::with_options(
        "whatsapp_bridge".to_string(),
        "pixel7_irak".to_string(),
        "irak_master".to_string(),
        "message_sent".to_string(),
        Utc::now(),
        serde_json::json!({"msg": "race A1"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
        None,
        Some(key_a.clone()),
    );
    let event_a2 = TelemetryEvent::with_options(
        "whatsapp_bridge".to_string(),
        "pixel7_irak".to_string(),
        "irak_master".to_string(),
        "message_sent".to_string(),
        Utc::now(),
        serde_json::json!({"msg": "race A2"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
        None,
        Some(key_a.clone()),
    );

    let storage_a1 = storage.clone();
    let storage_a2 = storage.clone();

    let handle_a1 = tokio::spawn(async move { storage_a1.save_event(&event_a1).await });
    let handle_a2 = tokio::spawn(async move { storage_a2.save_event(&event_a2).await });

    let (res_a1, res_a2) = tokio::join!(handle_a1, handle_a2);
    let res_a1 = res_a1.unwrap().unwrap();
    let res_a2 = res_a2.unwrap().unwrap();

    // Exactly one must be Created, and one must be AlreadyExists!
    let statuses_a = [res_a1.status, res_a2.status];
    assert_eq!(
        statuses_a.iter().filter(|s| matches!(s, IngestStatus::Created)).count(),
        1,
        "Exactly one concurrent request must win and be Created"
    );
    assert_eq!(
        statuses_a.iter().filter(|s| matches!(s, IngestStatus::AlreadyExists)).count(),
        1,
        "The competing concurrent request must gracefully report AlreadyExists"
    );

    // Pair B: Concurrent insert with SAME (source_id, source_record_id)
    let source_record = "chrome_record_race_555".to_string();
    let event_b1 = TelemetryEvent::with_options(
        "chrome_sqlite".to_string(),
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        Utc::now(),
        serde_json::json!({"url": "https://example.com/b1"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
        Some(source_record.clone()),
        None,
    );
    let event_b2 = TelemetryEvent::with_options(
        "chrome_sqlite".to_string(),
        "desktop_windows_irak".to_string(),
        "irak_master".to_string(),
        "url_visit".to_string(),
        Utc::now(),
        serde_json::json!({"url": "https://example.com/b2"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
        Some(source_record.clone()),
        None,
    );

    let storage_b1 = storage.clone();
    let storage_b2 = storage.clone();

    let handle_b1 = tokio::spawn(async move { storage_b1.save_event(&event_b1).await });
    let handle_b2 = tokio::spawn(async move { storage_b2.save_event(&event_b2).await });

    let (res_b1, res_b2) = tokio::join!(handle_b1, handle_b2);
    let res_b1 = res_b1.unwrap().unwrap();
    let res_b2 = res_b2.unwrap().unwrap();

    let statuses_b = [res_b1.status, res_b2.status];
    assert_eq!(
        statuses_b.iter().filter(|s| matches!(s, IngestStatus::Created)).count(),
        1,
        "Exactly one concurrent source_record_id request must win"
    );
    assert_eq!(
        statuses_b.iter().filter(|s| matches!(s, IngestStatus::AlreadyExists)).count(),
        1,
        "The competing concurrent source_record_id request must report AlreadyExists"
    );

    // Verify DB count: exactly 2 events total in DB
    let pool = storage.get_pool();
    let total_in_db: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM local_events")
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(total_in_db, 2, "Database must contain exactly 2 events, zero duplicates");
}

#[tokio::test]
async fn test_outbox_stale_processing_and_crash_recovery() {
    let storage = Arc::new(SqliteStorage::new("sqlite::memory:").await.unwrap());
    let sink = Arc::new(MockOutboxSink::new());
    let worker = OutboxWorker::with_options(storage.clone(), sink.clone(), 3, 60);

    let event = TelemetryEvent::new(
        "terminal".to_string(),
        "cloud_vm_debian".to_string(),
        "irak_master".to_string(),
        "command_exec".to_string(),
        Utc::now(),
        serde_json::json!({"cmd": "reboot"}),
        ConfidenceLevel::Proven,
        serde_json::json!({}),
    );
    storage.save_event(&event).await.unwrap();

    let pool = storage.get_pool();

    // Simulate crash: record was left stuck in PROCESSING 120 seconds ago
    sqlx::query(
        "UPDATE outbox_events SET status = 'PROCESSING', locked_at = datetime('now', '-120 seconds') WHERE event_id = ?"
    )
    .bind(&event.event_id)
    .execute(pool)
    .await
    .unwrap();

    // Verify stale reset recovers it
    let recovered = worker.reset_stale_processing().await.unwrap();
    assert_eq!(recovered, 1, "Stale locked record must be reset to PENDING");

    // Run worker: must successfully process the recovered event
    let summary = worker.process_batch(10).await.unwrap();
    assert_eq!(summary.processed, 1);
    assert_eq!(summary.succeeded, 1);

    // Verify status in DB is now SYNCED
    let status: String = sqlx::query_scalar("SELECT status FROM outbox_events WHERE event_id = ?")
        .bind(&event.event_id)
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(status, "SYNCED");
}

#[tokio::test]
async fn test_file_backed_sqlite_wal_and_checkpoint() {
    let temp_dir = std::env::temp_dir();
    let db_path = temp_dir.join(format!("telemetry_disk_test_{}.db", Uuid::now_v7()));
    let db_url = format!("sqlite://{}?mode=rwc", db_path.display());

    let storage = SqliteStorage::new(&db_url).await.unwrap();

    // Ingest events to disk
    for i in 0..10 {
        let event = TelemetryEvent::new(
            "chrome_sqlite".to_string(),
            "desktop_windows_irak".to_string(),
            "irak_master".to_string(),
            "url_visit".to_string(),
            Utc::now(),
            serde_json::json!({"page": i}),
            ConfidenceLevel::Proven,
            serde_json::json!({}),
        );
        storage.save_event(&event).await.unwrap();
    }

    // Verify WAL mode is indeed ACTIVE on disk
    let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode;")
        .fetch_one(storage.get_pool())
        .await
        .unwrap();
    assert_eq!(journal_mode.to_uppercase(), "WAL");

    // Checkpoint WAL to disk
    storage.checkpoint_wal().await.unwrap();

    // Clean up temporary disk file
    let _ = std::fs::remove_file(&db_path);
    let wal_path = temp_dir.join(format!("{}-wal", db_path.file_name().unwrap().to_str().unwrap()));
    let shm_path = temp_dir.join(format!("{}-shm", db_path.file_name().unwrap().to_str().unwrap()));
    let _ = std::fs::remove_file(wal_path);
    let _ = std::fs::remove_file(shm_path);
}
