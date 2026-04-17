# Architectural Decisions Log

_Last updated: 2026-04-16_

## DEC-001 — Central Task Orchestrator (not peer-to-peer)
**Decision:** Agents do not talk directly to each other. All task flow goes through a central Orchestrator.
**Why:** The POC broke because agents had no shared state. Peer-to-peer chains are fragile. Central orchestrator owns the state machine.
**Status:** Approved by CEO. Architect to validate technically in Phase 0.

## DEC-002 — LLM Priority: Ollama first
**Decision:** SanadReasoningLayer routes to Ollama/Deepseek first, free APIs second, paid last.
**Why:** Minimize cost, avoid token limits on paid providers. Deepseek is already running on the same VPS.
**Status:** Approved by CEO. Developer to implement in Phase 4.

## DEC-003 — Agent DNA = GitHub Repo
**Decision:** Each agent type maps to a GitHub repo. Updates go through git, not manual container changes.
**Why:** This is the user's existing mental model. Enables version control, rollback, and the HR agent lifecycle pattern.
**Status:** Approved. Kept as-is from user's original design.

## DEC-004 — 90-min session cap
**Decision:** No agent work session runs longer than 90 minutes. Context saved every 15 minutes.
**Why:** Avoid token limit hits mid-task with no recovery. User explicitly requested this.
**Status:** Non-negotiable. Must be enforced at the Orchestrator level.
