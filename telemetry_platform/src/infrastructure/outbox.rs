use async_trait::async_trait;
use chrono::Utc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Mutex;
use crate::domain::events::TelemetryEvent;
use super::database::{EventRepository, RepoError, SqliteStorage};

#[async_trait]
pub trait OutboxSink: Send + Sync {
    async fn dispatch(&self, event: &TelemetryEvent) -> Result<(), String>;
}

/// In-memory mock sink for deterministic testing and local verification
pub struct MockOutboxSink {
    pub sent_events: Arc<Mutex<Vec<TelemetryEvent>>>,
    pub should_fail: AtomicBool,
}

impl Default for MockOutboxSink {
    fn default() -> Self {
        Self::new()
    }
}

impl MockOutboxSink {
    pub fn new() -> Self {
        Self {
            sent_events: Arc::new(Mutex::new(Vec::new())),
            should_fail: AtomicBool::new(false),
        }
    }

    pub fn set_should_fail(&self, fail: bool) {
        self.should_fail.store(fail, Ordering::SeqCst);
    }

    pub async fn get_sent_count(&self) -> usize {
        self.sent_events.lock().await.len()
    }
}

#[async_trait]
impl OutboxSink for MockOutboxSink {
    async fn dispatch(&self, event: &TelemetryEvent) -> Result<(), String> {
        if self.should_fail.load(Ordering::SeqCst) {
            return Err("Mock sink simulated network/downstream error".to_string());
        }
        self.sent_events.lock().await.push(event.clone());
        Ok(())
    }
}

#[derive(Debug, Clone, Default)]
pub struct OutboxBatchSummary {
    pub processed: usize,
    pub succeeded: usize,
    pub failed: usize,
}

pub struct OutboxWorker {
    storage: Arc<SqliteStorage>,
    sink: Arc<dyn OutboxSink>,
    max_retries: i64,
    stale_timeout_secs: i64,
}

impl OutboxWorker {
    pub fn new(storage: Arc<SqliteStorage>, sink: Arc<dyn OutboxSink>) -> Self {
        Self {
            storage,
            sink,
            max_retries: 5,
            stale_timeout_secs: 60,
        }
    }

    pub fn with_options(
        storage: Arc<SqliteStorage>,
        sink: Arc<dyn OutboxSink>,
        max_retries: i64,
        stale_timeout_secs: i64,
    ) -> Self {
        Self {
            storage,
            sink,
            max_retries,
            stale_timeout_secs,
        }
    }

    /// Crash recovery: resets items stuck in 'PROCESSING' longer than stale_timeout_secs back to 'PENDING'
    pub async fn reset_stale_processing(&self) -> Result<u64, RepoError> {
        let pool = self.storage.get_pool();
        let timeout_modifier = format!("-{} seconds", self.stale_timeout_secs);
        let query = r#"
            UPDATE outbox_events
            SET status = 'PENDING', locked_at = NULL
            WHERE status = 'PROCESSING' AND locked_at <= datetime('now', ?)
        "#;
        let res = sqlx::query(query)
            .bind(timeout_modifier)
            .execute(pool)
            .await?;
        Ok(res.rows_affected())
    }

    /// Acquires a batch of PENDING records, transitions to PROCESSING with locked_at timestamp,
    /// dispatches via sink, and records SYNCED or schedules exponential backoff on failure.
    pub async fn process_batch(&self, batch_size: usize) -> Result<OutboxBatchSummary, RepoError> {
        // 1. Recover any stale processing items
        self.reset_stale_processing().await?;

        let pool = self.storage.get_pool();
        let now = Utc::now();

        // 2. Fetch pending events whose retry_after is null or <= now
        let records = sqlx::query_as::<_, (i64, String, i64)>(
            r#"
            SELECT outbox_id, event_id, retry_count
            FROM outbox_events
            WHERE status = 'PENDING'
              AND (retry_after IS NULL OR retry_after <= ?)
            ORDER BY created_at ASC
            LIMIT ?
            "#,
        )
        .bind(now.to_rfc3339())
        .bind(batch_size as i64)
        .fetch_all(pool)
        .await?;

        let mut summary = OutboxBatchSummary::default();

        for (outbox_id, event_id, retry_count) in records {
            summary.processed += 1;

            // Lock record into PROCESSING
            sqlx::query(
                "UPDATE outbox_events SET status = 'PROCESSING', locked_at = ? WHERE outbox_id = ?"
            )
            .bind(now.to_rfc3339())
            .bind(outbox_id)
            .execute(pool)
            .await?;

            // Retrieve the full event
            let maybe_event = self.storage.get_event_by_id(&event_id).await?;

            if let Some(event) = maybe_event {
                match self.sink.dispatch(&event).await {
                    Ok(_) => {
                        // Successfully dispatched
                        sqlx::query(
                            "UPDATE outbox_events SET status = 'SYNCED', locked_at = NULL, updated_at = ? WHERE outbox_id = ?"
                        )
                        .bind(Utc::now().to_rfc3339())
                        .bind(outbox_id)
                        .execute(pool)
                        .await?;
                        summary.succeeded += 1;
                    }
                    Err(err_msg) => {
                        let new_retry = retry_count + 1;
                        if new_retry >= self.max_retries {
                            // Move to FAILED (Dead-letter status)
                            sqlx::query(
                                "UPDATE outbox_events SET status = 'FAILED', retry_count = ?, last_error = ?, locked_at = NULL, updated_at = ? WHERE outbox_id = ?"
                            )
                            .bind(new_retry)
                            .bind(err_msg)
                            .bind(Utc::now().to_rfc3339())
                            .bind(outbox_id)
                            .execute(pool)
                            .await?;
                        } else {
                            // Exponential backoff: 2 ^ new_retry seconds
                            let backoff_secs = 2_i64.pow(new_retry.min(10) as u32);
                            let retry_after = Utc::now() + chrono::Duration::seconds(backoff_secs);

                            sqlx::query(
                                "UPDATE outbox_events SET status = 'PENDING', retry_count = ?, retry_after = ?, last_error = ?, locked_at = NULL, updated_at = ? WHERE outbox_id = ?"
                            )
                            .bind(new_retry)
                            .bind(retry_after.to_rfc3339())
                            .bind(err_msg)
                            .bind(Utc::now().to_rfc3339())
                            .bind(outbox_id)
                            .execute(pool)
                            .await?;
                        }
                        summary.failed += 1;
                    }
                }
            } else {
                // Event missing from local_events (inconsistency)
                sqlx::query(
                    "UPDATE outbox_events SET status = 'FAILED', last_error = 'Orphan outbox record: event_id not found in local_events', locked_at = NULL WHERE outbox_id = ?"
                )
                .bind(outbox_id)
                .execute(pool)
                .await?;
                summary.failed += 1;
            }
        }

        Ok(summary)
    }
}
