# Architecture: Current State
**Produced by:** Architect — Phase 0 Discovery (all file:line refs verified by direct read)
**Date:** 2026-04-16
**Repos scanned:** sanad_agent, SanadReasoningLayer, claude-code-typescript, clawd-code

---

## 1. System Overview

The Sanad POC consists of two running services and two reference codebases.

```
┌─────────────────────────────────────────────────────────┐
│  Docker Network: sanad_network                          │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────────┐ │
│  │  sanad_agent (×3)    │   │ SanadReasoningLayer     │ │
│  │  CEO     :9000       │──▶│ FastAPI  :5600          │ │
│  │  Architect :9001     │   │ LLM router              │ │
│  │  Dev     :9002       │   │ 8 providers configured  │ │
│  └──────────────────────┘   └────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

Three instances of the **same** `sanad_agent` Docker image run with different `AGENT_ROLE` env vars (CEO, Architect, Dev). Each exposes one HTTP endpoint and shares a file-based memory system via volume mounts.

---

## 2. sanad_agent — Complete File Map

**Path:** `projects/sanad_agent/`

| File | Description |
|------|-------------|
| `main.py` | FastAPI app; registers chat router at `/api/v1`; `startup_event()` is empty |
| `controllers/chat_controller.py` | Defines `POST /api/v1/chat`; validates API key; adds background task; returns 200 immediately |
| `services/chat_service.py` | `chat_with_agent()`: builds prompt → calls reasoning layer → writes response code to `to_run.py` → executes it |
| `actions/agent/prompt_builder.py` | `PromptBuilder`: loads `memory/private/{ROLE}/*.md` + `memory/public/agent_project/*.md` into prompt dict |
| `actions/agent/think.py` | `think(url, data)`: HTTP POST to reasoning layer; returns raw JSON response |
| `actions/agent/send_message.py` | `send_message(url, message)`: HTTP POST to another agent's `/api/v1/chat` |
| `actions/agent/request_hiring.py` | `request_hiring(role, hiring_config)`: HTTP POST to `HR_URL`; raises `ValueError` if `HR_URL` unset |
| `actions/agent/update_context.py` | **Empty file** — 1 line, no implementation |
| `actions/execute_command.py` | `execute_command(cmd)`: `subprocess.run(cmd, shell=True, capture_output=True)` |
| `actions/file/write_file.py` | `open(path,'w').write(content)` |
| `actions/file/read_file.py` | `open(path,'r').read()` |
| `actions/file/move_file.py` | File move utility |
| `actions/file/delete_file.py` | File delete utility |
| `actions/file/update_file.py` | File update utility |
| `actions/folder/create_folder.py` | `os.makedirs()` wrapper |
| `actions/folder/delete_folder.py` | `shutil.rmtree()` wrapper |
| `actions/git/clone.py` | `git clone` via subprocess |
| `actions/git/pull.py` | `git pull` via subprocess |
| `actions/git/push.py` | `git push` via subprocess |
| `actions/git/add_commit.py` | `git add + commit` via subprocess |
| `dto/reasoning_request_dto.py` | Pydantic: `prompt: str`; validator auto-adds `"User: "` prefix if no role tag |
| `exceptions/exception.py` | `BadGatewayException`, `UnauthorizedException` |
| `exceptions/exception_handlers.py` | HTTP 502/401 handlers |
| `dependencies/api_key_dependency.py` | `x-api-key` header auth |
| `services/on_start_service.py` | **Empty file** — 1 line, no implementation |
| `memory/private/CEO/who_iam.md` | CEO identity: strategic executive, delegate-not-execute |
| `memory/private/CEO/what_i_can_do.md` | CEO tool list: `think`, `send_message`, `reflect`, `read/write_file`, `execute_command`, `request_hiring` |
| `memory/private/CEO/context_tracker.md` | Current state: "User approved task delegation" |
| `memory/private/CEO/shortterm_memory.md` | Active task notes |
| `memory/private/CEO/longterm_memory.md` | Persistent knowledge |
| `memory/private/Architect/` | Same 5-file structure for Architect role |
| `memory/private/Dev/` | Same 5-file structure for Dev role |
| `memory/public/agent_project/workflow.md` | Task lifecycle: `NEW_TASK → ARCHITECTURE_DESIGN → IMPLEMENTATION_PLAN → IMPLEMENTATION_APPROVED → IMPLEMENTING → COMPLETED` |
| `memory/public/agent_project/team.md` | Agent URLs: `CEO:http://sanad_agent:9000/api/v1/chat`, `Architect::9001`, `Dev::9002` |
| `memory/public/agent_project/architecture.md` | Finance-app architecture notes (example prior task) |
| `memory/public/agent_project/tasks_to_do.md` | Finance-app task list (example prior task) |
| `memory/public/agent_project/strategy_overview.md` | Strategy doc for prior task |
| `memory/public/agent_project/response_instructions.md` | Response formatting instructions |
| `memory/public/workspace/` | Same structure for workspace-level public memory |
| `docker-compose.yml` | 4 services: `reasoning_layer` (port 5600), `sanad_agent` (9000), `sanad_agent_architect` (9001), `sanad_agent_dev` (9002) on `sanad_network` bridge |
| `to_run.py` | **Generated file** — LLM output written here and executed each request |
| `.env.example` | `PORT=9001`, `AGENT_ROLE=Architect`, `REASONING_API_URL`, API keys (placeholders) |
| `.env.dev` | `PORT=9002`, `AGENT_ROLE=Dev` |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container definition |

### FastAPI Endpoints

| Method | Path | Auth | Response |
|--------|------|------|---------|
| POST | `/api/v1/chat` | `x-api-key` header | `{"message": "Chat processing started in the background."}` — 200 immediately, result never returned |

**No** health endpoint. **No** status endpoint. **No** agent registration endpoint.

### Configuration Variables

| Variable | Purpose | Set in |
|----------|---------|--------|
| `PORT` | Per-instance port | `.env*` |
| `AGENT_ROLE` | CEO / Architect / Dev | `.env*` |
| `AGENTS_API_KEY` | Auth for incoming requests | `.env*` |
| `RL_API_KEY` | Auth for reasoning layer | `.env*` |
| `REASONING_API_URL` | Reasoning layer endpoint | `.env*` |
| `PROVIDER` | LLM provider name | `.env*` (default: `githubgpt4o`) |
| `HR_URL` | HR service endpoint | **Not set anywhere** |

---

## 3. The Exact Broken Chain (verified)

### Sequence Diagram

```
User/Telegram
     │
     │ POST /api/v1/chat {prompt}
     ▼
[sanad_agent CEO :9000]  ← chat_controller.py
     │ background_task added → returns 200 to caller
     │
     │ [background task runs chat_service.py:chat_with_agent()]
     │
     │ POST /api/v1/reasoning/generate
     │   {prompt: "{ Memory: {...}, User Message: ... }", provider: "githubgpt4o"}
     ▼
[SanadReasoningLayer :5600]
     │ → githubgpt4o driver → Azure GitHub Models (gpt-4o)
     │ ← JSON: {"action": "<python code string>", ...}
     ▼
[sanad_agent CEO :9000]  ← back in chat_service.py
     │ write_file("to_run.py", response.get("action", ""))
     │ execute_command("python to_run.py")
     │
     ├── IF LLM generated code calling send_message():
     │     POST /api/v1/chat to Architect :9001
     │     ... (same cycle repeats — also fire-and-forget)
     │
     └── IF LLM did NOT generate send_message() call:
           [CHAIN DIES SILENTLY]
     │
     │ return cmd_result ← returned to background task
     ▼
[background task: return value DISCARDED]
[original caller never receives result]
```

### Exact Broken Locations

**Location 1 — result discarded:**
`projects/sanad_agent/controllers/chat_controller.py:9-11`
```python
async def background_chat_processing(request: ReasoningRequestDTO):
    """This runs in the background."""
    await chat_with_agent(request)   # ← return value discarded, nobody receives it
```

**Location 2 — no next-agent notification:**
`projects/sanad_agent/services/chat_service.py:13-19`
```python
async def chat_with_agent(request):
    orchestration_payload = prompt_builder.build_prompt(request.prompt, provider)
    response = think(reasoning_api_url, orchestration_payload)
    print(f"Reasoning response: {response}")
    write_file("to_run.py", response.get("action", ""))    # line 17
    cmd_result = execute_command("python to_run.py")        # line 18
    return cmd_result                                       # line 19 — nobody receives this
```

**Location 3 — context preservation is empty:**
`projects/sanad_agent/actions/agent/update_context.py` — **file is empty** (1 line). When LLM-generated code calls `update_context()`, nothing happens. No state is saved.

**Root cause:** Two structural failures:
1. HTTP endpoint returns 200 before work begins; result has no path back to caller
2. Chain continuation depends entirely on the LLM including `send_message()` in its generated code — not guaranteed, not validated, not retried on failure

---

## 4. SanadReasoningLayer — Complete File Map

**Path:** `projects/SanadReasoningLayer/`

| File | Description |
|------|-------------|
| `main.py` | FastAPI app; registers reasoning router at `/api/v1` |
| `controllers/generate_reasoning_controller.py` | `POST /api/v1/reasoning/generate`; calls `generate_reasoning()` synchronously |
| `services/reasoning_service.py` | `generate_reasoning()`: calls `LLMAdapter.send_message()`, strips ` ```json ` wrappers, parses JSON |
| `adapters/llm_adapter_abstraction.py` | `BaseLLMDriver` ABC; `LLMAdapter` class |
| `adapters/imp/githungpt4o_llm_adapter.py` | **WORKING** — `AsyncOpenAI`, Azure GitHub Models, model=gpt-4o |
| `adapters/imp/deepseek_llm_adapter.py` | **WORKING** — `Azure AI Inference SDK`, `DeepSeek-V3-0324` |
| `adapters/imp/openRouter_llm_adapter.py` | **WORKING** — OpenRouter sync, `arcee-ai/trinity-large-preview:free` |
| `adapters/imp/openRouterLiquid_llm_adapter.py` | **WORKING** — OpenRouter sync, `liquid/lfm-2.5-1.2b-thinking:free` |
| `adapters/imp/anthropic_llm_adapter.py` | **STUB** — `return f"[anthropic] {prompt}"`, no API call |
| `adapters/imp/azure_llm_adapter.py` | **BROKEN** — calls `client.responses.create()` (invalid OpenAI SDK method) |
| `adapters/imp/openAI_llm_adapter.py` | **BROKEN** — same invalid call, model=`gpt-5` (nonexistent) |
| `adapters/imp/gemini_llm_adapter.py` | **LIKELY BROKEN** — OpenAI sync client, model=`gpt-4o`, Azure base URL |
| `dto/reasoning_request_dto.py` | `prompt: str`, `provider: str = "githubgpt4o"` |
| `dto/reasoning_response_dto.py` | `content: str` — defined but never used by service |
| `dto/provider_dto.py` | `Provider` dataclass with `name, api_base_url, api_key, enabled, max_retries` — **never instantiated** |
| `dependencies/api_key_dependency.py` | API key auth |
| `utils/security.py` | Security utilities |
| `exceptions/exception.py` | Custom exceptions |
| `exceptions/exception_handlers.py` | HTTP error handlers |
| `.env` | All provider keys + base URLs (8 providers configured) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container definition |

### FastAPI Endpoints

| Method | Path | Auth | Response |
|--------|------|------|---------|
| POST | `/api/v1/reasoning/generate` | `X-API-Key` header | Parsed JSON from LLM response |

**No** health endpoint. **No** provider status endpoint. **No** token usage endpoint.

### LLM Routing Logic (verified line-by-line)

**File:** `projects/SanadReasoningLayer/adapters/llm_adapter_abstraction.py`

```python
class LLMAdapter:
    def __init__(self):
        self.providers = self._load_providers()  # reads "providers" env var

    def _select_provider(self) -> str:
        return "githubgpt4o"                  # line 35 — HARDCODED
        return random.choice(self.providers)  # line 36 — DEAD CODE, never reached

    async def send_message(self, prompt: str, provider: str = None, **kwargs) -> str:
        #provider_name = self._select_provider()  # line 67 — commented out
        driver = self._instantiate_driver(provider)  # uses caller-supplied value directly
        return await driver.send_message(prompt, **kwargs)
```

The `provider` value flows: `.env`(`PROVIDER=githubgpt4o`) → `chat_service.py:10` → request DTO → reasoning controller → `LLMAdapter.send_message()`. The `_select_provider()` method and `providers` list are unused in the actual call path.

### Provider Status Table

| Provider key | SDK | Status | Notes |
|-------------|-----|--------|-------|
| `githubgpt4o` | `AsyncOpenAI` | **WORKING** | Only async driver; default |
| `deepseek` | `Azure AI Inference` | **WORKING** | Sync in async context |
| `openrouter` | `OpenAI` (sync) | **WORKING** | Free model |
| `openrouterliquid` | `OpenAI` (sync) | **WORKING** | Free model |
| `anthropic` | None | **STUB** | Returns `"[anthropic] {prompt}"` |
| `azure` | `OpenAI` (sync) | **BROKEN** | `client.responses.create()` doesn't exist |
| `openai` | `OpenAI` (sync) | **BROKEN** | Same; model=`gpt-5` (nonexistent) |
| `gemini` | `OpenAI` (sync) | **LIKELY BROKEN** | Wrong model, wrong endpoint |

### What the Providers List Contains

`.env` configures: `providers=openai,azure,anthropic,gemini,githubgpt4o,deepseek,openrouter`

All provider keys and base URLs are configured. Base URLs: GitHub Models (`azure.ai.azure.com`), OpenRouter (`openrouter.ai`), GitHub AI inference (`models.github.ai`).

### Token Management

**None.** No token counting, no rate-limit detection, no provider switching on limit, no context save on limit. The `Provider` dataclass defines `max_retries` and `enabled` but is never instantiated. No retry logic anywhere.

---

## 5. Reference Codebases

### claude-code-typescript (`projects/claude-code-typescript/`)

The Claude Code CLI source in TypeScript. Key patterns for Sanad:

**Task State Machine** (`src/Task.ts` + `src/tasks/types.ts`):
```typescript
type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'killed'

type TaskType = 'local_bash' | 'local_agent' | 'remote_agent' |
                'in_process_teammate' | 'local_workflow' | 'monitor_mcp' | 'dream'

type TaskStateBase = {
  id: string           // prefixed random ID: 'b', 'a', 'r', 't', 'w', 'm', 'd'
  type: TaskType
  status: TaskStatus
  description: string
  toolUseId?: string
  startTime: number
  endTime?: number
  totalPausedMs?: number
  outputFile: string   // disk path for output streaming
  outputOffset: number // read cursor position
  notified: boolean    // whether completion was surfaced to caller
}
```

The `notified` flag is critical — it prevents dropped completions from going unnoticed.

**Terminal state guard** (`src/Task.ts:27-29`):
```typescript
export function isTerminalTaskStatus(status: TaskStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'killed'
}
```

**Task state union** (`src/tasks/types.ts:12-19`):
```typescript
export type TaskState =
  | LocalShellTaskState    // bash commands
  | LocalAgentTaskState    // subprocess agent
  | RemoteAgentTaskState   // networked agent
  | InProcessTeammateTaskState  // in-process
  | LocalWorkflowTaskState
  | MonitorMcpTaskState
  | DreamTaskState
```

**Session Spawning** (`src/bridge/sessionRunner.ts`):
- Spawns child claude CLI processes with NDJSON stdio: `--input-format stream-json --output-format stream-json`
- Session states: `completed | failed | interrupted`
- Activity ring buffer (10 events): `tool_start | text | result | error`
- Permission requests forwarded via `control_request` NDJSON messages
- `writeStdin(data)` — sends control messages to child via stdin
- `kill()` → SIGTERM, `forceKill()` → SIGKILL
- Token refresh: sends `update_environment_variables` message over stdin

**Agent listing** (`src/cli/handlers/agents.ts`):
- Agents discovered from directory definitions
- Agents have: agentType, model override, memory config, source group
- Source groups provide override precedence

**Key pattern for Sanad:** Fire-and-forget workers + notification-based completion. Coordinator owns workflow state, workers report results via structured messages.

---

### clawd-code (`projects/clawd-code/`)

Python reimplementation of Claude Code. Most reusable patterns for Sanad:

**Conversation model** (`src/agent/conversation.py`):
```python
@dataclass
class TextContentBlock: type: str; text: str
@dataclass
class ToolUseContentBlock: type, id, name, input
@dataclass
class ToolResultContentBlock: type, tool_use_id, content, is_error

@dataclass
class Conversation:
    messages: list[Message]
    max_history: int = 100
    # Serializable to/from dict (Anthropic API format)
    def add_message/add_user_message/add_assistant_message/add_tool_result_message()
    def get_messages() -> list[dict]   # Anthropic API format
    def to_dict() / from_dict()
```

**Session persistence** (`src/agent/session.py`):
```python
@dataclass
class Session:
    session_id: str          # datetime-based: "YYYYMMDD_HHMMSS"
    provider: str
    model: str
    conversation: Conversation
    created_at: str
    updated_at: str

    def save(self)            # → ~/.clawd/sessions/{session_id}.json
    def load(cls, id)         # ← disk (returns None if not found)
    def create(cls, provider, model)  # → new Session
```

**Task manager** (`src/tool_system/task_manager.py`):
```python
@dataclass(frozen=True)
class ManagedTask:
    task_id: str                   # uuid4
    name: str
    started_at: float
    stop_event: threading.Event    # signal for graceful shutdown
    thread: threading.Thread

class TaskManager:
    # Thread-safe: _lock guards _tasks dict
    def start(*, name, target) -> ManagedTask  # target receives stop_event
    def stop(task_id) -> bool                  # sets stop_event
    def get(task_id) -> Optional[ManagedTask]
    def list() -> list[ManagedTask]
```

**Tool protocol** (`src/tool_system/protocol.py`):
```python
@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    tool_use_id: Optional[str] = None

@dataclass(frozen=True)
class ToolResult:
    name: str
    output: Any
    is_error: bool = False
    tool_use_id: Optional[str] = None
    content_type: Literal["text", "json"] = "json"
```

**Agent loop** (`src/tool_system/agent_loop.py`):
- Multi-turn tool calling loop
- Uses `ToolRegistry`, `ToolContext`, `BaseProvider`
- Supports both Anthropic and OpenAI provider protocols
- Tool results summarized for display (`summarize_tool_result()`)

**Context compaction** (`src/compact_service/service.py`):
- `compact_conversation(conversation, provider, model)` → `CompactResult`
- Summarizes older messages via LLM into a boundary + summary pair
- `CompactResult` has: `boundary_message, summary_message, tokens_saved, pre/post_compact_count, summary_text, trigger`

**Microcompact** (`src/context_system/microcompact.py`):
- `strip_images_from_messages()` — replaces image/document blocks with `[image]`/`[document]`
- `microcompact_messages(messages, keep_recent=3)` — clears old tool results beyond last 3
- Returns `(modified_messages, tokens_saved)`

**Context builder** (`src/context_system/builder.py`):
- `build_context_prompt(workspace_root)` → structured context string
- Sections: workspace snapshot (files, cwd), git context (branch, commit, status), CLAUDE.md files

**Cost tracker** (`src/cost_tracker.py`):
- Minimal: `record(label, units)` → `total_units += units`. No per-provider breakdown.

**Coordinator** (`src/coordinator/__init__.py`):
- **Not implemented** — placeholder reads from archived JSON. The coordinator was never ported to Python.

---

## 6. Docker Topology (current)

**File:** `projects/sanad_agent/docker-compose.yml`

```
services:
  reasoning_layer       image: sanadrl     port: 5600    (SanadReasoningLayer)
  sanad_agent           build: .           port: 9000    AGENT_ROLE=CEO (from .env)
  sanad_agent_architect build: .           port: 9001    AGENT_ROLE=Architect (from .env.example)
  sanad_agent_dev       build: .           port: 9002    AGENT_ROLE=Dev (from .env.dev)

network: sanad_network (bridge)
```

All containers on same Docker bridge network. Agents reach each other by service name (e.g., `http://sanad_agent_architect:9001`). Agent instances share the host directory via volume mount (`./:/sanad_agent`).

---

## 7. Full Data Flow (current)

```
User/Telegram
     │
     ▼ POST /api/v1/chat {prompt: "CEO: build X"}
[CEO :9000]    ← chat_controller.py
     │ queue background task, return 200
     │
     ▼ [background] chat_service.py
[PromptBuilder]
     │ reads memory/private/CEO/*.md
     │ reads memory/public/agent_project/*.md
     │ prompt = "{ Memory: {...}, User Message: CEO: build X }"
     │
     ▼ POST /api/v1/reasoning/generate {prompt, provider="githubgpt4o"}
[SanadReasoningLayer :5600]
     │ → Azure GitHub Models → gpt-4o
     │ ← {"action": "from actions.agent.send_message import...\nsend_message(...)"}
     │
     ▼ write to_run.py, execute python to_run.py
[to_run.py subprocess]
     │ IF send_message() in generated code:
     │     POST /api/v1/chat to Architect :9001 {"prompt": "CEO: <msg>"}
     │     same loop repeats for Architect
     │     Architect POST to Dev :9002 ...
     │     Dev POST back to Architect ...
     │     [each hop is fire-and-forget with no result return]
     │ IF no send_message() generated:
     │     CHAIN STOPS SILENTLY
     │
     ▼ execute_command returns cmd_result
     │ chat_service.py returns cmd_result to background task
     ▼
[result DISCARDED — no caller, no storage, no notification]
```

**Conclusion:** The POC has correct infrastructure (Docker networking, memory files, reasoning layer) but no workflow persistence, no guaranteed handoff, and no result delivery. The chain is held together only by the LLM's willingness to generate `send_message()` calls in every response.
