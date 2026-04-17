# Architecture: Target State
**Produced by:** Architect — Phase 1 Design
**Date:** 2026-04-16
**Based on:** `architecture_current_state.md`, `architecture_gaps.md`, `sanad_masterplan.md`
**Branch:** feat/cross-agent-workflow

---

## Design Principles

Before the spec: four binding constraints that shaped every decision below.

1. **No broken chain.** All workflow routing goes through the Orchestrator. Agents never call each other directly.
2. **No silent failures.** Every step transition is persisted before acknowledgment. If the Orchestrator crashes mid-handoff, no work is lost.
3. **No blind execution.** The `to_run.py` dynamic script model is replaced with a structured tool-call JSON protocol. Agents declare what they want to do; the harness validates and executes.
4. **No stale state.** Context is saved every 15 minutes and on every BLOCKED/COMPLETE event. Any agent can be restarted and resume from its last checkpoint.

---

## 1. Task Orchestrator — Full API Spec

**Service:** `task_orchestrator` — FastAPI on port **8100**, SQLite at `orchestrator.db`
**Base URL:** `http://task_orchestrator:8100`
**Auth:** `X-API-Key` header for all endpoints except `/health`

---

### POST /tasks

Create a new task workflow.

**Request body:**
```json
{
  "prompt":         "string (required) — the original user request",
  "requester_id":   "string (required) — Telegram user ID or API caller ID",
  "requester_type": "string (required) — enum: telegram | api | agent",
  "workflow_type":  "string (optional, default: standard) — enum: standard | research | build | hotfix",
  "callback_url":   "string (optional) — URL to POST result when workflow finishes",
  "metadata":       "object (optional) — arbitrary key-value pairs"
}
```

**Response 201 Created:**
```json
{
  "task_id":    "string — UUID4 prefixed with 'tsk_'",
  "status":     "PENDING",
  "created_at": "ISO 8601 timestamp"
}
```

**Response 422 Unprocessable Entity:**
```json
{
  "error": "validation_error",
  "detail": [{"field": "prompt", "msg": "field required"}]
}
```

**Response 401 Unauthorized:**
```json
{"error": "invalid_api_key"}
```

---

### GET /tasks/{task_id}

Retrieve full task status including all step history.

**Path parameter:** `task_id` — the `tsk_` prefixed UUID

**Response 200 OK:**
```json
{
  "task_id":         "tsk_abc123",
  "prompt":          "string — original prompt",
  "status":          "string — enum: PENDING|ASSIGNED|IN_PROGRESS|AWAITING_HANDOFF|BLOCKED|DONE|FAILED",
  "workflow_type":   "standard",
  "requester_id":    "string",
  "requester_type":  "telegram",
  "current_step_id": "string or null",
  "result":          "string or null — final output when status=DONE",
  "created_at":      "ISO 8601",
  "updated_at":      "ISO 8601",
  "completed_at":    "ISO 8601 or null",
  "steps": [
    {
      "step_id":       "stp_xyz789",
      "step_number":   1,
      "role":          "CEO",
      "agent_id":      "agt_ceo_001 or null",
      "status":        "DONE",
      "prompt":        "string — what this agent was asked to do",
      "result":        "string or null",
      "artifacts":     ["path/to/file1.md"],
      "blocked_reason": null,
      "assigned_at":   "ISO 8601 or null",
      "started_at":    "ISO 8601 or null",
      "completed_at":  "ISO 8601 or null"
    }
  ]
}
```

**Response 404 Not Found:**
```json
{"error": "task_not_found", "task_id": "tsk_abc123"}
```

---

### POST /tasks/{task_id}/report

An agent reports step completion, blockage, or failure.
This is the **critical handoff endpoint** — the Orchestrator transitions state and assigns the next step upon receiving this call.

**Path parameter:** `task_id`

**Request body:**
```json
{
  "agent_id":       "string (required) — reporting agent's registered ID",
  "step_id":        "string (required) — the step being reported on",
  "status":         "string (required) — enum: COMPLETE | BLOCKED | FAILED",
  "result":         "string (optional) — human-readable output or summary",
  "artifacts":      ["string"] (optional) — list of file paths produced,
  "blocked_reason": "string (required if status=BLOCKED) — enum: token_limit | missing_skill | external_dependency | human_required",
  "error_detail":   "string (optional, used if status=FAILED) — error message"
}
```

**Response 200 OK (status=COMPLETE, more steps remain):**
```json
{
  "task_id":        "tsk_abc123",
  "step_reported":  "stp_xyz789",
  "task_status":    "AWAITING_HANDOFF",
  "next_step":      {
    "step_id":      "stp_next001",
    "role":         "Architect",
    "agent_id":     "agt_arch_001"
  }
}
```

**Response 200 OK (status=COMPLETE, no more steps):**
```json
{
  "task_id":      "tsk_abc123",
  "step_reported": "stp_xyz789",
  "task_status":  "DONE",
  "next_step":    null
}
```

**Response 200 OK (status=BLOCKED):**
```json
{
  "task_id":        "tsk_abc123",
  "step_reported":  "stp_xyz789",
  "task_status":    "BLOCKED",
  "retry_after":    3600,
  "message":        "Task paused. Retry scheduled in 3600s."
}
```

**Response 200 OK (status=FAILED):**
```json
{
  "task_id":      "tsk_abc123",
  "step_reported": "stp_xyz789",
  "task_status":  "FAILED",
  "message":      "Task marked FAILED. Requester notified."
}
```

**Response 409 Conflict** (step not in IN_PROGRESS state):
```json
{"error": "invalid_step_state", "step_id": "stp_xyz789", "current_status": "PENDING"}
```

---

### GET /tasks/{task_id}/next

An agent polls for its next step assignment. Called by agents on startup or after completing a step to receive work.

**Path parameter:** `task_id`
**Query parameter:** `agent_id` (required)

**Response 200 OK (work available):**
```json
{
  "step_id":      "stp_xyz789",
  "task_id":      "tsk_abc123",
  "step_number":  2,
  "role":         "Architect",
  "prompt":       "string — the exact prompt the agent must work on",
  "context": {
    "session_file": "/workspace/strategy/progress/tsk_abc123_context.json",
    "prior_steps":  [
      {"step_number": 1, "role": "CEO", "result": "string — summary of step 1 result"}
    ]
  },
  "timeout_seconds": 5400,
  "assigned_at":  "ISO 8601"
}
```

**Response 204 No Content** — no pending step for this agent right now.

**Response 404 Not Found** — task not found or agent not registered.

---

### GET /agents

List all registered agents and their health status.

**Response 200 OK:**
```json
{
  "agents": [
    {
      "agent_id":       "agt_ceo_001",
      "role":           "CEO",
      "url":            "http://sanad_agent:9000",
      "status":         "ONLINE",
      "current_task_id": null,
      "version":        "1.2.0",
      "registered_at":  "ISO 8601",
      "last_seen":      "ISO 8601"
    }
  ],
  "total": 4,
  "online": 3,
  "busy": 1
}
```

---

### POST /agents/register

An agent calls this on startup to announce itself.

**Request body:**
```json
{
  "role":    "string (required) — enum: CEO | Architect | Dev | HR",
  "url":     "string (required) — base URL of the agent service (e.g. http://sanad_agent:9000)",
  "version": "string (optional) — image tag or git SHA"
}
```

**Response 201 Created:**
```json
{
  "agent_id":      "agt_ceo_001",
  "registered":    true,
  "registered_at": "ISO 8601"
}
```

**Response 200 OK** (agent already registered — updates last_seen and URL):
```json
{
  "agent_id":   "agt_ceo_001",
  "registered": true,
  "updated":    true
}
```

---

### GET /health

Orchestrator liveness check. No auth required.

**Response 200 OK:**
```json
{
  "status":        "ok",
  "uptime_seconds": 3661,
  "db":            "ok",
  "tasks_active":  2,
  "tasks_pending": 1,
  "agents_online": 3
}
```

**Response 503 Service Unavailable** (SQLite unreachable):
```json
{"status": "degraded", "db": "error", "error": "database connection failed"}
```

---

## 2. Task Data Model

Full SQLite schema for the Orchestrator (`orchestrator.db`).

```sql
-- ─────────────────────────────────────────────
-- tasks: one row per workflow initiated
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT PRIMARY KEY,          -- 'tsk_' + uuid4 hex
    prompt           TEXT NOT NULL,             -- original user request
    status           TEXT NOT NULL DEFAULT 'PENDING',
                                                -- PENDING|ASSIGNED|IN_PROGRESS|
                                                -- AWAITING_HANDOFF|BLOCKED|DONE|FAILED
    workflow_type    TEXT NOT NULL DEFAULT 'standard',
    requester_id     TEXT NOT NULL,             -- Telegram user ID or API caller
    requester_type   TEXT NOT NULL DEFAULT 'telegram',
                                                -- telegram|api|agent
    callback_url     TEXT,                      -- where to POST final result
    current_step_id  TEXT,                      -- FK to task_steps.id (active step)
    result           TEXT,                      -- final output when DONE
    blocked_reason   TEXT,                      -- if status=BLOCKED
    created_at       TEXT NOT NULL,             -- ISO 8601
    updated_at       TEXT NOT NULL,             -- ISO 8601, updated on every transition
    completed_at     TEXT,                      -- ISO 8601, set when DONE or FAILED
    metadata         TEXT                       -- JSON blob for extra fields
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_requester ON tasks(requester_id);

-- ─────────────────────────────────────────────
-- task_steps: one row per step in the workflow
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_steps (
    id               TEXT PRIMARY KEY,          -- 'stp_' + uuid4 hex
    task_id          TEXT NOT NULL,             -- FK → tasks.id
    step_number      INTEGER NOT NULL,          -- 1-based ordering within task
    role             TEXT NOT NULL,             -- CEO|Architect|Dev|HR
    agent_id         TEXT,                      -- FK → agents.id (null until assigned)
    status           TEXT NOT NULL DEFAULT 'PENDING',
                                                -- PENDING|ASSIGNED|IN_PROGRESS|
                                                -- AWAITING_HANDOFF|DONE|FAILED|BLOCKED
    prompt           TEXT NOT NULL,             -- instruction sent to the agent
    result           TEXT,                      -- agent's output on completion
    artifacts        TEXT,                      -- JSON array of file paths
    blocked_reason   TEXT,                      -- if status=BLOCKED
    error_detail     TEXT,                      -- if status=FAILED
    assigned_at      TEXT,                      -- ISO 8601
    started_at       TEXT,                      -- ISO 8601, when agent called GET /next
    completed_at     TEXT,                      -- ISO 8601, when POST /report received
    timeout_seconds  INTEGER NOT NULL DEFAULT 5400,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_steps_task ON task_steps(task_id);
CREATE INDEX IF NOT EXISTS idx_steps_status ON task_steps(status);
CREATE INDEX IF NOT EXISTS idx_steps_agent ON task_steps(agent_id);

-- ─────────────────────────────────────────────
-- agents: registered agent instances
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id               TEXT PRIMARY KEY,          -- 'agt_' + role_lower + '_' + 3-digit seq
    role             TEXT NOT NULL,             -- CEO|Architect|Dev|HR
    url              TEXT NOT NULL,             -- http://host:port base URL
    status           TEXT NOT NULL DEFAULT 'OFFLINE',
                                                -- ONLINE|OFFLINE|BUSY
    version          TEXT,                      -- Docker image tag or git SHA
    current_task_id  TEXT,                      -- FK → tasks.id (null when idle)
    registered_at    TEXT NOT NULL,             -- ISO 8601
    last_seen        TEXT NOT NULL,             -- ISO 8601, updated on heartbeat
    metadata         TEXT                       -- JSON blob (env vars, capabilities)
);

CREATE INDEX IF NOT EXISTS idx_agents_role ON agents(role);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

-- ─────────────────────────────────────────────
-- events: immutable audit log of all transitions
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT,                      -- FK → tasks.id (null for agent-only events)
    step_id          TEXT,                      -- FK → task_steps.id (null for task-level events)
    agent_id         TEXT,                      -- FK → agents.id (null for system events)
    event_type       TEXT NOT NULL,
                     -- TASK_CREATED | TASK_DONE | TASK_FAILED | TASK_BLOCKED
                     -- STEP_CREATED | STEP_ASSIGNED | STEP_STARTED
                     -- STEP_COMPLETE | STEP_FAILED | STEP_BLOCKED
                     -- AGENT_REGISTERED | AGENT_ONLINE | AGENT_OFFLINE
                     -- HANDOFF_INITIATED | HANDOFF_DELIVERED | CALLBACK_SENT
    from_status      TEXT,                      -- prior state
    to_status        TEXT,                      -- new state
    details          TEXT,                      -- JSON blob: {reason, result_preview, etc.}
    timestamp        TEXT NOT NULL              -- ISO 8601 with microseconds
);

CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
```

**Schema notes:**
- All timestamps are ISO 8601 strings stored as TEXT (SQLite has no native DATETIME type; TEXT sorts lexicographically which is correct for ISO 8601).
- The `events` table is append-only — no UPDATE, no DELETE. It is the authoritative audit trail.
- The `tasks.current_step_id` column is a denormalized pointer for fast "what's happening now" queries without a JOIN.
- `task_steps.artifacts` stores a JSON array: `["strategy/progress/tsk_abc123_design.md", ...]`.
- `agents.metadata` stores JSON with fields like `{"capabilities": ["code", "design"], "env": {"AGENT_ROLE": "Dev"}}`.

---

## 3. State Machine Diagram (ASCII)

### Task-Level State Machine

```
                         ┌─────────────────────────────────────────┐
                         │         TASK STATE MACHINE              │
                         └─────────────────────────────────────────┘

  [POST /tasks called]
          │
          ▼
    ┌─────────┐
    │ PENDING │  Task created. Steps defined. No agent assigned yet.
    └────┬────┘  Transition: Orchestrator selects agent for first step.
         │       Who: Orchestrator (internal scheduler loop)
         │
         ▼
    ┌──────────┐
    │ ASSIGNED │  First step assigned to agent. Agent notified via push
    └────┬─────┘  (POST /task on agent) or polled (GET /tasks/{id}/next).
         │        Transition: Agent calls GET /tasks/{id}/next.
         │        Who: Agent (on startup or after prior step completes)
         │
         ▼
    ┌─────────────┐
    │ IN_PROGRESS │  Agent has acknowledged step. Working.
    └──────┬──────┘  Transition: Agent POSTs /tasks/{id}/report.
           │         Who: Agent
           │
     ┌─────┴──────────────────────────────┐
     │                                    │
     ▼ report.status = COMPLETE           ▼ report.status = BLOCKED
  ┌──────────────────┐             ┌─────────┐
  │ AWAITING_HANDOFF │             │ BLOCKED │  Context saved, retry scheduled.
  └────────┬─────────┘             └────┬────┘  Who: Agent → Orchestrator
           │                            │       Retry: Orchestrator (after 60 min)
           │         report.status = FAILED     CEO notified if blocked > 2 hours.
           │                            │
           │         ┌──────────────────┘
           │         │
           ▼         ▼ report.status = FAILED
           │      ┌────────┐
           │      │ FAILED │  Terminal. Requester notified.
           │      └────────┘  Who: Agent → Orchestrator → Telegram callback
           │
     ┌─────┴──────────────────────────────┐
     │ More steps remain?                 │
     │                                    │
     ▼ YES                                ▼ NO
  Next step → PENDING               ┌──────┐
  (loop back to top)                │ DONE │  Terminal. Result delivered.
                                    └──────┘  Who: Orchestrator → callback_url
```

### Step-Level State Machine

```
  [Orchestrator creates step]
          │
          ▼
    ┌─────────┐
    │ PENDING │  Step defined, not yet assigned.
    └────┬────┘
         │  Orchestrator selects agent for this role
         ▼
    ┌──────────┐
    │ ASSIGNED │  Agent selected. POST /task sent to agent (or queued for poll).
    └────┬─────┘
         │  Agent calls GET /tasks/{id}/next
         ▼
    ┌─────────────┐
    │ IN_PROGRESS │  Agent working. Clock running against timeout_seconds.
    └──────┬──────┘
           │
     ┌─────┼───────────────────────────────┐
     │     │                               │
     │     ▼ COMPLETE                      │
     │  ┌──────────────────┐               │
     │  │ AWAITING_HANDOFF │               │
     │  └────────┬─────────┘               │
     │           │ Orchestrator             │
     │           │ assigns next step        │
     │           ▼                         │
     │        ┌──────┐                     │
     │        │ DONE │ (this step)          │
     │        └──────┘                     │
     │                                     │
     ▼ BLOCKED                   ▼ FAILED (or timeout)
  ┌─────────┐                 ┌────────┐
  │ BLOCKED │                 │ FAILED │
  └─────────┘                 └────────┘
```

### Valid Transitions Table

| From              | To                 | Trigger                          | Actor         |
|-------------------|--------------------|----------------------------------|---------------|
| PENDING           | ASSIGNED           | Orchestrator picks agent         | Orchestrator  |
| ASSIGNED          | IN_PROGRESS        | Agent calls GET /next            | Agent         |
| IN_PROGRESS       | AWAITING_HANDOFF   | Agent reports COMPLETE           | Agent         |
| IN_PROGRESS       | BLOCKED            | Agent reports BLOCKED            | Agent         |
| IN_PROGRESS       | FAILED             | Agent reports FAILED             | Agent         |
| IN_PROGRESS       | FAILED             | Timeout exceeded                 | Orchestrator  |
| AWAITING_HANDOFF  | PENDING (new step) | Orchestrator creates next step   | Orchestrator  |
| AWAITING_HANDOFF  | DONE               | No more steps                    | Orchestrator  |
| BLOCKED           | PENDING (new step) | Retry timer fires                | Orchestrator  |
| BLOCKED           | FAILED             | CEO marks unresolvable           | CEO Agent     |
| DONE              | —                  | Terminal state                   | —             |
| FAILED            | —                  | Terminal state                   | —             |

---

## 4. Handoff Protocol — Exact Sequence

This is the precise call flow when an agent completes its step and work must move to the next agent.

### Scenario: Architect finishes design → Dev receives implementation task

```
 Telegram         Orchestrator          Architect Agent       Dev Agent
    │                   │                     │                   │
    │  POST /tasks       │                     │                   │
    │  {prompt,          │                     │                   │
    │   requester_id}    │                     │                   │
    │──────────────────►│                     │                   │
    │  201 {task_id}     │                     │                   │
    │◄──────────────────│                     │                   │
    │                   │                     │                   │
    │          [Orchestrator creates steps:   │                   │
    │           step 1: CEO → step 2: Arch →  │                   │
    │           step 3: Dev; assigns step 1]  │                   │
    │                   │                     │                   │
    │                   │  POST /task         │                   │
    │                   │  {step_id, prompt}  │                   │
    │                   │────────────────────►│                   │
    │                   │  202 Accepted       │                   │
    │                   │◄────────────────────│                   │
    │                   │                     │                   │
    │                   │  .... (CEO step, then Architect step assigned) ....
    │                   │                     │                   │
    │          [Step 2 assigned to Architect]  │                   │
    │                   │  POST /task         │                   │
    │                   │  {step_id:stp_002,  │                   │
    │                   │   prompt: "Design   │                   │
    │                   │   the system..."}   │                   │
    │                   │────────────────────►│                   │
    │                   │  202 Accepted       │                   │
    │                   │◄────────────────────│                   │
    │                   │                     │                   │
    │                   │     [Architect works — calls SanadReasoningLayer]
    │                   │                     │                   │
    │                   │                     │                   │
── STEP 1: Agent reports completion ────────────────────────────────────────
    │                   │                     │                   │
    │                   │  POST               │                   │
    │                   │  /tasks/tsk_001/    │                   │
    │                   │  report             │                   │
    │                   │  {agent_id:         │                   │
    │                   │   "agt_arch_001",   │                   │
    │                   │   step_id: stp_002, │                   │
    │                   │   status: COMPLETE, │                   │
    │                   │   result: "...",    │                   │
    │                   │   artifacts:        │                   │
    │                   │   ["design.md"]}    │                   │
    │                   │◄────────────────────│                   │
    │                   │                     │                   │
── STEP 2: Orchestrator persists transition ─────────────────────────────────
    │                   │                     │                   │
    │          [SQLite writes (within same DB transaction):
    │           UPDATE task_steps SET status='DONE',
    │                  result=..., completed_at=now WHERE id='stp_002'
    │           INSERT INTO events (STEP_COMPLETE, stp_002, agt_arch_001)
    │           UPDATE tasks SET status='AWAITING_HANDOFF', updated_at=now
    │           INSERT INTO events (TASK_AWAITING_HANDOFF, tsk_001)]
    │                   │                     │                   │
── STEP 3: Orchestrator determines next step ────────────────────────────────
    │                   │                     │                   │
    │          [SELECT next step for task tsk_001 WHERE step_number > 2
    │           AND status = 'PENDING' ORDER BY step_number LIMIT 1
    │           → stp_003, role='Dev']
    │                   │                     │                   │
    │          [SELECT agent for role='Dev' WHERE status='ONLINE'
    │           ORDER BY last_seen DESC LIMIT 1
    │           → agt_dev_001]
    │                   │                     │                   │
    │          [UPDATE task_steps SET status='ASSIGNED',
    │                  agent_id='agt_dev_001', assigned_at=now
    │           UPDATE agents SET status='BUSY', current_task_id='tsk_001'
    │           UPDATE tasks SET current_step_id='stp_003',
    │                  status='ASSIGNED', updated_at=now
    │           INSERT INTO events (STEP_ASSIGNED, stp_003, agt_dev_001)
    │           INSERT INTO events (HANDOFF_INITIATED, tsk_001)]
    │                   │                     │                   │
── STEP 4: Orchestrator responds to Architect ───────────────────────────────
    │                   │                     │                   │
    │                   │  200 {task_id,      │                   │
    │                   │  task_status:       │                   │
    │                   │  AWAITING_HANDOFF,  │                   │
    │                   │  next_step: {       │                   │
    │                   │   step_id: stp_003, │                   │
    │                   │   role: Dev,        │                   │
    │                   │   agent_id:         │                   │
    │                   │   agt_dev_001}}     │                   │
    │                   │────────────────────►│                   │
    │                   │                     │  (Architect done) │
    │                   │                     │                   │
── STEP 5: Orchestrator pushes assignment to Dev ────────────────────────────
    │                   │                     │                   │
    │                   │  POST /task         │                   │
    │                   │  {step_id: stp_003, │                   │
    │                   │   task_id: tsk_001, │                   │
    │                   │   prompt: "Impl...",│                   │
    │                   │   context: {        │                   │
    │                   │    session_file:    │                   │
    │                   │    "...ctx.json",   │                   │
    │                   │    prior_steps: [   │                   │
    │                   │     {step:2,result} │                   │
    │                   │    ]}}              │                   │
    │                   │───────────────────────────────────────►│
    │                   │  202 Accepted       │                   │
    │                   │◄───────────────────────────────────────│
    │                   │                     │                   │
    │          [SQLite: UPDATE task_steps SET status='IN_PROGRESS',
    │                   started_at=now WHERE id='stp_003'
    │           INSERT events (STEP_STARTED, stp_003, agt_dev_001)
    │           INSERT events (HANDOFF_DELIVERED, tsk_001)]
    │                   │                     │                   │
    │                   │  ... Dev works ...  │                   │
    │                   │                     │                   │
── FINAL STEP: Dev is the last step — task completion ───────────────────────
    │                   │                     │                   │
    │                   │  POST               │                   │
    │                   │  /tasks/tsk_001/    │                   │
    │                   │  report             │                   │
    │                   │  {status: COMPLETE, │                   │
    │                   │   result: "PR #42   │                   │
    │                   │   opened"}          │                   │
    │                   │◄───────────────────────────────────────│
    │                   │                     │                   │
    │          [No more steps. UPDATE tasks SET status='DONE',
    │           result=..., completed_at=now
    │           INSERT events (TASK_DONE)]
    │                   │                     │                   │
── FINAL: Orchestrator delivers result to original requester ────────────────
    │                   │                     │                   │
    │  POST callback_url│                     │                   │
    │  {task_id,        │                     │                   │
    │   status: DONE,   │                     │                   │
    │   result: "PR #42 │                     │                   │
    │   opened",        │                     │                   │
    │   artifacts: [...]}                     │                   │
    │◄──────────────────│                     │                   │
    │  (Telegram bot    │                     │                   │
    │   sends to user)  │                     │                   │
    │                   │                     │                   │
```

### Agent Push vs. Agent Poll

The Orchestrator uses **push-first, poll-fallback**:

1. **Push (primary):** When the next agent is known, the Orchestrator immediately POSTs to the agent's `/task` endpoint with the step assignment. The agent begins work without polling.
2. **Poll (fallback):** If the push POST fails (agent temporarily unreachable), the Orchestrator logs a `HANDOFF_PUSH_FAILED` event and marks the step ASSIGNED. The agent's startup hook calls `GET /tasks/{id}/next` and picks up pending work.
3. **Timeout guard:** If a step remains IN_PROGRESS beyond `timeout_seconds`, the Orchestrator fires a `STEP_TIMEOUT` event, marks the step FAILED, and creates a retry step.

---

## 5. HR Agent — API Spec

**Service:** `hr_agent` — FastAPI on port **8200**, Docker socket mounted at `/var/run/docker.sock`
**Base URL:** `http://hr_agent:8200`
**Auth:** `X-API-Key` header

The HR Agent has full Docker access on the host. It is the only service with Docker socket access.

---

### POST /agents/recruit

Provision a new agent: clone its DNA repo, build its Docker image, start a container, health-check it, and register it with the Orchestrator.

**Request body:**
```json
{
  "repo_url":        "string (required) — GitHub HTTPS URL of the agent repo",
  "role":            "string (required) — enum: CEO | Architect | Dev | custom",
  "tag":             "string (optional, default: latest) — Docker image tag",
  "port":            "integer (optional) — host port to expose (auto-assigned if omitted)",
  "env_overrides":   "object (optional) — key-value pairs to add/override in container env"
}
```

**Internal execution sequence:**
```bash
# 1. Clone the agent DNA repo
git clone {repo_url} /tmp/agents/{role}_{tag}_{timestamp}

# 2. Build Docker image
docker build \
  -t sanad_{role_lower}:{tag} \
  /tmp/agents/{role}_{tag}_{timestamp}

# 3. Start container
docker run -d \
  --name sanad_{role_lower}_{seq} \
  --network sanad_network \
  -p {port}:{internal_port} \
  -e AGENT_ROLE={role} \
  -e ORCHESTRATOR_URL=http://task_orchestrator:8100 \
  -e AGENTS_API_KEY={api_key} \
  {env_overrides as -e KEY=VALUE ...} \
  sanad_{role_lower}:{tag}

# 4. Health check (retry up to 12× every 5s = 60s total)
curl --fail http://localhost:{port}/health

# 5. Register with Orchestrator
POST http://task_orchestrator:8100/agents/register
  {role, url, version: tag}
```

**Response 201 Created (success):**
```json
{
  "agent_id":      "agt_dev_002",
  "role":          "Dev",
  "url":           "http://sanad_dev_002:9003",
  "container_id":  "d3f2a1b9...",
  "image_tag":     "sanad_dev:latest",
  "status":        "ONLINE",
  "registered_at": "ISO 8601"
}
```

**Response 422 Unprocessable Entity** (build failed):
```json
{
  "error":  "build_failed",
  "stage":  "docker_build",
  "detail": "Exit code 1: requirements.txt not found"
}
```

**Response 503 Service Unavailable** (health check timeout):
```json
{
  "error":         "health_check_failed",
  "container_id":  "d3f2a1b9...",
  "logs_tail":     "last 20 lines of docker logs"
}
```

---

### POST /agents/retire

Gracefully stop and deregister an agent. Uses blue/green: only stop old container after confirming no active steps.

**Request body:**
```json
{
  "agent_id":    "string (required) — the agt_* ID to retire",
  "force":       "boolean (optional, default: false) — skip graceful drain if true",
  "drain_timeout": "integer (optional, default: 300) — seconds to wait for active steps to finish"
}
```

**Internal execution sequence:**
```bash
# 1. Check for active steps
GET http://task_orchestrator:8100/agents  # verify agent has no IN_PROGRESS steps
# If agent is BUSY and force=false: return 409 with active step info

# 2. Deregister from Orchestrator (marks OFFLINE, won't receive new work)
PATCH http://task_orchestrator:8100/agents/{agent_id}/status
  {"status": "OFFLINE"}

# 3. Drain: wait up to drain_timeout for any in-flight step to complete

# 4. Stop container (graceful SIGTERM, 30s, then SIGKILL)
docker stop --time 30 {container_name}

# 5. Remove container
docker rm {container_name}
```

**Response 200 OK:**
```json
{
  "agent_id":    "agt_dev_002",
  "retired":     true,
  "container_id": "d3f2a1b9...",
  "retired_at":  "ISO 8601"
}
```

**Response 409 Conflict** (agent is busy, force=false):
```json
{
  "error":          "agent_busy",
  "agent_id":       "agt_dev_002",
  "active_step_id": "stp_009",
  "task_id":        "tsk_005",
  "message":        "Use force=true to retire immediately or wait for step completion."
}
```

---

### GET /agents

List all running agent containers managed by this HR service.

**Response 200 OK:**
```json
{
  "agents": [
    {
      "agent_id":       "agt_dev_001",
      "role":           "Dev",
      "container_name": "sanad_dev_001",
      "container_id":   "d3f2a1b9...",
      "image":          "sanad_dev:latest",
      "url":            "http://sanad_dev_001:9002",
      "status":         "ONLINE",
      "uptime_seconds": 7200,
      "registered":     true
    }
  ],
  "total": 4
}
```

---

## 6. Context Persistence Schema

### AgentSession Data Structure

Modeled on `clawd-code/src/agent/session.py` (verified in Phase 0), extended for multi-agent handoff.

```python
@dataclass
class AgentSession:
    # Identity
    session_id:    str    # "{task_id}__{step_id}__{YYYYMMDD_HHMMSS}"
    task_id:       str    # tsk_* — links back to Orchestrator
    step_id:       str    # stp_* — links back to specific step
    agent_role:    str    # CEO | Architect | Dev | HR

    # LLM state
    provider:      str    # active provider at time of save (e.g. "githubgpt4o")
    model:         str    # model name used
    messages:      list[dict]  # full conversation history in Anthropic API format
                               # [{"role": "user"|"assistant", "content": "..." or [blocks]}]
    token_count:   int    # cumulative tokens used this session

    # Task state
    checkpoint:    dict   # {
                          #   "step_description": str,
                          #   "work_done": str,    # what was accomplished before save
                          #   "next_action": str,  # what to do on resume
                          #   "artifacts": [str],  # file paths already produced
                          #   "notes": str         # any relevant context
                          # }

    # Session lifecycle
    saved_at:      str    # ISO 8601 with microseconds
    save_reason:   str    # enum: "periodic" | "blocked" | "complete" | "token_limit"
    resume_hint:   str    # one-sentence prompt to prepend on resume
                          # e.g. "You were designing the API spec. You completed
                          #       sections 1-3. Continue with section 4."
```

### File Path Pattern

```
/workspace/strategy/progress/{task_id}_context.json
```

Single file per task. Each save **overwrites** the previous (last-checkpoint-wins). The `events` table in SQLite is the audit trail for how many saves occurred.

Example: `/workspace/strategy/progress/tsk_abc123_context.json`

### Save Trigger Rules

| Trigger | Condition | save_reason |
|---------|-----------|-------------|
| Periodic | Every 15 minutes of active work | `"periodic"` |
| Token limit | Token count exceeds per-session threshold from `.env` | `"token_limit"` |
| BLOCKED report | Agent POSTs BLOCKED to Orchestrator | `"blocked"` |
| COMPLETE report | Agent POSTs COMPLETE to Orchestrator | `"complete"` |
| Graceful shutdown | SIGTERM received by container | `"shutdown"` |

### Resume Protocol

When an agent is restarted and finds a context file for its current step:

1. Load `/workspace/strategy/progress/{task_id}_context.json`
2. Validate: `step_id` matches current assignment
3. Prepend `resume_hint` as a system message to the conversation
4. Restore `messages` list (conversation history)
5. Resume from `checkpoint.next_action`

Resume prompt template injected as first user message:
```
[RESUMING SESSION]
Prior work: {checkpoint.work_done}
Next action: {checkpoint.next_action}
Artifacts already produced: {checkpoint.artifacts}
Note: {checkpoint.notes}
```

### Context Compaction

If `len(messages)` exceeds 80 turns or estimated token count > 60,000 tokens:
- Apply `microcompact_messages()` pattern from `clawd-code/src/context_system/microcompact.py`:
  clear tool results beyond last 3, strip images/documents
- If still over threshold: call SanadReasoningLayer to produce a summary, replace messages[:-10] with a single summary message
- Record tokens saved in `checkpoint.notes`

---

## 7. sanad_agent Changes Required (Phase 3 Scope)

These are the exact file changes needed to retrofit `projects/sanad_agent/` for Orchestrator integration. No new files are created outside the existing module structure.

---

### `main.py` — Add startup registration and health endpoint

**What to add:**
- Import and call `orchestrator_client.register()` inside `startup_event()`
- Add `GET /health` endpoint returning `{"status": "ok", "role": AGENT_ROLE, "uptime": N}`
- Add `POST /task` endpoint that accepts step assignments pushed by the Orchestrator

```python
# startup_event() — currently empty. Add:
async def startup_event():
    await on_start_service.run()           # was already planned, now implement
    await orchestrator_client.register()   # NEW: announce to Orchestrator

# New endpoints:
GET  /health  → {"status": "ok", "role": str, "uptime_seconds": int}
POST /task    → accepts OrchestratorAssignment, queues for processing, returns 202
```

---

### `services/on_start_service.py` — Implement registration logic

**Current state:** Empty file (1 line).

**What to add:** Read `ORCHESTRATOR_URL` from env. Call `POST /agents/register` with `{role, url, version}`. Log result. Retry up to 5× with 5s backoff if Orchestrator is not yet up (container race on startup).

---

### `controllers/chat_controller.py` — Remove fire-and-forget, add Orchestrator-aware endpoint

**Current broken pattern** (line 9-11): background task discards result.

**What to change:**
- Keep `POST /api/v1/chat` for backward compatibility with the Telegram bot entry point — but change it so the CEO agent creates a task in the Orchestrator and returns the `task_id`
- Add `POST /task` endpoint (called by Orchestrator for non-CEO agents) that is also background but reports result back via `orchestrator_client.report()`

---

### `services/chat_service.py` — Add report-back lifecycle

**Current broken pattern** (lines 13-19): result returned to nobody.

**What to change:**

```python
# New signature:
async def chat_with_agent(request, task_id: str, step_id: str):
    orchestration_payload = prompt_builder.build_prompt(request.prompt, provider)

    # Save context checkpoint before LLM call
    context_manager.save(task_id, step_id, messages=[], reason="periodic")

    response = think(reasoning_api_url, orchestration_payload)

    # Execute structured tool calls (NOT raw Python scripts)
    tool_result = tool_executor.execute(response.get("tool_calls", []))

    # Check execution result
    if tool_result.is_error:
        await orchestrator_client.report(task_id, step_id, status="FAILED",
                                         error_detail=tool_result.error)
        return

    # Save context after completion
    context_manager.save(task_id, step_id,
                         messages=[...], reason="complete",
                         work_done=..., next_action=None)

    # Report back — THIS IS THE FIX FOR THE BROKEN CHAIN
    await orchestrator_client.report(task_id, step_id, status="COMPLETE",
                                     result=tool_result.output,
                                     artifacts=tool_result.artifacts)
```

---

### `actions/agent/update_context.py` — Implement context save

**Current state:** Empty file.

**What to add:** Full implementation of `update_context(task_id, step_id, messages, checkpoint, reason)`:
- Serializes `AgentSession` to JSON
- Writes to `/workspace/strategy/progress/{task_id}_context.json`
- Logs save event

---

### `actions/agent/send_message.py` — Retire direct agent-to-agent calls

**Current pattern:** Direct HTTP POST to another agent's `/api/v1/chat`.

**What to change:** This function must no longer be called by agent code for workflow routing. It can be kept for CEO→Telegram notifications only (CEOs alerting the user). All workflow routing goes through `orchestrator_client.report()`.

The LLM prompt instructions in `memory/` files must be updated to remove `send_message` from the agent's tool list for workflow steps.

---

### `actions/agent/orchestrator_client.py` — New module

**This is the only new file.** Add to `actions/agent/`:

```python
# actions/agent/orchestrator_client.py
#
# Methods:
#   register()         — POST /agents/register on startup
#   report(task_id, step_id, status, result, artifacts, blocked_reason, error_detail)
#                      — POST /tasks/{task_id}/report
#   get_next(task_id)  — GET /tasks/{task_id}/next?agent_id={id}
#   heartbeat()        — POST /agents/{id}/heartbeat (called every 30s by background task)
#
# Config from env:
#   ORCHESTRATOR_URL   — base URL of Orchestrator
#   ORCHESTRATOR_API_KEY — auth key
#   AGENT_ID           — set after successful register()
```

---

### `memory/public/agent_project/workflow.md` — Update tool list and routing rules

**What to change:**
- Remove `send_message` from the tool list for all non-CEO workflow steps
- Add `report_complete(result, artifacts)` as the approved handoff action
- Add `report_blocked(reason)` for token limit and missing-skill scenarios
- Update state machine documentation to match the new Orchestrator-owned flow

---

### `to_run.py` execution model — Deprecate in Phase 3

**Current model:** LLM returns raw Python code → written to `to_run.py` → `exec`-ed via subprocess.

**Target model:** LLM returns structured JSON tool-call:
```json
{
  "thought": "I need to write a design document.",
  "tool_calls": [
    {
      "tool": "write_file",
      "args": {"path": "strategy/design.md", "content": "# Design\n..."}
    },
    {
      "tool": "report_complete",
      "args": {"result": "Design document written.", "artifacts": ["strategy/design.md"]}
    }
  ]
}
```

A `tool_executor.py` module validates tool names against an allowlist and executes them. This eliminates the code injection risk (GAP-11).

The `to_run.py` pattern is kept as fallback for Phase 3 only, with subprocess stderr checked and non-zero exit reported as FAILED to Orchestrator.

---

## 8. Key Design Decisions

These decisions address each question raised in `architecture_gaps.md`.

---

### Decision 1: Orchestrator Storage — SQLite (not Redis)

**Chosen:** SQLite, file at `orchestrator.db` in the Orchestrator container, mounted on host at `./data/orchestrator.db`.

**Why:**
- The system runs on a single VPS. Redis would add an external dependency (another container, another failure point) for no scaling benefit at this scale.
- SQLite provides ACID transactions — a single `BEGIN...COMMIT` block can atomically update `task_steps`, `tasks`, and `events` in the handoff path. This prevents partial state.
- SQLite is portable: `orchestrator.db` can be copied, inspected with any SQLite client, and restored from backup trivially.
- The `clawd-code` and `claude-code-typescript` reference codebases both use file-based persistence — consistent with the DNA of this project.

**What it rules out:** Horizontal scaling of the Orchestrator (two Orchestrator instances would need shared external state). This is acceptable — the Orchestrator is a single-node coordination service for a single-VPS deployment.

**Revisit trigger:** If task throughput exceeds 100 concurrent tasks or Orchestrator becomes a bottleneck in profiling.

---

### Decision 2: Agent Communication — All Routing Through Orchestrator (no agent-to-agent HTTP)

**Chosen:** Agents never call each other directly. All workflow transitions are reported to the Orchestrator, which pushes the next step to the next agent.

**Why:**
- The broken chain (GAP-01, GAP-02) is caused by direct `send_message()` calls that have no guaranteed delivery, no retry, and no result routing. Eliminating direct calls eliminates the root cause.
- The Orchestrator has full audit trail: every transition is persisted before any agent is notified. If an agent goes down between notification and acknowledgment, the ASSIGNED step is visible and will be retried.
- Workflow enforcement (GAP-09) is only possible if the Orchestrator is on every call path. An Architect cannot skip to CEO if the Orchestrator controls sequencing.

**What it rules out:** Sub-second agent-to-agent round-trips for fine-grained collaboration. If two agents need to collaborate interactively within a single step (e.g., pair-programming), they cannot do so in the current design. This is acceptable — each step is assigned to one agent; multi-agent collaboration within a step is deferred to a later phase.

**`send_message()` kept for one purpose:** CEO → Telegram user notifications. This is a human-alerting function, not workflow routing.

---

### Decision 3: to_run.py Execution Model — Replace With Structured Tool-Call JSON

**Chosen:** LLM returns `{"thought": str, "tool_calls": [{tool, args}]}`. A `tool_executor.py` validates against an allowlist and executes.

**Why:**
- The current model (write raw Python to disk, execute via `subprocess`) has a direct code injection risk (GAP-11). The LLM or reasoning API could return malicious code.
- Structured tool-calls are auditable: the `events` table can record exactly which tools were invoked with which arguments.
- Tool results are directly usable by the Orchestrator as `result` and `artifacts` without parsing subprocess output.
- This pattern is identical to how Claude Code itself works (claude-code-typescript reference) and how `clawd-code/src/tool_system/protocol.py` models tool use.

**Migration path for Phase 3:** The `to_run.py` path is kept as fallback behind a feature flag (`ENABLE_SCRIPT_FALLBACK=true`). The fallback checks returncode and captures stderr. Phase 3 ships the structured protocol; Phase 5 removes the fallback.

**What it rules out:** Ad-hoc Python scripting by agents in a single response. Agents can only use declared tools. New capabilities require adding a tool to the allowlist. This is a security/correctness tradeoff — the restriction is intentional.

---

### Decision 4: Context Save Location — `/workspace/strategy/progress/` (as masterplan specifies)

**Chosen:** Context files saved to `/workspace/strategy/progress/{task_id}_context.json`, which maps to `/home/ubuntu/DevAgent/strategy/progress/` on the host via the existing volume mount.

**Why:**
- The masterplan explicitly specifies this location. Changing it would require updating all documentation and potentially breaking CEO checkpoint scripts that scan this directory.
- The path is already bind-mounted into all agent containers via the existing Docker volume: `./:/sanad_agent` (for sanad_agent containers). The Orchestrator also has access to the DevAgent workspace via a separate mount.
- Keeping context on the host filesystem (not inside containers) means context survives container restarts and replacements — critical for the session resume protocol.

**What it rules out:** Multi-host deployment where agents run on separate machines. Context files would not be shared. This is acceptable for the current single-VPS architecture.

**One-file-per-task:** Each task has a single context file. Saves overwrite. The SQLite `events` table records how many saves occurred and when. If a full history of conversation turns is needed for debugging, the messages are in the latest save.

---

## System Integration Diagram (Target State)

```
                          ┌─────────────────────────────────────────┐
                          │           SANAD TARGET ARCHITECTURE      │
                          │              (Docker network: sanad_net) │
                          └─────────────────────────────────────────┘

  Human/Telegram
      │
      │ HTTPS webhook
      ▼
  ┌──────────────────┐
  │  Telegram Bot    │  (existing, /workspace/telegram/bot.py)
  │  :8000           │  
  └────────┬─────────┘
           │ POST /tasks {prompt, requester_id}
           │ Callback: POST /callback {task_id, result}
           ▼
  ┌──────────────────────────────────────────────────────────────┐
  │            Task Orchestrator :8100                            │
  │  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────┐  │
  │  │  FastAPI │  │  State     │  │  Agent   │  │ Callback │  │
  │  │  Routes  │  │  Machine   │  │ Selector │  │ Notifier │  │
  │  └──────────┘  └────────────┘  └──────────┘  └──────────┘  │
  │                      │                                        │
  │                 ┌────┴────┐                                   │
  │                 │ SQLite  │  orchestrator.db                  │
  │                 │ tasks   │                                   │
  │                 │ steps   │                                   │
  │                 │ agents  │                                   │
  │                 │ events  │                                   │
  │                 └─────────┘                                   │
  └───────┬──────────────────────────────────────────────────────┘
          │
          │ POST /task (push assignments)
          │ GET registration, health checks
          │
    ┌─────┼──────────────────────┬──────────────────────┐
    │     │                      │                      │
    ▼     ▼                      ▼                      ▼
  ┌──────────────┐   ┌──────────────────┐  ┌──────────────────┐
  │ sanad_agent  │   │  sanad_agent     │  │  sanad_agent     │
  │ CEO :9000    │   │  Architect :9001 │  │  Dev :9002       │
  │              │   │                  │  │                  │
  │ memory/CEO/  │   │ memory/Arch/     │  │ memory/Dev/      │
  └──────┬───────┘   └────────┬─────────┘  └────────┬─────────┘
         │                    │                      │
         └──────────┬─────────┘                      │
                    │ POST /api/v1/reasoning/generate │
                    ▼                                 │
          ┌─────────────────────┐                     │
          │ SanadReasoningLayer │◄────────────────────┘
          │ :5600               │
          │ LLM Router:         │
          │  1. Ollama/DS       │
          │  2. Free APIs       │
          │  3. Paid APIs       │
          └─────────────────────┘

          Context files:
          /workspace/strategy/progress/
          └── tsk_abc123_context.json
          └── tsk_xyz789_context.json

  ┌──────────────────────┐
  │ HR Agent :8200        │  (Phase 5)
  │ Docker socket mounted │
  │ Recruits/retires      │
  │ agent containers      │
  └──────────────────────┘
```

---

## Appendix: Agent /task Endpoint (Inbound from Orchestrator)

Each sanad_agent instance must expose this endpoint to receive push assignments.

### POST /task

Called by the Orchestrator to push a step assignment to an agent.

**Request body:**
```json
{
  "step_id":       "string (required)",
  "task_id":       "string (required)",
  "step_number":   "integer",
  "prompt":        "string (required) — the exact work instruction",
  "context": {
    "session_file":  "string or null — path to context JSON if resuming",
    "prior_steps":   [
      {"step_number": 1, "role": "CEO", "result": "string — summary"}
    ]
  },
  "timeout_seconds": "integer"
}
```

**Response 202 Accepted** (agent queued the work):
```json
{"step_id": "stp_xyz789", "accepted": true}
```

**Response 503 Service Unavailable** (agent busy or unhealthy):
```json
{"error": "agent_unavailable", "reason": "currently processing another step"}
```
