# Integration Contract: Rust Task With Time Keeping & Live Note

## 1. Non-Invasive Architectural Boundary

The existing application [`Rust_Task_With_Time_Keeping_And_Live_Note`](https://github.com/IroScript/Rust_Task_With_Time_Keeping_And_Live_Note) is treated as an **independent client and integration target**, NOT as the primary telemetry database.

### Strict Safety Guarantees
1. **Zero Database Overwrites**: The existing SQLite database (`backend/data/app.db`) and its virtual-scrolling tables (`cards`, `card_chunks`) are **never modified, replaced, or merged**.
2. **Autonomous Operation**: The existing GUI application continues to function normally even if the telemetry platform is completely offline.
3. **Decoupled REST Interface**: All interaction occurs exclusively via HTTP REST endpoints under `/api/v1/integration/`.

---

## 2. Integration Mapping Model

```text
┌────────────────────────────────────────┐
│  Rust_Task_With_Time_Keeping_And_Note   │
│  (Desktop egui GUI + Local SQLite)     │
│  - Cards (quote_0, quote_1)            │
│  - Card Chunks (Lines 0..N)            │
│  - Planning Notes & Tasks              │
└──────────────────┬─────────────────────┘
                   │
                   │ HTTP REST Contract
                   │ (Stable External IDs)
                   ▼
┌────────────────────────────────────────┐
│  Personal Digital History Platform     │
│  - External Link Registry              │
│  - Universal Telemetry Ingestion       │
│  - Evidence Audit & Time Accounting    │
└────────────────────────────────────────┘
```

### Entity Correlation

| Existing Concept | Telemetry Platform Entity | Linkage Mechanism |
|---|---|---|
| Card / Quote Note | `Note` / `Artifact` | `external_system: "rust_task_live_note"`, `external_id: "quote_0"` |
| Workspace / Project | `Project` | `project_id: "youtube_pipeline"` |
| Task Item | `Task` | `task_id: "task_42"` |
| Active Working Period | `Session` | `session_id: "0191fa23-..."` |

---

## 3. Integration REST Endpoints

### 1. Link Task/Note to Telemetry Session
```http
POST /api/v1/integration/link-session
Content-Type: application/json

{
  "external_system": "rust_task_live_note",
  "external_id": "quote_0",
  "project_id": "personal_ai_agent",
  "session_id": "0191fa23-7b44-7000-8000-000000000001"
}
```

### 2. Query Time Investment for a Task/Note
```http
GET /api/v1/integration/time-investment?external_system=rust_task_live_note&external_id=quote_0
```

Response:
```json
{
  "external_id": "quote_0",
  "total_proven_user_active_seconds": 180,
  "total_ai_processing_seconds": 1420,
  "total_unknown_seconds": 450,
  "confidence": "PROVEN",
  "attributable_events_count": 42
}
```
