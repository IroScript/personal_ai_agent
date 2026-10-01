use chrono::{Duration, Utc};
use std::sync::Arc;
use std::time::Instant;
use uuid::Uuid;
use telemetry_platform::domain::events::TelemetryEvent;
use telemetry_platform::domain::evidence::ConfidenceLevel;
use telemetry_platform::infrastructure::database::{EventFilter, EventRepository, SqliteStorage};
use telemetry_platform::infrastructure::outbox::{MockOutboxSink, OutboxWorker};

#[tokio::test]
async fn test_benchmark_in_memory_throughput() {
    println!("\n=======================================================");
    println!("   TELEMETRY PLATFORM — IN-MEMORY SQLITE BENCHMARK     ");
    println!("=======================================================");

    let storage = SqliteStorage::new("sqlite::memory:").await.unwrap();
    let base_time = Utc::now();

    // -------------------------------------------------------------
    // Benchmark 1: Ingest 1,000 individual events (Single Ingest)
    // -------------------------------------------------------------
    let start_1k = Instant::now();
    for i in 0..1_000 {
        let event = TelemetryEvent::with_options(
            "chrome_sqlite".to_string(),
            "desktop_windows_irak".to_string(),
            "irak_master".to_string(),
            "url_visit".to_string(),
            base_time + Duration::milliseconds(i),
            serde_json::json!({"url": format!("https://benchmark.test/page_{}", i)}),
            ConfidenceLevel::Proven,
            serde_json::json!({}),
            Some(format!("bench_1k_{}", i)),
            None,
        );
        storage.save_event(&event).await.unwrap();
    }
    let elapsed_1k = start_1k.elapsed();
    let throughput_1k = 1_000.0 / elapsed_1k.as_secs_f64();
    println!(
        "► 1,000 Events (Single Ingestion): {:.2?} ({:.1} events/sec)",
        elapsed_1k, throughput_1k
    );

    // -------------------------------------------------------------
    // Benchmark 2: Ingest 10,000 events in batches of 200
    // -------------------------------------------------------------
    let total_events = 10_000;
    let batch_size = 200;
    let num_batches = total_events / batch_size;

    let start_10k = Instant::now();
    for b in 0..num_batches {
        let mut batch = Vec::with_capacity(batch_size);
        for i in 0..batch_size {
            let idx = b * batch_size + i;
            batch.push(TelemetryEvent::with_options(
                "whatsapp_bridge".to_string(),
                "pixel7_irak".to_string(),
                "irak_master".to_string(),
                "message_sent".to_string(),
                base_time + Duration::milliseconds(idx as i64 + 1_000),
                serde_json::json!({"text": "bench", "idx": idx}),
                ConfidenceLevel::Proven,
                serde_json::json!({}),
                Some(format!("bench_10k_{}", idx)),
                None,
            ));
        }
        let res = storage.save_batch(&batch).await.unwrap();
        assert_eq!(res.accepted, batch_size);
    }
    let elapsed_10k = start_10k.elapsed();
    let throughput_10k = (total_events as f64) / elapsed_10k.as_secs_f64();
    println!(
        "► 10,000 Events (Batched x200):    {:.2?} ({:.1} events/sec)",
        elapsed_10k, throughput_10k
    );

    // -------------------------------------------------------------
    // Benchmark 3: Keyset Pagination Query Latency over 11,000 records
    // -------------------------------------------------------------
    let start_query = Instant::now();
    let filter = EventFilter {
        limit: 50,
        ..Default::default()
    };
    let page = storage.list_events_paginated(&filter).await.unwrap();
    let elapsed_query = start_query.elapsed();
    assert_eq!(page.items.len(), 50);
    println!(
        "► Keyset Query (50 items / 11,000 rows): {:.2?} (next_cursor exists: {})",
        elapsed_query,
        page.next_cursor.is_some()
    );
    println!("=======================================================\n");
}

#[tokio::test]
async fn test_benchmark_file_backed_concurrent_workload() {
    println!("\n=======================================================");
    println!("   TELEMETRY PLATFORM — FILE-BACKED CONCURRENT WORKLOAD");
    println!("   (Real Disk + WAL + Concurrent Writers + Readers + Outbox)");
    println!("=======================================================");

    let temp_dir = std::env::temp_dir();
    let db_path = temp_dir.join(format!("telemetry_bench_concurrent_{}.db", Uuid::now_v7()));
    let db_url = format!("sqlite://{}?mode=rwc", db_path.display());

    let storage = Arc::new(SqliteStorage::new(&db_url).await.unwrap());
    let sink = Arc::new(MockOutboxSink::new());
    let worker = Arc::new(OutboxWorker::new(storage.clone(), sink.clone()));

    // Verify WAL mode on real disk
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode;")
        .fetch_one(storage.get_pool())
        .await
        .unwrap();
    println!("► SQLite Journal Mode on Disk: {}", journal.to_uppercase());

    let num_writers = 5;
    let events_per_writer = 200; // total 1,000 concurrent events written to disk
    let base_time = Utc::now();

    let start_total = Instant::now();

    // 1. Launch 5 Concurrent Writer Tasks
    let mut writer_handles = Vec::new();
    for w in 0..num_writers {
        let storage_clone = storage.clone();
        let handle = tokio::spawn(async move {
            let mut accepted = 0;
            for i in 0..events_per_writer {
                let idx = w * events_per_writer + i;
                let event = TelemetryEvent::with_options(
                    "terminal".to_string(),
                    "cloud_vm_debian".to_string(),
                    "irak_master".to_string(),
                    "command_exec".to_string(),
                    base_time + Duration::milliseconds(idx as i64),
                    serde_json::json!({"writer": w, "seq": i}),
                    ConfidenceLevel::Proven,
                    serde_json::json!({}),
                    Some(format!("disk_w{}_rec{}", w, i)),
                    None,
                );
                let res = storage_clone.save_event(&event).await.unwrap();
                if matches!(res.status, telemetry_platform::infrastructure::database::IngestStatus::Created) {
                    accepted += 1;
                }
            }
            accepted
        });
        writer_handles.push(handle);
    }

    // 2. Launch Concurrent Reader (Keyset query polling while writes are happening)
    let storage_reader = storage.clone();
    let reader_handle = tokio::spawn(async move {
        let mut query_count = 0;
        let mut total_latency = std::time::Duration::ZERO;
        for _ in 0..10 {
            tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
            let q_start = Instant::now();
            let filter = EventFilter {
                limit: 25,
                ..Default::default()
            };
            let _ = storage_reader.list_events_paginated(&filter).await;
            total_latency += q_start.elapsed();
            query_count += 1;
        }
        (query_count, total_latency / query_count.max(1))
    });

    // 3. Await all writers
    let mut total_written = 0;
    for handle in writer_handles {
        total_written += handle.await.unwrap();
    }
    let write_elapsed = start_total.elapsed();
    let write_throughput = (total_written as f64) / write_elapsed.as_secs_f64();

    // 4. Await reader metrics
    let (read_queries, avg_read_latency) = reader_handle.await.unwrap();

    println!(
        "► Concurrent Writers (5 tasks x 200 events): {:.2?} ({:.1} writes/sec to disk)",
        write_elapsed, write_throughput
    );
    println!(
        "► Concurrent Reader under Write Contention: {} queries, Avg Latency: {:.2?}",
        read_queries, avg_read_latency
    );

    // 5. Run Outbox Worker on the 1,000 written events
    let outbox_start = Instant::now();
    let outbox_summary = worker.process_batch(1_000).await.unwrap();
    let outbox_elapsed = outbox_start.elapsed();
    let outbox_throughput = (outbox_summary.succeeded as f64) / outbox_elapsed.as_secs_f64();

    println!(
        "► Outbox Worker Dispatch ({} items): {:.2?} ({:.1} dispatches/sec)",
        outbox_summary.succeeded, outbox_elapsed, outbox_throughput
    );

    // 6. WAL Checkpoint
    let cp_start = Instant::now();
    storage.checkpoint_wal().await.unwrap();
    println!("► WAL Checkpoint (TRUNCATE): {:.2?}", cp_start.elapsed());

    // Clean up temporary disk files
    let _ = std::fs::remove_file(&db_path);
    let wal_path = temp_dir.join(format!("{}-wal", db_path.file_name().unwrap().to_str().unwrap()));
    let shm_path = temp_dir.join(format!("{}-shm", db_path.file_name().unwrap().to_str().unwrap()));
    let _ = std::fs::remove_file(wal_path);
    let _ = std::fs::remove_file(shm_path);

    println!("=======================================================\n");
    assert_eq!(total_written, 1_000);
    assert_eq!(outbox_summary.succeeded, 1_000);
}
