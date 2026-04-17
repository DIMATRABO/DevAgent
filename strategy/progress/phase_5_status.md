## Phase 5 — HR Agent

status: COMPLETE
updated_at: 2026-04-16T14:30:00Z

files_written:
  - hr_agent/__init__.py
  - hr_agent/main.py
  - hr_agent/config.py
  - hr_agent/models.py
  - hr_agent/docker_client.py
  - hr_agent/orchestrator_client.py
  - hr_agent/api/__init__.py
  - hr_agent/api/agents.py
  - hr_agent/tests/__init__.py
  - hr_agent/tests/test_hr_agent.py
  - hr_agent/requirements.txt
  - hr_agent/Dockerfile
  - hr_agent/docker-compose.yml

test_result: pass (5/5)

summary: |
  HR Agent implemented as a standalone FastAPI service on port 8200 with
  Docker socket access.  All four required endpoints are live:

    POST   /agents/recruit              — 5-step pipeline:
                                          git clone → docker build → docker run
                                          → health-check (12×5s) → POST /agents/register
                                          Returns 201 {agent_id, container_id, port, url, status:"healthy"}
                                          or 500 {error, failed_step, detail} on any failure.
                                          Failed health-check triggers full cleanup
                                          (stop + rm container, rm image) before 500.

    POST   /agents/validate/{agent_id}  — Single GET /health against the container URL;
                                          on success POSTs PATCH /agents/{id}/status ONLINE
                                          to Orchestrator.
                                          Returns {agent_id, healthy, latency_ms}.

    DELETE /agents/{agent_id}           — Blue/green retirement: queries Orchestrator
                                          for BUSY status before stopping.  docker stop
                                          (30s grace) → docker rm → PATCH status OFFLINE.
                                          Returns 204 on success, 409 if agent is BUSY.

    GET    /health                      — No auth.  Returns {"status":"ok","docker":"connected"}
                                          or {"docker":"disconnected"} if socket unreachable.

  Design notes:
  - All Docker SDK calls go through hr_agent/docker_client.py (no subprocess Docker ops).
  - git clone is the only subprocess operation (no Docker SDK equivalent).
  - Heavy blocking calls (build, run, stop, rm) are wrapped in asyncio.to_thread() in
    api/agents.py to avoid blocking the FastAPI event loop.
  - An in-memory dict _agent_registry maps agent_id → container metadata (port, url,
    container_id, container_name). Lost on restart; acceptable for current single-node
    deployment. Orchestrator is the authoritative agent registry.
  - Orchestrator registration failure at step 5 is non-fatal: agent is still started and
    a local agent_id is generated.
  - Auth: X-API-Key dependency on all routes except GET /health; reads AGENTS_API_KEY
    env var (same key used by Orchestrator).
  - Dockerfile builds from sanad_agent/ parent context (context: ..) so hr_agent package
    is importable as hr_agent.xxx — consistent with the orchestrator package pattern.

  Tests (all mocked, no live Docker or Orchestrator required):
    test_health_ok                    — GET /health 200 {status:ok, docker:connected}
    test_recruit_success              — happy path; verifies Orchestrator register called
    test_recruit_cleanup_on_failure   — health-check timeout triggers stop+rm+rmi and 500
    test_validate_healthy             — returns {healthy:true, latency_ms:42}; ONLINE confirmed
    test_retire_removes_container     — docker stop+rm called; Orchestrator OFFLINE called; 204

blocker: |
  none

next_phase: |
  Phase 6 — Integration & Demo: wire up the full stack (Orchestrator + sanad_agent ×3
  + HR Agent) with docker-compose, send a real task end-to-end, verify no broken chains,
  and report result via Telegram.
