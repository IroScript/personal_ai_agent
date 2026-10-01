use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use crate::domain::events::TelemetryEvent;
use crate::domain::sessions::Session;
use crate::domain::time::TimeInterval;

pub mod sqlite;
pub use sqlite::SqliteStorage;

#[derive(Debug, Error)]
pub enum RepoError {
    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("Conflict: event with idempotency key {0} already exists")]
    AlreadyExists(String),
    #[error("Validation error: {0}")]
    Validation(String),
    #[error("Entity not found: {0}")]
    NotFound(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum IngestStatus {
    Created,
    AlreadyExists,
    Invalid(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestResult {
    pub event_id: String,
    pub status: IngestStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchIngestResult {
    pub total: usize,
    pub accepted: usize,
    pub duplicates: usize,
    pub invalid: usize,
    pub results: Vec<IngestResult>,
}

#[derive(Debug, Clone, Default)]
pub struct EventFilter {
    pub user_id: Option<String>,
    pub source_id: Option<String>,
    pub device_id: Option<String>,
    pub event_type: Option<String>,
    pub project_id: Option<String>,
    pub task_id: Option<String>,
    pub note_id: Option<String>,
    pub start_time: Option<DateTime<Utc>>,
    pub end_time: Option<DateTime<Utc>>,
    pub cursor: Option<String>,
    pub limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PaginatedEvents {
    pub items: Vec<TelemetryEvent>,
    pub next_cursor: Option<String>,
    pub has_more: bool,
    pub limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutboxRecord {
    pub outbox_id: i64,
    pub event_id: String,
    pub status: String,
    pub retry_count: i64,
    pub last_error: Option<String>,
    pub locked_at: Option<DateTime<Utc>>,
    pub retry_after: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[async_trait]
pub trait EventRepository: Send + Sync {
    async fn save_event(&self, event: &TelemetryEvent) -> Result<IngestResult, RepoError>;
    async fn save_batch(&self, events: &[TelemetryEvent]) -> Result<BatchIngestResult, RepoError>;
    async fn get_event_by_id(&self, event_id: &str) -> Result<Option<TelemetryEvent>, RepoError>;
    async fn get_event_by_idempotency_key(&self, key: &str) -> Result<Option<TelemetryEvent>, RepoError>;
    async fn list_events_paginated(&self, filter: &EventFilter) -> Result<PaginatedEvents, RepoError>;
}

#[async_trait]
pub trait SessionRepository: Send + Sync {
    async fn create_session(&self, session: &Session) -> Result<(), RepoError>;
    async fn get_session(&self, session_id: &str) -> Result<Option<Session>, RepoError>;
    async fn list_sessions(&self, user_id: &str, limit: usize) -> Result<Vec<Session>, RepoError>;
    async fn link_external_task(
        &self,
        link_id: &str,
        session_id: Option<&str>,
        external_system: &str,
        external_task_id: &str,
        project_id: Option<&str>,
        note_id: Option<&str>,
    ) -> Result<(), RepoError>;
}

#[async_trait]
pub trait AuditRepository: Send + Sync {
    async fn save_interval(&self, interval: &TimeInterval, session_id: Option<&str>) -> Result<(), RepoError>;
    async fn save_intervals(&self, intervals: &[TimeInterval], session_id: Option<&str>) -> Result<(), RepoError>;
    async fn get_intervals(&self, start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Vec<TimeInterval>, RepoError>;
    async fn derive_intervals(&self, start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Vec<TimeInterval>, RepoError>;
}
