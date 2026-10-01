use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use telemetry_platform::api::handlers::AppState;
use telemetry_platform::api::routes::create_router;
use telemetry_platform::infrastructure::database::sqlite::SqliteStorage;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Initialize Logging
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "telemetry_platform=debug,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("🚀 Initializing Personal Digital History & Telemetry Platform...");

    // 2. Initialize Database (Edge SQLite with WAL mode)
    let db_url = std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "sqlite://telemetry_edge.db?mode=rwc".to_string());

    info!("📦 Connecting to SQLite Edge storage at {}", db_url);
    let storage = SqliteStorage::new(&db_url).await?;

    // Seed default devices and sources if not present
    seed_defaults(&storage).await?;

    let app_state = AppState {
        storage: Arc::new(storage),
    };

    // 3. Build Axum Router
    let app = create_router(app_state);

    // 4. Start HTTP Server
    let port = std::env::var("PORT").unwrap_or_else(|_| "3030".to_string());
    let addr = format!("0.0.0.0:{}", port);
    let listener = TcpListener::bind(&addr).await?;

    info!("🌟 Telemetry Backend listening on http://{}", addr);
    info!("   GET  /health");
    info!("   GET  /ready");
    info!("   POST /api/v1/events");
    info!("   GET  /api/v1/events");
    info!("   POST /api/v1/events/batch");
    info!("   POST /api/v1/sessions/link");
    info!("   GET  /api/v1/audit/time-investment");

    axum::serve(listener, app).await?;

    Ok(())
}

async fn seed_defaults(storage: &SqliteStorage) -> Result<(), Box<dyn std::error::Error>> {
    let pool = storage.get_pool();

    // Default devices
    sqlx::query(
        "INSERT OR IGNORE INTO devices (device_id, device_name, device_type, os_info) VALUES (?, ?, ?, ?)"
    )
    .bind("desktop_windows_irak")
    .bind("Irak Windows PC")
    .bind("desktop")
    .bind("Windows 11 Pro 64-bit")
    .execute(pool)
    .await?;

    sqlx::query(
        "INSERT OR IGNORE INTO devices (device_id, device_name, device_type, os_info) VALUES (?, ?, ?, ?)"
    )
    .bind("pixel7_irak")
    .bind("Irak Google Pixel 7")
    .bind("mobile")
    .bind("Android 14 / Google Play Services")
    .execute(pool)
    .await?;

    sqlx::query(
        "INSERT OR IGNORE INTO devices (device_id, device_name, device_type, os_info) VALUES (?, ?, ?, ?)"
    )
    .bind("cloud_vm_debian")
    .bind("AGY Cloud Server VM")
    .bind("server")
    .bind("Debian Linux 12 x86_64")
    .execute(pool)
    .await?;

    // Default sources
    let sources = [
        ("google_activity", "Google MyActivity Scraper", "cloud_scraper"),
        ("chrome_sqlite", "Chrome SQLite Master History", "browser"),
        ("openrecall", "OpenRecall Visual & OCR Snapshots", "desktop_ocr"),
        ("android_activity", "Android OS UsageStats & Events", "mobile_telemetry"),
        ("whatsapp_bridge", "WhatsApp Baileys Multi-Device Bridge", "chat_bridge"),
        ("ai_agent", "Antigravity Multi-Agent Runner", "ai_runtime"),
        ("terminal", "Linux / Windows Shell Commands", "terminal"),
    ];

    for (s_id, s_name, s_cat) in sources {
        sqlx::query(
            "INSERT OR IGNORE INTO sources (source_id, source_name, source_category) VALUES (?, ?, ?)"
        )
        .bind(s_id)
        .bind(s_name)
        .bind(s_cat)
        .execute(pool)
        .await?;
    }

    Ok(())
}
