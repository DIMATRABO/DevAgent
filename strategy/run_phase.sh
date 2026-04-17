#!/bin/bash
# CEO Orchestrator — Phase runner
# Usage: ./run_phase.sh <profile> <phase_number> <prompt_file>
# Runs a Claude profile agent in the background, logs to strategy/progress/

PROFILE=$1
PHASE=$2
PROMPT_FILE=$3

PROFILE_PROMPT=$(cat /workspace/agents/${PROFILE}.md 2>/dev/null || echo "")
TASK_PROMPT=$(cat "$PROMPT_FILE")
LOG_FILE="/workspace/strategy/progress/phase_${PHASE}_output.log"
PID_FILE="/workspace/strategy/progress/phase_${PHASE}.pid"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting $PROFILE for Phase $PHASE" >> "$LOG_FILE"

# Build allowed-tools based on profile
if [ "$PROFILE" = "architect" ]; then
  TOOLS="Read,Glob,Grep,Write,Bash(git log:*),Bash(git diff:*),WebSearch"
elif [ "$PROFILE" = "developer" ]; then
  TOOLS=""  # all tools
elif [ "$PROFILE" = "reviewer" ]; then
  TOOLS="Read,Glob,Grep,Bash(gh:*),Bash(git:*)"
fi

if [ -n "$TOOLS" ]; then
  claude -p "$TASK_PROMPT" \
    --dangerously-skip-permissions \
    --append-system-prompt "$PROFILE_PROMPT" \
    --allowed-tools "$TOOLS" \
    >> "$LOG_FILE" 2>&1
else
  claude -p "$TASK_PROMPT" \
    --dangerously-skip-permissions \
    --append-system-prompt "$PROFILE_PROMPT" \
    >> "$LOG_FILE" 2>&1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Phase $PHASE $PROFILE EXITED (code: $?)" >> "$LOG_FILE"
