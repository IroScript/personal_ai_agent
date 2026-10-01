use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ConfidenceLevel {
    /// Directly supported by raw telemetry (e.g. keypress/submission timestamp, system clock log).
    Proven,
    /// Strongly supported by multiple independent signals, but not directly measured.
    Supported,
    /// Mathematically or model-estimated from incomplete evidence.
    Estimated,
    /// Insufficient evidence to establish fact.
    Unknown,
}

impl ConfidenceLevel {
    /// Combines two confidence levels using the most conservative / epistemic bound.
    /// - Proven + Proven => Proven
    /// - Any Supported with Proven => Supported
    /// - Any Estimated with higher => Estimated
    /// - Any Unknown => Unknown
    pub fn combine(self, other: Self) -> Self {
        match (self, other) {
            (Self::Unknown, _) | (_, Self::Unknown) => Self::Unknown,
            (Self::Estimated, _) | (_, Self::Estimated) => Self::Estimated,
            (Self::Supported, _) | (_, Self::Supported) => Self::Supported,
            (Self::Proven, Self::Proven) => Self::Proven,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActivityType {
    /// Physical or direct digital user interaction (e.g. prompt submission, touch, click).
    UserInteraction,
    /// Background AI execution, agent planning, or tool running. NOT user time.
    AiProcessing,
    /// Reading/reviewing AI response (Requires direct proof, otherwise Unknown).
    Reading,
    /// Active typing/drafting duration prior to submission.
    Typing,
    /// External application usage (e.g. WhatsApp, Chrome, Terminal, IDE).
    ExternalApp,
    /// Time where system cannot determine user activity.
    UnknownInterval,
    /// System-level background job, cron, sync.
    SystemProcessing,
}
