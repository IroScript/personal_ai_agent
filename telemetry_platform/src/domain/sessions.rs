use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use super::evidence::ConfidenceLevel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionBoundaryReason {
    InactivityTimeout,
    ExplicitProjectSwitch,
    DayBoundary,
    DeviceChange,
    Manual,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub session_id: String,
    pub user_id: String,
    pub project_id: Option<String>,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub boundary_reason: SessionBoundaryReason,
    pub confidence: ConfidenceLevel,
    pub metadata: serde_json::Value,
    pub created_at: DateTime<Utc>,
}
