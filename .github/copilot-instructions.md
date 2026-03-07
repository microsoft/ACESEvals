```instructions
# SABER Repository – Copilot Instructions

**SABER** (Security Agent Benchmarking and Evaluation Research) is a distributed system for benchmarking agentic workflows in cybersecurity domains using **inspect_ai** integration with **Model Context Protocol (MCP)**.

## Repository Structure

| Path | Purpose |
|------|---------|
| `src/saber/server/` | FastAPI + FastMCP server – REST API, session management, Docker sandbox execution |
| `src/saber/client/` | Client-side – session management, REST client, MCP tool access |
| `src/saber/inspect_ai/` | Inspect AI integration – SABERSandboxEnvironment, agent registry, solvers |
| `src/saber/domain/` | Domain orchestration – manifest loading, Docker compose management |
| `src/saber/models/` | Shared Pydantic models – REST, MCP, evaluation, benchmark task models |
| `domains/` | Benchmark domains – task configurations, prompts, Docker environments |
| `docs/` | Architecture documentation and diagrams |
| `tests/` | Test suite organized by component |

## Architecture Overview

```
Inspect AI → SABERSandboxEnvironment → ClientSessionManager → REST/MCP Server
                      ↓                        ↓                    ↓
               Agent Solver              MCP Client           SessionManager
                      ↓                        ↓                    ↓
               Tool Execution          Tool Discovery      Docker Sandbox Execution
```

**Key Components**:
- `SABERSandboxEnvironment`: Inspect AI sandbox lifecycle management (task_init, sample_init, sample_cleanup)
- `SessionManager`: Central server orchestrator – sessions, episodes, execution, evaluation
- `ClientSessionManager`: Client-side session and episode management via REST
- `ExecutionManager`: Docker sandbox command execution with security validation
- `EvaluationManager`: Client-side evaluation result storage and validation
- `BenchmarkManager`: YAML-based task and benchmark configuration loading

**Key APIs**:
- REST: `/sessions`, `/episodes`, `/benchmarks`, `/policy`, `/evaluation`
- MCP: Tool discovery and execution via FastMCP server

## Python Environment

- **Use `uv`** – the package manager for this project
- Run commands: `uv run pytest`, `uv run pre-commit`
- Install deps: `uv sync --all-extras` (workspace root)
- **Do NOT** use system Python or create new virtual environments
- Python 3.11-3.12 required (managed by `.python-version`)

## Code Quality

- **Pre-commit**: Ruff linting/formatting (see `.pre-commit-config.yaml`)
- **Type hints**: Required on all public functions
- **Docstrings**: Args/Returns/Raises sections for public APIs
- **Clean code**: Small focused functions, DRY, meaningful names, proper error handling
- **Pydantic v2**: Use `ConfigDict(frozen=True)` for immutable data models

## Testing

- **Framework**: pytest with markers
- **Unit tests**: `uv run pytest` (default, no external deps)
- **Integration**: `uv run pytest -m integration` (requires Docker/services)
- **E2E**: `uv run pytest -m e2e` (full stack)
- Use `tmp_path` fixture, mock Docker/network calls
- Coverage: `uv run coverage run -m pytest && uv run coverage report`

## Key Domain Concepts

- **Session**: Client connection with lifecycle management and multiple episodes
- **Episode**: Single evaluation instance in an isolated Docker sandbox
- **Task**: YAML-defined benchmark scenario with prompts, subtasks, and evaluation config
- **Benchmark**: Collection of related tasks in a domain (excytin_demo, airt_demo)
- **Sandbox**: Docker Compose environment for secure command execution
- **MCP Tools**: Model Context Protocol tools exposed to agents for task execution
- **Evaluation**: Client-side scoring (static, LLM-judge, tool-call strategies)

## Logging Categories

SABER uses structured logging with categories:
- `LogCategory.SESSION_MANAGER`: Session and episode lifecycle
- `LogCategory.EXECUTION`: Command execution in sandboxes
- `LogCategory.EVALUATION`: Evaluation and scoring
- `LogCategory.AGENT`: Agent solver and tool execution
- `LogCategory.TASK_MANAGER`: Task and benchmark loading

## Local Development

```bash
# Install dependencies
uv sync --all-extras

# Run unit tests
uv run pytest tests/

# Run specific test file
uv run pytest tests/server/test_session_manager.py -v

# Run quality checks
uv run pre-commit run --all-files

# Enable detailed logging for debugging
INSPECT_LOG_LEVEL=info uv run inspect eval domains/excytin_demo --model openai/gpt-4
```

## Running Evaluations

```bash
# Basic evaluation
uv run inspect eval domains/excytin_demo --model openai/gpt-4

# With task filtering
uv run inspect eval domains/excytin_demo --model openai/gpt-4 -T task_filter="incident_*"

# Build/rebuild Docker images
uv run inspect eval domains/excytin_demo --model openai/gpt-4 -T build=true
uv run inspect eval domains/excytin_demo --model openai/gpt-4 -T rebuild_all=true

# Concurrency control
uv run inspect eval domains/excytin_demo --model openai/gpt-4 --max-samples 4 --max-connections 20
```

## Key Task Parameters (-T flags)

| Parameter | Purpose |
|-----------|---------|
| `task_filter` | Filter tasks by name/pattern |
| `build=true` | Build missing Docker images |
| `rebuild_all=true` | Rebuild all Docker images |
| `rebuild=<prefix>` | Rebuild specific images by prefix |
| `stop_saber_after=true` | Stop server after evaluation |
| `run_preflight=true` | Run health checks before evaluation |
| `rest_port` / `mcp_port` | Custom server ports |
| `agent=<name>` | Specify agent implementation |

## Common Patterns

### Creating a New Task
1. Add task YAML in `domains/<domain>/server/config/tasks/`
2. Include required prompts: `instruction`, `assistant`, `submit`, `continue`
3. Define `environment` (Docker Compose reference or inline)
4. Configure `submission_evaluation_config` and optionally `step_evaluation_config`

### Adding a New Agent
1. Create agent in `src/saber/inspect_ai/agents/registry/` or domain-local `client/`
2. Register with `@SABERAgentRegistry.register("agent_name")`
3. Implement `create_agent(domain_slug, ...)` function returning `Solver`

### Server-Side Component Changes
1. Update models in `src/saber/models/`
2. Implement logic in appropriate manager (`SessionManager`, `ExecutionManager`, etc.)
3. Add REST endpoint in `src/saber/server/api/`
4. Add tests in `tests/server/`

**Documentation**: [docs/README.md](docs/README.md) | **Domains**: [domains/](domains/) | **Architecture**: [docs/assets/](docs/assets/)

```
