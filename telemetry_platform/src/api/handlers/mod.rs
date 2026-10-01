use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    Json,
};
use chrono::{DateTime, Utc};
use std::sync::Arc;
use uuid::Uuid;
use crate::api::dto::{
    HealthResponse, IngestBatchRequest, IngestEventRequest, IntegrationTaskLinkRequest,
    IntegrationTaskLinkResponse, ListEventsQuery, ListEventsResponse, TimeInvestmentAuditResponse,
};
use crate::domain::events::TelemetryEvent;
use crate::domain::evidence::{ActivityType, ConfidenceLevel};
use crate::domain::time::interval_union_by_activity;
use crate::infrastructure::database::{
    AuditRepository, EventFilter, EventRepository, IngestStatus, SessionRepository, SqliteStorage,
};

const MAX_BATCH_SIZE: usize = 500;

#[derive(Clone)]
pub struct AppState {
    pub storage: Arc<SqliteStorage>,
}

pub async fn health() -> impl IntoResponse {
    Json(HealthResponse {
        status: "healthy".to_string(),
        version: "0.1.0".to_string(),
        storage_engine: "sqlite-wal-edge".to_string(),
        timestamp: Utc::now(),
    })
}

pub async fn ready(State(state): State<AppState>) -> impl IntoResponse {
    match sqlx::query("SELECT 1").execute(state.storage.get_pool()).await {
        Ok(_) => (StatusCode::OK, "ready").into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "database connection failed").into_response(),
    }
}

pub async fn ingest_event(
    State(state): State<AppState>,
    Json(req): Json<IngestEventRequest>,
) -> impl IntoResponse {
    // Basic Request Validation
    if req.source_id.trim().is_empty()
        || req.device_id.trim().is_empty()
        || req.user_id.trim().is_empty()
        || req.event_type.trim().is_empty()
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "Validation failed: source_id, device_id, user_id, and event_type must not be empty"
            })),
        )
            .into_response();
    }

    let event_time = req.event_time.unwrap_or_else(Utc::now);
    let confidence = req.confidence.unwrap_or(ConfidenceLevel::Proven);
    let provenance = req.provenance.unwrap_or_else(|| serde_json::json!({"ingest_channel": "rest_api"}));

    let mut event = TelemetryEvent::with_options(
        req.source_id,
        req.device_id,
        req.user_id,
        req.event_type,
        event_time,
        req.payload,
        confidence,
        provenance,
        req.source_record_id,
        req.idempotency_key,
    );
    event.session_id = req.session_id;
    event.project_id = req.project_id;
    event.task_id = req.task_id;
    event.note_id = req.note_id;

    match state.storage.save_event(&event).await {
        Ok(res) => {
            let status_code = match &res.status {
                IngestStatus::Created => StatusCode::CREATED,
                IngestStatus::AlreadyExists => StatusCode::OK,
                IngestStatus::Invalid(_) => StatusCode::BAD_REQUEST,
            };
            (status_code, Json(serde_json::to_value(res).unwrap())).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        )
            .into_response(),
    }
}

pub async fn ingest_batch(
    State(state): State<AppState>,
    Json(req): Json<IngestBatchRequest>,
) -> impl IntoResponse {
    // 1. Batch size constraints
    if req.events.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "Validation failed: Batch cannot be empty"
            })),
        )
            .into_response();
    }

    if req.events.len() > MAX_BATCH_SIZE {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": format!("Validation failed: Batch size {} exceeds maximum allowed limit of {}", req.events.len(), MAX_BATCH_SIZE)
            })),
        )
            .into_response();
    }

    let mut events = Vec::with_capacity(req.events.len());

    for e_req in req.events {
        let event_time = e_req.event_time.unwrap_or_else(Utc::now);
        let confidence = e_req.confidence.unwrap_or(ConfidenceLevel::Proven);
        let provenance = e_req.provenance.unwrap_or_else(|| {
            serde_json::json!({
                "ingest_channel": "rest_batch_api",
                "batch_id": req.batch_id
            })
        });

        let mut event = TelemetryEvent::with_options(
            e_req.source_id,
            e_req.device_id,
            e_req.user_id,
            e_req.event_type,
            event_time,
            e_req.payload,
            confidence,
            provenance,
            e_req.source_record_id,
            e_req.idempotency_key,
        );
        event.session_id = e_req.session_id;
        event.project_id = e_req.project_id;
        event.task_id = e_req.task_id;
        event.note_id = e_req.note_id;
        events.push(event);
    }

    match state.storage.save_batch(&events).await {
        Ok(batch_res) => (StatusCode::OK, Json(serde_json::to_value(batch_res).unwrap())).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        )
            .into_response(),
    }
}

pub async fn list_events(
    State(state): State<AppState>,
    Query(query): Query<ListEventsQuery>,
) -> impl IntoResponse {
    let start_time = query
        .start_time
        .and_then(|s| DateTime::parse_from_rfc3339(&s).ok().map(|d| d.with_timezone(&Utc)));
    let end_time = query
        .end_time
        .and_then(|s| DateTime::parse_from_rfc3339(&s).ok().map(|d| d.with_timezone(&Utc)));

    let filter = EventFilter {
        user_id: query.user_id,
        source_id: query.source_id,
        device_id: query.device_id,
        event_type: query.event_type,
        project_id: query.project_id,
        task_id: query.task_id,
        note_id: query.note_id,
        start_time,
        end_time,
        cursor: query.cursor,
        limit: query.limit.unwrap_or(50),
    };

    match state.storage.list_events_paginated(&filter).await {
        Ok(paginated) => {
            let resp = ListEventsResponse {
                items: paginated.items,
                next_cursor: paginated.next_cursor,
                has_more: paginated.has_more,
                limit: paginated.limit,
            };
            (StatusCode::OK, Json(resp)).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        )
            .into_response(),
    }
}

pub async fn link_session(
    State(state): State<AppState>,
    Json(req): Json<IntegrationTaskLinkRequest>,
) -> impl IntoResponse {
    if req.external_system.trim().is_empty() || req.external_task_id.trim().is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "Validation failed: external_system and external_task_id must not be empty"
            })),
        )
            .into_response();
    }

    let link_id = Uuid::now_v7().to_string();

    match state
        .storage
        .link_external_task(
            &link_id,
            req.session_id.as_deref(),
            &req.external_system,
            &req.external_task_id,
            req.project_id.as_deref(),
            req.note_id.as_deref(),
        )
        .await
    {
        Ok(_) => {
            let resp = IntegrationTaskLinkResponse {
                status: "linked".to_string(),
                link_id,
                external_system: req.external_system,
                external_task_id: req.external_task_id,
                linked_at: Utc::now(),
            };
            (StatusCode::OK, Json(resp)).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        )
            .into_response(),
    }
}

#[derive(serde::Deserialize)]
pub struct AuditQuery {
    pub start_time: Option<String>,
    pub end_time: Option<String>,
}

pub async fn audit_time_investment(
    State(state): State<AppState>,
    Query(query): Query<AuditQuery>,
) -> impl IntoResponse {
    let now = Utc::now();
    let start = query
        .start_time
        .and_then(|s| DateTime::parse_from_rfc3339(&s).ok().map(|d| d.with_timezone(&Utc)))
        .unwrap_or_else(|| now - chrono::Duration::hours(24));
    let end = query
        .end_time
        .and_then(|s| DateTime::parse_from_rfc3339(&s).ok().map(|d| d.with_timezone(&Utc)))
        .unwrap_or(now);

    // 1. Fetch pre-calculated intervals from time_intervals table
    let mut intervals = state.storage.get_intervals(start, end).await.unwrap_or_default();

    // 2. If no explicit intervals exist, derive from local_events in the range
    if intervals.is_empty() {
        if let Ok(derived) = state.storage.derive_intervals(start, end).await {
            intervals = derived;
        }
    }

    // 3. Run multi-timeline Interval Union grouped by activity_type to strictly prevent double-counting
    let merged_intervals = interval_union_by_activity(intervals);

    let mut total_proven_user_active_seconds: i64 = 0;
    let mut total_ai_processing_seconds: i64 = 0;
    let mut total_proven_external_app_seconds: i64 = 0;
    let mut total_proven_reading_seconds: i64 = 0;
    let mut covered_active_seconds: i64 = 0;

    for interval in &merged_intervals {
        let dur = interval.duration_seconds();
        match interval.activity_type {
            ActivityType::UserInteraction | ActivityType::Typing => {
                if interval.confidence == ConfidenceLevel::Proven {
                    total_proven_user_active_seconds += dur;
                    covered_active_seconds += dur;
                }
            }
            ActivityType::AiProcessing => {
                total_ai_processing_seconds += dur;
            }
            ActivityType::ExternalApp => {
                if interval.confidence == ConfidenceLevel::Proven {
                    total_proven_external_app_seconds += dur;
                    covered_active_seconds += dur;
                }
            }
            ActivityType::Reading => {
                if interval.confidence == ConfidenceLevel::Proven {
                    total_proven_reading_seconds += dur;
                    covered_active_seconds += dur;
                }
            }
            ActivityType::SystemProcessing | ActivityType::UnknownInterval => {}
        }
    }

    let total_window_seconds = (end - start).num_seconds().max(0);
    let total_unknown_seconds = (total_window_seconds - covered_active_seconds).max(0);

    let resp = TimeInvestmentAuditResponse {
        start_time: start,
        end_time: end,
        total_proven_user_active_seconds,
        total_ai_processing_seconds,
        total_proven_external_app_seconds,
        total_proven_reading_seconds,
        total_unknown_seconds,
        confidence: ConfidenceLevel::Proven,
        intervals: merged_intervals,
    };

    Json(resp).into_response()
}
