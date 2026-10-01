use axum::{
    routing::{get, post},
    Router,
};
use super::handlers::{
    audit_time_investment, health, ingest_batch, ingest_event, link_session, list_events, ready,
    AppState,
};

pub fn create_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/ready", get(ready))
        .route("/api/v1/events", post(ingest_event).get(list_events))
        .route("/api/v1/events/batch", post(ingest_batch))
        .route("/api/v1/sessions/link", post(link_session))
        .route("/api/v1/audit/time-investment", get(audit_time_investment))
        .with_state(state)
}
