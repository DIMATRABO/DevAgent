# Sanad — Company of AI Agents: Master Strategic Plan
**CEO: Claude Sonnet 4.6 | Date: 2026-04-16 | Branch: feat/cross-agent-workflow**

---

## Vision

Build a self-organizing company of AI agents that:
- Receives work from a human (via Telegram or API)
- Plans, decomposes, assigns, and executes tasks autonomously
- Manages its own lifecycle (recruit, train, retire agents via Git + Docker)
- Routes LLM calls intelligently across providers to avoid limits and minimize cost
- Recovers from interruptions without losing context
- Operates without constant human intervention

**North Star Metric:** Give a real software task to the agent company and have it fully completed — PRs open, tests passing, human not touched — within 24 hours.

---

## The Core Problem (from POC)

Agents lose the execution chain. When one agent finishes its task, it does not notify the next agent. The workflow dies silently.

**Root cause hypothesis:** No shared task state machine. Each agent only knows its own job, not the broader workflow.

**Solution direction:** Introduce a central Task Orchestrator that owns workflow state. Agents report to it, not to each other directly. The Orchestrator decides what happens next.

---

## System Components

### 1. Task Orchestrator (NEW — highest priority)
- Central brain: owns the task graph, tracks state of every step
- Every agent reports START, PROGRESS, COMPLETE, BLOCKED to it
- Assigns next steps when a task completes (fixes broken chain)
- Persists all state to disk — survives restarts and token limits
- API: FastAPI, accessible to all agents

### 2. sanad_agent (EXTEND existing)
- Individual agent workers: receive assignments, execute, report back
- Each agent type = a GitHub repo (DNA model)
- Instances = Docker containers
- Must implement the Orchestrator handoff protocol

### 3. SanadReasoningLayer (EXTEND existing)
- LLM router + load balancer
- Priority order: Ollama/Deepseek (free, self-hosted) → free APIs → paid APIs
- Token budget awareness: tracks usage per provider, switches on limit
- Context compression: saves/restores conversation context on token limit

### 4. HR Agent (NEW)
- Manages agent lifecycle: create instance, validate, retire
- Triggered by Orchestrator when a task requires a skill not available
- Pulls latest agent DNA from GitHub, builds Docker image, registers agent
- Stops/removes containers of retired agents

### 5. Telegram Gateway (EXISTING — keep as is)
- Human entry point
- Also used by CEO to send alerts to user when human intervention needed

---

## Agent DNA Model

```
GitHub Repo (Agent DNA)
       |
   git clone
       |
  Docker Build  ←── HR Agent manages this
       |
  Running Container (Agent Instance)
       |
  FastAPI endpoint (/task, /health, /status)
       |
  Reports to Task Orchestrator
```

When a skill upgrade is needed:
1. Developer profile works on agent repo
2. Tests pass, pushed to GitHub
3. HR Agent builds new image, runs it alongside old
4. Validation test: new agent passes task
5. HR Agent stops old container, registers new one
6. Other agents pull if they subscribe to that skill

---

## Multi-LLM Strategy

**Routing priority (cost-optimized):**
1. Ollama/Deepseek (same VPS — zero API cost, ~30 token/s)
2. Free-tier APIs (Groq, Together, Mistral — rate limited)
3. Paid APIs (Anthropic, OpenAI, Gemini — last resort)

**Token limit recovery:**
- SanadReasoningLayer tracks token usage per provider per hour
- When approaching limit: switch provider automatically
- If all providers at limit: pause task, save context, schedule wake-up in 60 min
- Context saved to disk as JSON: messages[], task_state, next_step

---

## Token Management & Work Session Protocol

**This is non-negotiable — protect API budgets.**

### Work Session Rules
| Rule | Value |
|------|-------|
| Max active session | 90 minutes |
| Mandatory break between sessions | 60 minutes |
| Context save frequency | Every 15 minutes |
| Max tokens per session (per agent) | Configured in .env |

### Context Preservation
- Before session end: agent saves full context to `/workspace/strategy/progress/<task_id>_context.json`
- On wake-up: agent reads context file, resumes from exact checkpoint
- Orchestrator never loses task state — persisted to SQLite or JSON file

### On Token Limit Hit
1. Agent detects limit (error from API or approaching threshold)
2. Saves context + current state immediately
3. Reports BLOCKED (reason: token_limit) to Orchestrator
4. Orchestrator schedules retry after 60 min
5. CEO notified via Telegram if blocked > 2 hours

---

## Phases & Work Assignments

### Phase 0 — Discovery (Architect) — SESSION 1
**Goal:** Understand what exists before designing anything new.

Tasks:
- Read `sanad_agent` full codebase — map all endpoints, data models, agent logic
- Read `SanadReasoningLayer` — map LLM routing logic, current providers, .env structure
- Scan `claude-code-typescript` and `clawd-code` — identify key patterns: task state machine, agent communication, context management
- Produce: `strategy/architecture_current_state.md` (what exists) + `strategy/architecture_gaps.md` (what's missing)

**Break:** 60 min after this session.

### Phase 1 — Architecture Design (Architect) — SESSION 2
**Goal:** Design the target system before any code is written.

Tasks:
- Design Task Orchestrator: API spec, data model, state machine
- Design Handoff Protocol: how agents communicate task completion
- Design HR Agent: lifecycle operations, GitHub integration
- Design Context Persistence schema
- Produce: `strategy/architecture_target.md` — full technical spec for Developer

**Break:** 60 min after this session.

### Phase 2 — Task Orchestrator (Developer) — SESSIONS 3-4
**Goal:** Build the core that fixes the broken chain.

Tasks:
- Implement Task Orchestrator as FastAPI service
- Task state machine: PENDING → ASSIGNED → IN_PROGRESS → AWAITING_HANDOFF → DONE/FAILED
- Persistent storage (SQLite): tasks, agents registry, workflow definitions
- Agent registration endpoint: agents announce themselves on startup
- Handoff endpoint: agents call this when done — Orchestrator assigns next step
- Docker containerize the Orchestrator

**Break:** 60 min between sessions 3 and 4.

### Phase 3 — Fix sanad_agent (Developer) — SESSION 5
**Goal:** Retrofit existing agents to use the new Orchestrator protocol.

Tasks:
- Add Orchestrator client to sanad_agent
- On task start: register + report START to Orchestrator
- On task complete: call handoff endpoint (not silent exit)
- On task blocked: report BLOCKED with reason
- Test: 2 agents passing a task back and forth until completion

### Phase 4 — Multi-LLM Hardening (Developer) — SESSION 6
**Goal:** Make SanadReasoningLayer robust against token limits.

Tasks:
- Add token usage tracking per provider
- Implement automatic provider switching logic
- Add Ollama/Deepseek as first-priority provider (configure endpoint)
- Implement context save/restore on limit hit
- Expose provider health endpoint for Orchestrator to monitor

### Phase 5 — HR Agent (Developer) — SESSIONS 7-8
**Goal:** Agents can recruit new skills autonomously.

Tasks:
- HR Agent: FastAPI service, Docker containerized
- Operations: `recruit(repo_url)`, `validate(agent_id)`, `retire(agent_id)`
- Git pull → Docker build → health check → register with Orchestrator
- Integration test: Orchestrator detects missing skill → requests HR → new agent online

**Break:** 60 min between sessions 7 and 8.

### Phase 6 — Integration & Demo (Architect + Developer) — SESSION 9
**Goal:** End-to-end proof. Give the agent company a real task, watch it complete.

Demo task: "Create a Python script that fetches weather data and saves it to CSV."
- Orchestrator receives task
- Assigns to available agent(s)
- Agents collaborate, no broken chains
- Task marked DONE, output available
- CEO reviews, contacts user with result

---

## CEO Checkpoint Schedule

| Checkpoint | When | Action |
|------------|------|--------|
| CP-0 | After Phase 0 | Read architecture docs, validate scope with user |
| CP-1 | After Phase 1 | Review architecture design, approve before coding starts |
| CP-2 | After Phase 2 | Orchestrator demo: does handoff work? |
| CP-3 | After Phase 3 | Two-agent task passing test |
| CP-4 | After Phase 4 | LLM switching test |
| CP-5 | After Phase 5 | HR recruit/retire test |
| CP-6 | After Phase 6 | Full demo — contact user on Telegram with result |

**Between checkpoints:** CEO reviews `strategy/progress/` files every 6 hours via scheduled wake-up.

---

## Contact User on Telegram When:
1. A phase is complete and needs validation
2. Any task is blocked > 2 hours
3. An architectural decision requires business input
4. A new credential or external access is needed
5. Phase 6 (final demo) is complete

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Token limits during long sessions | High | Medium | 90-min session cap + context save |
| sanad_agent too diverged to extend | Medium | High | Architect assesses in Phase 0 — rebuild if needed |
| Ollama slow for complex reasoning | Medium | Low | Fallback chain handles it |
| Docker networking between agents | Medium | Medium | Use shared Docker network + service discovery |
| HR Agent breaks running agents | Low | High | Blue/green deployment: new container validated before old stopped |

---

## Progress Tracking

All progress files go in `/workspace/strategy/progress/`.

File naming:
- `phase_<N>_status.md` — current status of each phase
- `<task_id>_context.json` — saved agent contexts
- `blockers.md` — active blockers needing CEO or human attention
- `decisions.md` — architectural decisions made and why

---

## First Action

**Architect profile** starts with Phase 0 — read all 4 repos, produce the two discovery documents before any code is written.

Command for Architect: `/profile architect` then read this file at `/workspace/strategy/sanad_masterplan.md`
