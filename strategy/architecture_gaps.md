# Architecture: Gaps vs. Masterplan
**Produced by:** Architect — Phase 0 Discovery (all file:line refs verified)
**Date:** 2026-04-16
**Reference:** `strategy/sanad_masterplan.md`
**Companion:** `strategy/architecture_current_state.md`

---

## Priority Scale

| Level | Label | Meaning |
|-------|-------|---------|
| P0 | **CRITICAL** | System cannot function without this — blocks everything |
| P1 | **HIGH** | Core masterplan feature — must be built in phases 2-5 |
| P2 | **MEDIUM** | Required for reliability and observability |
| P3 | **LOW** | Improvement; can be deferred to phase 6+ |

---

## P0 — CRITICAL: The Broken Chain

### GAP-01: No Task Orchestrator

**Masterplan reference:** Section "System Components / 1. Task Orchestrator"

**What's missing:** No central component owns workflow state. No entity knows "task T is at step 2 of 4, waiting on Dev agent, assigned at T+05:00".

**Current state:**
- `controllers/chat_controller.py:24` — returns `202` before work begins
- `services/chat_service.py:19` — `return cmd_result` returns to background task that discards it
- `memory/public/agent_project/workflow.md` — defines 6-state lifecycle in text, but **zero code enforces it**

**Severity:** Blocking — without this, no reliable multi-step workflow can complete.

**Estimated complexity:** High (new service). Needs: SQLite schema, state machine, FastAPI endpoints, assignment logic.

**What Phase 2 must build:**
- New FastAPI service (separate repo/container)
- `POST /tasks` — create workflow with steps
- `POST /tasks/{id}/report` — agent reports START/PROGRESS/COMPLETE/BLOCKED/FAILED
- `GET /tasks/{id}` — status query
- SQLite persistence: task graph, step states, agent assignments, timestamps
- State machine: `PENDING → ASSIGNED → IN_PROGRESS → AWAITING_HANDOFF → DONE | FAILED | BLOCKED`
- On COMPLETE: auto-assign next step from workflow definition, call next agent

---

### GAP-02: No Handoff Protocol

**Masterplan reference:** Section "System Components / 2. sanad_agent (EXTEND existing)"

**What's missing:** When an agent finishes work, no contract exists for what to do next. `send_message()` is a bare fire-and-forget HTTP call — success is assumed, errors are swallowed, and the calling agent moves on.

**Current state:**
- `actions/agent/send_message.py:6-9` — HTTP POST with no error handling, no retry, no ACK
- Generated `to_run.py` is executed without checking returncode
- `execute_command()` returns `{stdout, stderr, returncode}` but `chat_service.py:18` ignores it

**Severity:** Blocking — even if the Orchestrator exists, agents must report back to it.

**Estimated complexity:** Medium. Needs: Orchestrator client module in sanad_agent; replace `send_message()` pattern with `report_to_orchestrator()`.

**What Phase 3 must build:**
- Add `POST /orchestrator/tasks/{id}/report` endpoint to Orchestrator
- Payload: `{task_id, step, status, result, artifacts, agent_role, timestamp}`
- Agents call this on complete, blocked, or failed — **not** each other directly
- Orchestrator decides what happens next (assigns next step)
- Remove direct agent-to-agent HTTP communication

---

### GAP-03: No Result Delivery

**Masterplan reference:** Section "Vision — Receives work, executes autonomously"

**What's missing:** The original requester (Telegram user / API caller) never receives workflow output.

**Current state:**
- `controllers/chat_controller.py:23-24` — response is `{"message": "Chat processing started..."}` — always
- Background task output visible only in container stdout
- No callback URL, no polling endpoint, no webhook, no Telegram reply after completion

**Severity:** Blocking — users cannot see results.

**Estimated complexity:** Low-Medium. Orchestrator needs a `notify_requester()` step as the terminal workflow step. The existing Telegram bot infrastructure can receive the callback.

---

## P1 — HIGH: Core Masterplan Features

### GAP-04: No Token Tracking or Provider Failover

**Masterplan reference:** Section "Multi-LLM Strategy" + "Token Management & Work Session Protocol"

**What's missing:** 8 providers configured but `githubgpt4o` is always used. No token counting, no rate-limit detection, no switching logic.

**Current state (verified):**
- `adapters/llm_adapter_abstraction.py:35` — `return "githubgpt4o"` hardcoded
- `adapters/llm_adapter_abstraction.py:36` — `return random.choice(self.providers)` is **dead code** (unreachable line)
- `adapters/llm_adapter_abstraction.py:67` — `_select_provider()` call is commented out
- `dto/provider_dto.py` — `Provider` dataclass has `max_retries`, `enabled` fields but is **never instantiated**
- No token counter in any file across both repos

**3 broken providers (verified):**
- `openAI_llm_adapter.py:12` — calls `client.responses.create()` — invalid OpenAI Python SDK method
- `azure_llm_adapter.py:12` — same invalid call, model=`gpt-5` (nonexistent)
- `anthropic_llm_adapter.py:9` — `return f"[anthropic] {prompt}"` — stub, no API call

**Severity:** High — at GitHub Models rate limits (~50k tokens/day free), the system will silently fail.

**Estimated complexity:** High. Needs: per-provider token counter (in-memory + disk), 429 detection, priority routing logic, Ollama adapter.

**What Phase 4 must build:**
- Per-provider token counter (hourly window, persisted to disk)
- `429 / Retry-After` detection in all adapters
- Priority routing: Ollama → deepseek → openrouter → githubgpt4o → paid
- Auto-switch: on limit or error, pick next in priority list
- Fix the 3 broken adapters
- New `ollama_llm_adapter.py` (HTTP to `localhost:11434`)
- `GET /providers/health` endpoint for Orchestrator monitoring

---

### GAP-05: No Context Persistence

**Masterplan reference:** Section "Token Management / Context Preservation"

**What's missing:** Every agent request is stateless. No conversation history is maintained. On token limit or restart, all in-progress state is lost.

**Current state:**
- `SanadReasoningLayer/services/reasoning_service.py:8-10` — single `prompt` in, single `content` out, fully stateless
- `sanad_agent/actions/agent/update_context.py` — **empty file**, 1 line, no implementation
- Memory files (`shortterm_memory.md`, `context_tracker.md`) are updated only if the LLM generates code to do so — not guaranteed

**Severity:** High — any multi-step task spanning more than one LLM call loses prior context.

**Estimated complexity:** Medium. clawd-code's `Session` + `Conversation` classes are directly portable.

**What Phase 4 must build (modeled on `clawd-code/src/agent/session.py`):**
```python
@dataclass
class AgentContext:
    session_id: str
    task_id: str
    agent_role: str
    messages: list[dict]        # full conversation history (Anthropic format)
    checkpoint: dict            # last known task state
    saved_at: str               # ISO timestamp
    token_count: int
```
- Pass full `messages[]` history to reasoning layer on each call (extend `ReasoningRequestDTO`)
- Save context every 15 min → `/workspace/strategy/progress/{task_id}_context.json`
- On BLOCKED (token limit): save + report BLOCKED to Orchestrator
- On resume: load session, prepend compact summary via `compact_conversation()`

---

### GAP-06: No HR Agent

**Masterplan reference:** Section "System Components / 4. HR Agent (NEW)"

**What's missing:** No service can provision new agents. `request_hiring()` raises `ValueError` if `HR_URL` is unset.

**Current state (verified):**
- `actions/agent/request_hiring.py:6-10` — raises `ValueError: 'HR_URL or RL_API_KEY is missing'`
- `HR_URL` is not set in `.env`, `.env.dev`, or `.env.example`
- No HR service defined in `docker-compose.yml`
- The endpoint it would call does not exist

**Severity:** High — the Agent DNA lifecycle model (clone → build → run → retire) cannot work without this.

**Estimated complexity:** High (new service). Needs: git clone, docker build, health-check, Orchestrator registration, blue/green deployment logic.

**What Phase 5 must build:**
- New FastAPI service (`hr_agent/`)
- `POST /agents/recruit` — `{repo_url, role, config}` → clone → build → start → health check → register
- `POST /agents/retire/{agent_id}` — graceful stop → deregister
- `GET /agents` — list active agents
- Blue/green: new container validated before old stopped

---

### GAP-07: No Ollama/Local Provider

**Masterplan reference:** Section "Multi-LLM Strategy / Routing priority"

**What's missing:** Ollama (self-hosted, zero cost) is the highest-priority provider per the masterplan but no adapter exists.

**Current state:** Only 8 external-API adapters in `adapters/imp/`. No local inference adapter.

**Severity:** High — without Ollama, the system always hits rate-limited external APIs.

**Estimated complexity:** Low. Ollama exposes an OpenAI-compatible API.

**What Phase 4 must build:**
- `adapters/imp/ollama_llm_adapter.py` — HTTP to `http://localhost:11434/api/chat`
- Add to `.env`: `ollama_base_url=http://localhost:11434`, `ollama_model=deepseek-r1:7b`
- Insert `ollama` as first in priority chain

---

## P2 — MEDIUM: Reliability Gaps

### GAP-08: No Error Handling in Execution Chain

**What's missing:** Failures in LLM-generated code (`to_run.py`) are completely invisible.

**Evidence:**
- `chat_service.py:18` — calls `execute_command()`, result stored in `cmd_result` but never checked
- `execute_command.py:5` — returns `{stdout, stderr, returncode}`, caller ignores `returncode`
- If LLM generates Python with a syntax error, `returncode=1` and `stderr` has details — both discarded

**Fix needed:** Check `returncode != 0`, capture stderr, report FAILED to Orchestrator with error details.

---

### GAP-09: No Workflow Enforcement

**What's missing:** The documented chain (CEO→Architect→Dev→Architect→CEO) is convention only. Any agent can HTTP-POST to any other. No guard exists.

**Evidence:** `memory/public/agent_project/workflow.md` defines the chain in text, but no code enforces it. `send_message()` accepts any URL.

**Fix needed:** Orchestrator owns the step→role mapping. Agents can only call `report_to_orchestrator()`. Cross-role direct calls are eliminated.

---

### GAP-10: File-Based State Has No Locking

**What's missing:** Three agent containers write to the same memory markdown files (shared via volume mount) with no file locking.

**Evidence:** `prompt_builder.py:18-36` reads multiple files without any locking. Two concurrent agents could produce a torn write.

**Fix needed:** Move shared state to Orchestrator's SQLite (atomic writes) rather than shared files. Per-agent private memory stays file-based (only one writer per container).

---

### GAP-11: Code Injection Risk in to_run.py

**What's missing:** The reasoning layer's raw output is written to `to_run.py` and executed as Python code. No validation occurs.

**Evidence:** `chat_service.py:17-18`
```python
write_file("to_run.py", response.get("action", ""))
cmd_result = execute_command("python to_run.py")
```

If the LLM is prompted to generate malicious code (prompt injection via task content), it runs with full container permissions.

**Severity:** Security risk; medium priority for internal use, high for any external-facing deployment.

**Fix needed (preferred):** Replace script execution with structured tool-call protocol. LLM returns JSON `{"tool": "send_message", "args": {...}}` instead of raw Python. Agent validates against an allowlist before executing.

---

### GAP-12: No Observability

**What's missing:** Both services use `print()` only. No structured logging, no request tracing, no metrics.

**Evidence:** `generate_reasoning_controller.py:20-24` — `print(f"Received reasoning request: {request}")`.

**Minimum needed for Phase 2+:**
- Python `logging` module with JSON formatter
- `X-Request-ID` header propagated across agent hops
- Orchestrator event log: `{timestamp, task_id, agent, event, status, duration_ms}`

---

## P3 — LOW: Deferred Improvements

### GAP-13: Three Broken Provider Adapters

`openai`, `azure` use `client.responses.create()` (invalid SDK method). `anthropic` is a stub. Not critical (githubgpt4o works) but must be fixed before multi-provider routing is meaningful.

**Fix:** `openai`/`azure` → use `client.chat.completions.create()`. `anthropic` → use Anthropic SDK `client.messages.create()`.

---

### GAP-14: Sync SDK Calls in Async Context

Most drivers declare `async def send_message()` but call synchronous SDK methods internally (blocking the event loop under concurrent requests).

**Evidence:** `openRouter_llm_adapter.py:13-22` — `client.chat.completions.create()` (sync) inside `async def`.

**Fix:** Use `asyncio.run_in_executor(None, sync_fn)` or switch to async SDK variants where available.

---

### GAP-15: No .env.example in SanadReasoningLayer

The `.env` file contains real credentials and is not in `.gitignore` properly. No `.env.example` exists for reference. The HR Agent cannot clone and configure the repo without a template.

---

### GAP-16: No Health Endpoints

Neither service has a `GET /health` endpoint. The Orchestrator cannot check if an agent is alive before assigning a task.

**Minimum:** `GET /health` → `{"status": "ok", "role": "architect", "uptime_seconds": N}`

---

## Summary: Gap → Phase Mapping

```
Phase 2 — Task Orchestrator (fixes the broken chain):
  GAP-01  Task Orchestrator service           P0 CRITICAL
  GAP-03  Result delivery                     P0 CRITICAL
  GAP-09  Workflow enforcement                P2 MEDIUM
  GAP-16  Health endpoints (agents)           P3 LOW

Phase 3 — Fix sanad_agent:
  GAP-02  Handoff protocol                    P0 CRITICAL
  GAP-08  Error handling in execution         P2 MEDIUM
  GAP-10  Remove shared file state            P2 MEDIUM

Phase 4 — Multi-LLM Hardening:
  GAP-04  Token tracking + provider failover  P1 HIGH
  GAP-05  Context persistence                 P1 HIGH
  GAP-07  Ollama adapter                      P1 HIGH
  GAP-14  Async/await fix in adapters         P3 LOW

Phase 5 — HR Agent:
  GAP-06  HR Agent service                    P1 HIGH
  GAP-11  to_run.py code injection fix        P2 MEDIUM

Phase 6 — Cleanup:
  GAP-13  Fix broken adapters (openai, azure, anthropic)  P3 LOW
  GAP-12  Structured logging                              P2 MEDIUM
  GAP-15  .env.example for SanadReasoningLayer            P3 LOW
```

---

## Architectural Decision Points for Phase 1

These must be confirmed before coding starts (masterplan section "CEO Checkpoint CP-1"):

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| D1 | Orchestrator storage | SQLite vs Redis | SQLite — simpler, no extra service, ACID |
| D2 | Agent communication | Direct agent-to-agent HTTP vs all-through-Orchestrator | All-through-Orchestrator — prevents broken chains, enables audit trail |
| D3 | LLM output format | Keep Python script execution vs structured tool-call JSON | Structured JSON — eliminates code injection, auditable, testable |
| D4 | Context save location | `strategy/progress/` (masterplan) vs `contexts/` dir | Follow masterplan: `strategy/progress/{task_id}_context.json` |
| D5 | sanad_agent: extend vs rebuild | Extend existing vs new clean implementation | Extend — infrastructure is good, only execution chain needs fixing |

---

## What Is Working Well (keep as-is)

- Docker networking with named bridge network — correct topology for agent communication
- API key auth pattern — consistent across both services
- Memory file system — good for per-agent identity; keep for static config, replace dynamic state with SQLite
- SanadReasoningLayer abstraction layer — `BaseLLMDriver` + `LLMAdapter` is the right pattern; just fix routing
- Background task endpoint pattern — correct for long-running work; problem is result delivery not the async pattern itself
- Agent role differentiation via env var — clean; no need to change
