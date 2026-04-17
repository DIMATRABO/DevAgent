status: COMPLETE
updated_at: 2026-04-16T00:00:00Z
output_file: /workspace/strategy/architecture_target.md
summary: >
  Full target architecture designed for the Sanad multi-agent system. The document
  specifies the complete Task Orchestrator REST API (7 endpoints with request/response
  schemas and HTTP status codes), the SQLite schema for four tables (tasks, task_steps,
  agents, events), an ASCII state machine covering all 7 task states and all valid
  transitions, a precise numbered HTTP call-flow for the agent handoff protocol including
  the Architect→Dev scenario end-to-end, the HR Agent API with exact Docker lifecycle
  commands, the AgentSession context persistence schema with save-trigger rules and resume
  protocol, the exact file changes required in sanad_agent for Phase 3, and binding design
  decisions on SQLite vs Redis, Orchestrator-mediated routing vs agent-to-agent calls,
  structured tool-call JSON vs to_run.py script execution, and context save location.
blocker: none
