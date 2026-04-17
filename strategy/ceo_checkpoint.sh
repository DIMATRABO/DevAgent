#!/bin/bash
# CEO Checkpoint — runs every 3 hours via system cron
# Reads project progress and triggers next agents as needed

WORKSPACE="/workspace"
PROGRESS="$WORKSPACE/strategy/progress"
PROMPTS="$WORKSPACE/strategy/prompts"
LOG="$PROGRESS/ceo_checkpoint.log"

echo "=== CEO CHECKPOINT $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"

# Build the checkpoint prompt dynamically from current state
PHASE0=$(cat "$PROGRESS/phase_0_status.md" 2>/dev/null || echo "status: NOT_STARTED")
PHASE1=$(cat "$PROGRESS/phase_1_status.md" 2>/dev/null || echo "status: NOT_STARTED")
PHASE2=$(cat "$PROGRESS/phase_2_status.md" 2>/dev/null || echo "status: NOT_STARTED")
PHASE3=$(cat "$PROGRESS/phase_3_status.md" 2>/dev/null || echo "status: NOT_STARTED")
BLOCKERS=$(cat "$PROGRESS/blockers.md" 2>/dev/null || echo "none")

CEO_PROMPT="You are the CEO orchestrator for the Sanad multi-agent project. This is an automated checkpoint.

Master plan: $WORKSPACE/strategy/sanad_masterplan.md

CURRENT STATE:
Phase 0 (Architect — Discovery): $PHASE0
Phase 1 (Architect — Design): $PHASE1
Phase 2 (Developer — Orchestrator): $PHASE2
Phase 3 (Developer — Fix sanad_agent): $PHASE3
Blockers: $BLOCKERS

YOUR JOB:
1. Evaluate progress
2. If a phase is COMPLETE and the next phase has no running agent, write the next phase prompt and launch it:
   nohup bash $WORKSPACE/strategy/run_phase.sh <profile> <N> $PROMPTS/phase_<N>_<profile>.txt > /dev/null 2>&1 &
3. If a phase is BLOCKED or PARTIAL and stale (no update in >2h), re-trigger it
4. Write checkpoint report to $PROGRESS/ceo_checkpoint_\$(date +%Y%m%d_%H).md
5. Update $PROGRESS/blockers.md if anything is stuck
6. If blocked >4h with no progress, contact user via Telegram:
   python3 -c \"
import requests, os
token = open('$WORKSPACE/.env').read()
import re
m = re.search(r'TELEGRAM_BOT_TOKEN=(.+)', token)
tok = m.group(1).strip() if m else ''
ids_m = re.search(r'ALLOWED_USER_IDS=(.+)', token)
uid = ids_m.group(1).strip().split(',')[0] if ids_m else ''
if tok and uid:
    requests.post(f'https://api.telegram.org/bot{tok}/sendMessage', json={'chat_id': uid, 'text': 'CEO ALERT: Sanad project blocked. Check /workspace/strategy/progress/blockers.md'})
\"

PHASE PROMPT TEMPLATES — write these files if the previous phase is COMPLETE:

Phase 1 prompt ($PROMPTS/phase_1_architect.txt): Design the full target architecture.
  Read the discovery docs from Phase 0:
  - $WORKSPACE/strategy/architecture_current_state.md
  - $WORKSPACE/strategy/architecture_gaps.md
  - $WORKSPACE/strategy/sanad_masterplan.md
  Design and write to $WORKSPACE/strategy/architecture_target.md:
  - Task Orchestrator: full API spec (endpoints, request/response schemas), data model, state machine diagram (ASCII)
  - Handoff Protocol: exact sequence of calls when an agent completes a task
  - HR Agent: API spec, Docker lifecycle operations
  - Context Persistence schema: what gets saved, format, recovery procedure
  - Update $PROGRESS/phase_1_status.md when done (status: COMPLETE)

Phase 2 prompt ($PROMPTS/phase_2_developer.txt): Build the Task Orchestrator.
  Read: $WORKSPACE/strategy/architecture_target.md
  Implement the Task Orchestrator in /workspace/projects/sanad_agent/orchestrator/:
  - FastAPI service with all endpoints from the spec
  - SQLite persistence for task state
  - Agent registry
  - Handoff endpoint
  - Dockerfile
  Tests: at minimum a test that proves two agents can complete a handoff without breaking the chain
  Update $PROGRESS/phase_2_status.md when done (status: COMPLETE)

Phase 3 prompt ($PROMPTS/phase_3_developer.txt): Retrofit sanad_agent to use Orchestrator.
  Read: $WORKSPACE/strategy/architecture_target.md and existing agent code
  Add Orchestrator client to sanad_agent:
  - Report START, PROGRESS, COMPLETE, BLOCKED to Orchestrator
  - Never exit silently — always call handoff endpoint
  - Test: two agents pass a task back and forth end-to-end
  Update $PROGRESS/phase_3_status.md when done (status: COMPLETE)

TOKEN BUDGET RULES (enforce strictly):
- If any phase log shows a session running >90 min: kill and re-launch with continuation context
- Add 60-min minimum gap between re-launching same phase
- Check: ps aux | grep claude — if multiple claude processes, something may be stuck
"

# Run CEO as claude subprocess
ARCHITECT_PROMPT=$(cat "$WORKSPACE/agents/ceo.md" 2>/dev/null || echo "")

claude -p "$CEO_PROMPT" \
  --dangerously-skip-permissions \
  --append-system-prompt "$ARCHITECT_PROMPT" \
  --allowed-tools "Read,Glob,Grep,Write,Bash" \
  >> "$LOG" 2>&1

echo "=== CHECKPOINT DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"
