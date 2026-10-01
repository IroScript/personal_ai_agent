use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;
use super::evidence::ConfidenceLevel;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryEvent {
    pub event_id: String,
    pub event_time: DateTime<Utc>,
    pub ingested_at: DateTime<Utc>,
    pub source_id: String,
    pub device_id: String,
    pub user_id: String,
    pub event_type: String,
    pub event_version: u32,
    pub schema_version: u32,
    pub session_id: Option<String>,
    pub project_id: Option<String>,
    pub task_id: Option<String>,
    pub note_id: Option<String>,
    pub trace_id: Option<String>,
    pub parent_event_id: Option<String>,
    pub sequence_number: Option<i64>,
    pub source_record_id: Option<String>,
    pub idempotency_key: String,
    pub payload: serde_json::Value,
    pub payload_hash: String,
    pub content_hash: Option<String>,
    pub confidence: ConfidenceLevel,
    pub provenance: serde_json::Value,
    pub created_at: DateTime<Utc>,
}

impl TelemetryEvent {
    /// Constructs a new TelemetryEvent with UUIDv7 and computed SHA-256 payload hash
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source_id: String,
        device_id: String,
        user_id: String,
        event_type: String,
        event_time: DateTime<Utc>,
        payload: serde_json::Value,
        confidence: ConfidenceLevel,
        provenance: serde_json::Value,
    ) -> Self {
        Self::with_options(
            source_id,
            device_id,
            user_id,
            event_type,
            event_time,
            payload,
            confidence,
            provenance,
            None,
            None,
        )
    }

    /// Constructs a new TelemetryEvent with source_record_id and explicit idempotency_key options
    #[allow(clippy::too_many_arguments)]
    pub fn with_options(
        source_id: String,
        device_id: String,
        user_id: String,
        event_type: String,
        event_time: DateTime<Utc>,
        payload: serde_json::Value,
        confidence: ConfidenceLevel,
        provenance: serde_json::Value,
        source_record_id: Option<String>,
        explicit_idempotency_key: Option<String>,
    ) -> Self {
        let now = Utc::now();
        let payload_str = serde_json::to_string(&payload).unwrap_or_default();
        let mut hasher = Sha256::new();
        hasher.update(payload_str.as_bytes());
        let payload_hash = hex::encode(hasher.finalize());

        let event_id = Uuid::now_v7().to_string();

        let idempotency_key = Self::compute_idempotency_key(
            &source_id,
            source_record_id.as_deref(),
            explicit_idempotency_key.as_deref(),
            &device_id,
            &user_id,
            &event_type,
            &event_time,
            &payload_hash,
        );

        Self {
            event_id,
            event_time,
            ingested_at: now,
            source_id,
            device_id,
            user_id,
            event_type,
            event_version: 1,
            schema_version: 1,
            session_id: None,
            project_id: None,
            task_id: None,
            note_id: None,
            trace_id: None,
            parent_event_id: None,
            sequence_number: None,
            source_record_id,
            idempotency_key,
            payload,
            payload_hash,
            content_hash: None,
            confidence,
            provenance,
            created_at: now,
        }
    }

    /// Deterministic Idempotency Key Computation:
    /// 1. If explicit idempotency key provided by collector -> use "key:<source_id>:<key>"
    /// 2. If stable source_record_id provided -> use "src:<source_id>:<source_record_id>"
    /// 3. Fallback: deterministic composite hash over (source_id, device_id, user_id, event_type, event_time_millis, payload_hash)
    ///    This guarantees that the SAME payload at a DIFFERENT time is a NEW EVENT!
    #[allow(clippy::too_many_arguments)]
    pub fn compute_idempotency_key(
        source_id: &str,
        source_record_id: Option<&str>,
        explicit_key: Option<&str>,
        device_id: &str,
        user_id: &str,
        event_type: &str,
        event_time: &DateTime<Utc>,
        payload_hash: &str,
    ) -> String {
        if let Some(key) = explicit_key {
            let trimmed = key.trim();
            if !trimmed.is_empty() {
                return format!("key:{}:{}", source_id, trimmed);
            }
        }
        if let Some(rec_id) = source_record_id {
            let trimmed = rec_id.trim();
            if !trimmed.is_empty() {
                return format!("src:{}:{}", source_id, trimmed);
            }
        }
        let mut hasher = Sha256::new();
        hasher.update(format!(
            "fb:{}:{}:{}:{}:{}:{}",
            source_id,
            device_id,
            user_id,
            event_type,
            event_time.timestamp_millis(),
            payload_hash
        ));
        format!("fb:{}", hex::encode(hasher.finalize()))
    }
}
