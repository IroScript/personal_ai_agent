use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use crate::domain::events::TelemetryEvent;
use crate::domain::evidence::ConfidenceLevel;
use crate::domain::time::TimeInterval;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestEventRequest {
    pub source_id: String,
    pub device_id: String,
    pub user_id: String,
    pub event_type: String,
    pub event_time: Option<DateTime<Utc>>,
    pub source_record_id: Option<String>,
    pub idempotency_key: Option<String>,
    pub payload: serde_json::Value,
    pub confidence: Option<ConfidenceLevel>,
    pub provenance: Option<serde_json::Value>,
    pub session_id: Option<String>,
    pub project_id: Option<String>,
    pub task_id: Option<String>,
    pub note_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestBatchRequest {
    pub batch_id: String,
    pub source_id: String,
    pub device_id: String,
    pub events: Vec<IngestEventRequest>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ListEventsQuery {
    pub user_id: Option<String>,
    pub source_id: Option<String>,
    pub device_id: Option<String>,
    pub event_type: Option<String>,
    pub project_id: Option<String>,
    pub task_id: Option<String>,
    pub note_id: Option<String>,
    pub start_time: Option<String>,
    pub end_time: Option<String>,
    pub cursor: Option<String>,
    pub limit: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ListEventsResponse {
    pub items: Vec<TelemetryEvent>,
    pub next_cursor: Option<String>,
    pub has_more: bool,
    pub limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeInvestmentAuditResponse {
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub total_proven_user_active_seconds: i64,
    pub total_ai_processing_seconds: i64,
    pub total_proven_external_app_seconds: i64,
    pub total_proven_reading_seconds: i64,
    pub total_unknown_seconds: i64,
    pub confidence: ConfidenceLevel,
    pub intervals: Vec<TimeInterval>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntegrationTaskLinkRequest {
    pub external_system: String,
    pub external_task_id: String,
    pub session_id: Option<String>,
    pub project_id: Option<String>,
    pub note_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntegrationTaskLinkResponse {
    pub status: String,
    pub link_id: String,
    pub external_system: String,
    pub external_task_id: String,
    pub linked_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
    pub storage_engine: String,
    pub timestamp: DateTime<Utc>,
}
