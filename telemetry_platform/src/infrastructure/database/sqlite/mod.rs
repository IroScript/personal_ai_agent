use async_trait::async_trait;
use chrono::{DateTime, Utc};
use sqlx::{sqlite::SqlitePoolOptions, Pool, Row, Sqlite};
use uuid::Uuid;
use crate::domain::events::TelemetryEvent;
use crate::domain::evidence::{ActivityType, ConfidenceLevel};
use crate::domain::sessions::Session;
use crate::domain::time::TimeInterval;
use super::{
    AuditRepository, BatchIngestResult, EventFilter, EventRepository, IngestResult, IngestStatus,
    PaginatedEvents, RepoError, SessionRepository,
};

#[derive(Clone)]
pub struct SqliteStorage {
    pool: Pool<Sqlite>,
}

impl SqliteStorage {
    pub async fn new(database_url: &str) -> Result<Self, RepoError> {
        let pool = SqlitePoolOptions::new()
            .max_connections(5)
            .connect(database_url)
            .await?;

        // Apply WAL and performance/integrity pragmas
        sqlx::query("PRAGMA journal_mode = WAL;").execute(&pool).await?;
        sqlx::query("PRAGMA synchronous = NORMAL;").execute(&pool).await?;
        sqlx::query("PRAGMA foreign_keys = ON;").execute(&pool).await?;

        // Run migrations
        let migration_sql = include_str!("../../../migrations/0001_initial_telemetry_schema.sql");
        for statement in migration_sql.split(';') {
            let stmt = statement.trim();
            if !stmt.is_empty() {
                sqlx::query(stmt).execute(&pool).await?;
            }
        }

        Ok(Self { pool })
    }

    pub fn get_pool(&self) -> &Pool<Sqlite> {
        &self.pool
    }

    /// Explicit WAL checkpoint to flush write-ahead log to disk and truncate .db-wal
    pub async fn checkpoint_wal(&self) -> Result<(), RepoError> {
        sqlx::query("PRAGMA wal_checkpoint(TRUNCATE);")
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    fn row_to_event(r: &sqlx::sqlite::SqliteRow) -> Result<TelemetryEvent, RepoError> {
        let time_str: String = r.get("event_time");
        let ing_str: String = r.get("ingested_at");
        let created_str: String = r.get("created_at");
        let payload_str: String = r.get("payload");
        let prov_str: String = r.get("provenance");
        let conf_str: String = r.get("confidence");

        let confidence: ConfidenceLevel = serde_json::from_str(&format!("\"{}\"", conf_str))
            .unwrap_or(ConfidenceLevel::Unknown);

        Ok(TelemetryEvent {
            event_id: r.get("event_id"),
            event_time: DateTime::parse_from_rfc3339(&time_str)
                .map_err(|e| RepoError::Validation(e.to_string()))?
                .with_timezone(&Utc),
            ingested_at: DateTime::parse_from_rfc3339(&ing_str)
                .map_err(|e| RepoError::Validation(e.to_string()))?
                .with_timezone(&Utc),
            source_id: r.get("source_id"),
            device_id: r.get("device_id"),
            user_id: r.get("user_id"),
            event_type: r.get("event_type"),
            event_version: r.get::<i64, _>("event_version") as u32,
            schema_version: r.get::<i64, _>("schema_version") as u32,
            session_id: r.get("session_id"),
            project_id: r.get("project_id"),
            task_id: r.get("task_id"),
            note_id: r.get("note_id"),
            trace_id: r.get("trace_id"),
            parent_event_id: r.get("parent_event_id"),
            sequence_number: r.get("sequence_number"),
            source_record_id: r.get("source_record_id"),
            idempotency_key: r.get("idempotency_key"),
            payload: serde_json::from_str(&payload_str)?,
            payload_hash: r.get("payload_hash"),
            content_hash: r.get("content_hash"),
            confidence,
            provenance: serde_json::from_str(&prov_str)?,
            created_at: DateTime::parse_from_rfc3339(&created_str)
                .map_err(|e| RepoError::Validation(e.to_string()))?
                .with_timezone(&Utc),
        })
    }
}

#[async_trait]
impl EventRepository for SqliteStorage {
    async fn save_event(&self, event: &TelemetryEvent) -> Result<IngestResult, RepoError> {
        // Validation check
        if event.source_id.trim().is_empty()
            || event.device_id.trim().is_empty()
            || event.user_id.trim().is_empty()
            || event.event_type.trim().is_empty()
        {
            return Ok(IngestResult {
                event_id: event.event_id.clone(),
                status: IngestStatus::Invalid("Missing required event identity fields".to_string()),
            });
        }

        // 1. Idempotency Check by idempotency_key
        let existing_by_key = sqlx::query("SELECT event_id FROM local_events WHERE idempotency_key = ?")
            .bind(&event.idempotency_key)
            .fetch_optional(&self.pool)
            .await?;

        if let Some(row) = existing_by_key {
            let existing_id: String = row.get(0);
            return Ok(IngestResult {
                event_id: existing_id,
                status: IngestStatus::AlreadyExists,
            });
        }

        // 2. Idempotency Check by (source_id, source_record_id) if source_record_id is present
        if let Some(ref rec_id) = event.source_record_id {
            if !rec_id.trim().is_empty() {
                let existing_by_source = sqlx::query(
                    "SELECT event_id FROM local_events WHERE source_id = ? AND source_record_id = ?"
                )
                .bind(&event.source_id)
                .bind(rec_id)
                .fetch_optional(&self.pool)
                .await?;

                if let Some(row) = existing_by_source {
                    let existing_id: String = row.get(0);
                    return Ok(IngestResult {
                        event_id: existing_id,
                        status: IngestStatus::AlreadyExists,
                    });
                }
            }
        }

        // 3. Atomic Transaction: Insert into local_events + Insert into outbox_events
        let mut tx = self.pool.begin().await?;

        let insert_res = sqlx::query(
            r#"
            INSERT INTO local_events (
                event_id, event_time, ingested_at, source_id, device_id, user_id,
                event_type, event_version, schema_version, session_id, project_id,
                task_id, note_id, trace_id, parent_event_id, sequence_number,
                source_record_id, idempotency_key, payload, payload_hash, content_hash,
                confidence, provenance, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&event.event_id)
        .bind(event.event_time.to_rfc3339())
        .bind(event.ingested_at.to_rfc3339())
        .bind(&event.source_id)
        .bind(&event.device_id)
        .bind(&event.user_id)
        .bind(&event.event_type)
        .bind(event.event_version as i64)
        .bind(event.schema_version as i64)
        .bind(&event.session_id)
        .bind(&event.project_id)
        .bind(&event.task_id)
        .bind(&event.note_id)
        .bind(&event.trace_id)
        .bind(&event.parent_event_id)
        .bind(event.sequence_number)
        .bind(&event.source_record_id)
        .bind(&event.idempotency_key)
        .bind(serde_json::to_string(&event.payload)?)
        .bind(&event.payload_hash)
        .bind(&event.content_hash)
        .bind(serde_json::to_string(&event.confidence)?.replace('"', ""))
        .bind(serde_json::to_string(&event.provenance)?)
        .bind(event.created_at.to_rfc3339())
        .execute(&mut *tx)
        .await;

        if let Err(e) = insert_res {
            let is_unique_violation = e.as_database_error().is_some_and(|dbe| dbe.is_unique_violation())
                || e.to_string().contains("UNIQUE constraint failed");
            if is_unique_violation {
                let _ = tx.rollback().await;
                // Query the existing winner record that beat us in the race
                if let Ok(Some(row)) = sqlx::query("SELECT event_id FROM local_events WHERE idempotency_key = ?")
                    .bind(&event.idempotency_key)
                    .fetch_optional(&self.pool)
                    .await
                {
                    let existing_id: String = row.get(0);
                    return Ok(IngestResult {
                        event_id: existing_id,
                        status: IngestStatus::AlreadyExists,
                    });
                }
                if let Some(ref rec_id) = event.source_record_id {
                    if let Ok(Some(row)) = sqlx::query("SELECT event_id FROM local_events WHERE source_id = ? AND source_record_id = ?")
                        .bind(&event.source_id)
                        .bind(rec_id)
                        .fetch_optional(&self.pool)
                        .await
                    {
                        let existing_id: String = row.get(0);
                        return Ok(IngestResult {
                            event_id: existing_id,
                            status: IngestStatus::AlreadyExists,
                        });
                    }
                }
                return Ok(IngestResult {
                    event_id: event.event_id.clone(),
                    status: IngestStatus::AlreadyExists,
                });
            }
            return Err(RepoError::Database(e));
        }

        // Outbox entry: state PENDING for upstream sync
        sqlx::query(
            "INSERT INTO outbox_events (event_id, status, created_at, updated_at) VALUES (?, 'PENDING', ?, ?)"
        )
        .bind(&event.event_id)
        .bind(event.created_at.to_rfc3339())
        .bind(event.created_at.to_rfc3339())
        .execute(&mut *tx)
        .await?;

        tx.commit().await?;

        Ok(IngestResult {
            event_id: event.event_id.clone(),
            status: IngestStatus::Created,
        })
    }

    async fn save_batch(&self, events: &[TelemetryEvent]) -> Result<BatchIngestResult, RepoError> {
        let mut accepted = 0;
        let mut duplicates = 0;
        let mut invalid = 0;
        let mut results = Vec::with_capacity(events.len());

        for event in events {
            let res = self.save_event(event).await?;
            match res.status {
                IngestStatus::Created => accepted += 1,
                IngestStatus::AlreadyExists => duplicates += 1,
                IngestStatus::Invalid(_) => invalid += 1,
            }
            results.push(res);
        }

        Ok(BatchIngestResult {
            total: events.len(),
            accepted,
            duplicates,
            invalid,
            results,
        })
    }

    async fn get_event_by_id(&self, event_id: &str) -> Result<Option<TelemetryEvent>, RepoError> {
        let row = sqlx::query(
            r#"
            SELECT event_id, event_time, ingested_at, source_id, device_id, user_id,
                   event_type, event_version, schema_version, session_id, project_id,
                   task_id, note_id, trace_id, parent_event_id, sequence_number,
                   source_record_id, idempotency_key, payload, payload_hash, content_hash,
                   confidence, provenance, created_at
            FROM local_events
            WHERE event_id = ?
            "#
        )
        .bind(event_id)
        .fetch_optional(&self.pool)
        .await?;

        if let Some(r) = row {
            Ok(Some(Self::row_to_event(&r)?))
        } else {
            Ok(None)
        }
    }

    async fn get_event_by_idempotency_key(&self, key: &str) -> Result<Option<TelemetryEvent>, RepoError> {
        let row = sqlx::query(
            r#"
            SELECT event_id, event_time, ingested_at, source_id, device_id, user_id,
                   event_type, event_version, schema_version, session_id, project_id,
                   task_id, note_id, trace_id, parent_event_id, sequence_number,
                   source_record_id, idempotency_key, payload, payload_hash, content_hash,
                   confidence, provenance, created_at
            FROM local_events
            WHERE idempotency_key = ?
            "#
        )
        .bind(key)
        .fetch_optional(&self.pool)
        .await?;

        if let Some(r) = row {
            Ok(Some(Self::row_to_event(&r)?))
        } else {
            Ok(None)
        }
    }

    async fn list_events_paginated(&self, filter: &EventFilter) -> Result<PaginatedEvents, RepoError> {
        let limit = if filter.limit == 0 { 50 } else { filter.limit.min(100) };
        let fetch_limit = (limit + 1) as i64;

        // Keyset cursor parsing: format "<event_time_rfc3339>#<event_id>"
        let (cursor_time, cursor_id) = if let Some(ref c) = filter.cursor {
            let mut parts = c.splitn(2, '#');
            let t = parts.next().and_then(|s| DateTime::parse_from_rfc3339(s).ok().map(|d| d.with_timezone(&Utc)));
            let id = parts.next().map(|s| s.to_string());
            (t, id)
        } else {
            (None, None)
        };

        let cursor_time_str = cursor_time.map(|t| t.to_rfc3339());
        let start_time_str = filter.start_time.map(|t| t.to_rfc3339());
        let end_time_str = filter.end_time.map(|t| t.to_rfc3339());

        let query = r#"
            SELECT event_id, event_time, ingested_at, source_id, device_id, user_id,
                   event_type, event_version, schema_version, session_id, project_id,
                   task_id, note_id, trace_id, parent_event_id, sequence_number,
                   source_record_id, idempotency_key, payload, payload_hash, content_hash,
                   confidence, provenance, created_at
            FROM local_events
            WHERE (? IS NULL OR user_id = ?)
              AND (? IS NULL OR source_id = ?)
              AND (? IS NULL OR device_id = ?)
              AND (? IS NULL OR event_type = ?)
              AND (? IS NULL OR project_id = ?)
              AND (? IS NULL OR task_id = ?)
              AND (? IS NULL OR note_id = ?)
              AND (? IS NULL OR event_time >= ?)
              AND (? IS NULL OR event_time <= ?)
              AND (? IS NULL OR (event_time < ? OR (event_time = ? AND event_id < ?)))
            ORDER BY event_time DESC, event_id DESC
            LIMIT ?
        "#;

        let rows = sqlx::query(query)
            .bind(&filter.user_id)
            .bind(&filter.user_id)
            .bind(&filter.source_id)
            .bind(&filter.source_id)
            .bind(&filter.device_id)
            .bind(&filter.device_id)
            .bind(&filter.event_type)
            .bind(&filter.event_type)
            .bind(&filter.project_id)
            .bind(&filter.project_id)
            .bind(&filter.task_id)
            .bind(&filter.task_id)
            .bind(&filter.note_id)
            .bind(&filter.note_id)
            .bind(&start_time_str)
            .bind(&start_time_str)
            .bind(&end_time_str)
            .bind(&end_time_str)
            .bind(&cursor_time_str)
            .bind(&cursor_time_str)
            .bind(&cursor_time_str)
            .bind(&cursor_id)
            .bind(fetch_limit)
            .fetch_all(&self.pool)
            .await?;

        let mut items = Vec::new();
        for r in rows {
            items.push(Self::row_to_event(&r)?);
        }

        let has_more = items.len() > limit;
        if has_more {
            items.pop();
        }

        let next_cursor = if has_more {
            items.last().map(|last| format!("{}#{}", last.event_time.to_rfc3339(), last.event_id))
        } else {
            None
        };

        Ok(PaginatedEvents {
            items,
            next_cursor,
            has_more,
            limit,
        })
    }
}

#[async_trait]
impl SessionRepository for SqliteStorage {
    async fn create_session(&self, session: &Session) -> Result<(), RepoError> {
        let reason_str = serde_json::to_string(&session.boundary_reason)?;
        let conf_str = serde_json::to_string(&session.confidence)?;

        sqlx::query(
            r#"
            INSERT INTO sessions (
                session_id, user_id, project_id, start_time, end_time,
                boundary_reason, confidence, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&session.session_id)
        .bind(&session.user_id)
        .bind(&session.project_id)
        .bind(session.start_time.to_rfc3339())
        .bind(session.end_time.map(|t| t.to_rfc3339()))
        .bind(reason_str)
        .bind(conf_str)
        .bind(serde_json::to_string(&session.metadata)?)
        .bind(session.created_at.to_rfc3339())
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    async fn get_session(&self, session_id: &str) -> Result<Option<Session>, RepoError> {
        let row = sqlx::query(
            "SELECT session_id, user_id, project_id, start_time, end_time, boundary_reason, confidence, metadata, created_at FROM sessions WHERE session_id = ?"
        )
        .bind(session_id)
        .fetch_optional(&self.pool)
        .await?;

        if let Some(r) = row {
            let start_str: String = r.get("start_time");
            let end_str: Option<String> = r.get("end_time");
            let reason_str: String = r.get("boundary_reason");
            let conf_str: String = r.get("confidence");
            let meta_str: String = r.get("metadata");
            let created_str: String = r.get("created_at");

            Ok(Some(Session {
                session_id: r.get("session_id"),
                user_id: r.get("user_id"),
                project_id: r.get("project_id"),
                start_time: DateTime::parse_from_rfc3339(&start_str)
                    .map_err(|e| RepoError::Validation(e.to_string()))?
                    .with_timezone(&Utc),
                end_time: end_str.and_then(|s| DateTime::parse_from_rfc3339(&s).ok().map(|d| d.with_timezone(&Utc))),
                boundary_reason: serde_json::from_str(&reason_str)?,
                confidence: serde_json::from_str(&conf_str)?,
                metadata: serde_json::from_str(&meta_str)?,
                created_at: DateTime::parse_from_rfc3339(&created_str)
                    .map_err(|e| RepoError::Validation(e.to_string()))?
                    .with_timezone(&Utc),
            }))
        } else {
            Ok(None)
        }
    }

    async fn list_sessions(&self, user_id: &str, limit: usize) -> Result<Vec<Session>, RepoError> {
        let l = if limit == 0 { 20 } else { limit };
        let rows = sqlx::query("SELECT session_id FROM sessions WHERE user_id = ? ORDER BY start_time DESC LIMIT ?")
            .bind(user_id)
            .bind(l as i64)
            .fetch_all(&self.pool)
            .await?;

        let mut list = Vec::new();
        for r in rows {
            let id: String = r.get(0);
            if let Some(s) = self.get_session(&id).await? {
                list.push(s);
            }
        }
        Ok(list)
    }

    async fn link_external_task(
        &self,
        link_id: &str,
        session_id: Option<&str>,
        external_system: &str,
        external_task_id: &str,
        project_id: Option<&str>,
        note_id: Option<&str>,
    ) -> Result<(), RepoError> {
        sqlx::query(
            r#"
            INSERT INTO session_links (
                link_id, session_id, external_system, external_task_id, project_id, note_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(link_id)
        .bind(session_id)
        .bind(external_system)
        .bind(external_task_id)
        .bind(project_id)
        .bind(note_id)
        .bind(Utc::now().to_rfc3339())
        .execute(&self.pool)
        .await?;

        Ok(())
    }
}

#[async_trait]
impl AuditRepository for SqliteStorage {
    async fn save_interval(&self, interval: &TimeInterval, session_id: Option<&str>) -> Result<(), RepoError> {
        let interval_id = Uuid::now_v7().to_string();
        let act_str = serde_json::to_string(&interval.activity_type)?.replace('"', "");
        let conf_str = serde_json::to_string(&interval.confidence)?.replace('"', "");
        let src_str = serde_json::to_string(&interval.source_event_ids)?;

        sqlx::query(
            r#"
            INSERT INTO time_intervals (
                interval_id, session_id, start_time, end_time, duration_seconds,
                activity_type, confidence, source_event_ids, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&interval_id)
        .bind(session_id)
        .bind(interval.start_time.to_rfc3339())
        .bind(interval.end_time.to_rfc3339())
        .bind(interval.duration_seconds())
        .bind(act_str)
        .bind(conf_str)
        .bind(src_str)
        .bind(Utc::now().to_rfc3339())
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    async fn save_intervals(&self, intervals: &[TimeInterval], session_id: Option<&str>) -> Result<(), RepoError> {
        for interval in intervals {
            self.save_interval(interval, session_id).await?;
        }
        Ok(())
    }

    async fn get_intervals(&self, start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Vec<TimeInterval>, RepoError> {
        let rows = sqlx::query(
            r#"
            SELECT interval_id, start_time, end_time, activity_type, confidence, source_event_ids
            FROM time_intervals
            WHERE end_time >= ? AND start_time <= ?
            ORDER BY start_time ASC
            "#
        )
        .bind(start.to_rfc3339())
        .bind(end.to_rfc3339())
        .fetch_all(&self.pool)
        .await?;

        let mut list = Vec::new();
        for r in rows {
            let s_str: String = r.get("start_time");
            let e_str: String = r.get("end_time");
            let act_str: String = r.get("activity_type");
            let conf_str: String = r.get("confidence");
            let src_str: String = r.get("source_event_ids");

            list.push(TimeInterval {
                start_time: DateTime::parse_from_rfc3339(&s_str)
                    .map_err(|e| RepoError::Validation(e.to_string()))?
                    .with_timezone(&Utc),
                end_time: DateTime::parse_from_rfc3339(&e_str)
                    .map_err(|e| RepoError::Validation(e.to_string()))?
                    .with_timezone(&Utc),
                activity_type: serde_json::from_str(&format!("\"{}\"", act_str)).unwrap_or(ActivityType::UnknownInterval),
                confidence: serde_json::from_str(&format!("\"{}\"", conf_str)).unwrap_or(ConfidenceLevel::Unknown),
                source_event_ids: serde_json::from_str(&src_str).unwrap_or_default(),
            });
        }
        Ok(list)
    }

    async fn derive_intervals(&self, start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Vec<TimeInterval>, RepoError> {
        let rows = sqlx::query(
            r#"
            SELECT event_id, event_time, event_type, confidence, payload
            FROM local_events
            WHERE event_time >= ? AND event_time <= ?
            ORDER BY event_time ASC
            "#
        )
        .bind(start.to_rfc3339())
        .bind(end.to_rfc3339())
        .fetch_all(&self.pool)
        .await?;

        let mut derived = Vec::new();
        for r in rows {
            let event_id: String = r.get("event_id");
            let time_str: String = r.get("event_time");
            let event_type: String = r.get("event_type");
            let conf_str: String = r.get("confidence");
            let payload_str: String = r.get("payload");

            let event_time = DateTime::parse_from_rfc3339(&time_str)
                .map_err(|e| RepoError::Validation(e.to_string()))?
                .with_timezone(&Utc);
            let confidence: ConfidenceLevel = serde_json::from_str(&format!("\"{}\"", conf_str))
                .unwrap_or(ConfidenceLevel::Proven);
            let payload_val: serde_json::Value = serde_json::from_str(&payload_str).unwrap_or_default();

            // Extract duration if present in payload, default to 1 second for point events
            let duration_secs = payload_val.get("duration_seconds")
                .and_then(|v| v.as_i64())
                .unwrap_or(1)
                .max(1);

            let end_time = event_time + chrono::Duration::seconds(duration_secs);

            let activity_type = match event_type.as_str() {
                "ai_processing" | "agent_run" | "tool_execution" => ActivityType::AiProcessing,
                "user_prompt" | "prompt_sent" | "keypress" | "mouse_click" => ActivityType::UserInteraction,
                "typing" => ActivityType::Typing,
                "reading" => ActivityType::Reading,
                "chrome_visit" | "external_app" | "message_sent" => ActivityType::ExternalApp,
                _ => ActivityType::UnknownInterval,
            };

            derived.push(TimeInterval {
                start_time: event_time,
                end_time,
                activity_type,
                confidence,
                source_event_ids: vec![event_id],
            });
        }

        Ok(derived)
    }
}
