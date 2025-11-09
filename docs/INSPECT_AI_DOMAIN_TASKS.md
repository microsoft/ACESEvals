# SABER Domain Tasks for Inspect AI

SABER provides a **domain task factory pattern** that enables SABER domains to be evaluated as standalone Inspect AI tasks. This integration provides clean task discovery, server lifecycle management, and seamless dataset loading from the running SABER server.

## Overview

The domain task pattern provides:

- **Server as Single Source of Truth**: Tasks loaded directly from SABER server (no duplicate YAML parsing)
- **Automatic Lifecycle Management**: Server starts on demand, stops after evaluation
- **Task Filtering**: Evaluate entire domains or specific tasks with exact/glob patterns
- **Concurrent Evaluation Protection**: Process-level registry prevents resource conflicts
- **Health Check Retry**: Robust server startup with automatic health verification
- **Clean Error Messages**: Actionable diagnostics for all failure modes

## Quick Start

### 1. Discover Available Domain Tasks

```bash
# List all available tasks including SABER domains
uv run inspect list tasks | grep domains/

# Output:
# domains/cybench/cybench.py@cybench
# domains/excytin/excytin.py@excytin
```

### 2. Evaluate Entire Domain

```bash
# Run all tasks in cybench domain
uv run inspect eval domains/cybench/cybench.py --model openai/gpt-4
# Or using the short form:
uv run inspect eval domains/cybench --model openai/gpt-4

# Run all tasks in excytin domain  
uv run inspect eval domains/excytin/excytin.py --model anthropic/claude-3-opus
# Or using the short form:
uv run inspect eval domains/excytin --model anthropic/claude-3-opus
```

### 3. Evaluate Specific Tasks

```bash
# Exact task match
uv run inspect eval domains/cybench \
  -T task_filter=labyrinth_linguist_task_hard \
  --model openai/gpt-4

# Glob pattern matching
uv run inspect eval domains/cybench \
  -T task_filter=labyrinth_* \
  --model openai/gpt-4

# Another glob pattern
uv run inspect eval domains/excytin \
  -T task_filter=*_forensics \
  --model anthropic/claude-3-opus
```

### 4. Custom Port Configuration

```bash
# Use different ports to avoid conflicts
uv run inspect eval domains/excytin \
  -T rest_port=9000 \
  -T mcp_port=9001 \
  --model openai/gpt-4
```

## Task Parameters

Domain tasks accept the following parameters via `-T` flags:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rest_port` | int | 8000 | REST API port for SABER server |
| `mcp_port` | int | 8001 | MCP API port for tool execution |
| `task_filter` | str | None | Filter tasks (exact match or glob pattern) |
| `log_level` | str | "INFO" | Logging level for domain services |
| `build` | str | None | Image filter for building (e.g., "server") |
| `rebuild` | str | None | Image filter for rebuilding |

## Task Filtering Patterns

The `task_filter` parameter supports multiple matching strategies:

### Exact Match
```bash
# Run only the specific task
uv run inspect eval domains/cybench -T task_filter=labyrinth_linguist_task_hard
```

### Glob Patterns
```bash
# All tasks starting with "labyrinth_"
uv run inspect eval domains/cybench -T task_filter=labyrinth_*

# All tasks ending with "_hard"
uv run inspect eval domains/cybench -T task_filter=*_hard

# All tasks containing "forensics"
uv run inspect eval domains/excytin -T task_filter=*forensics*
```

### Filter Error Handling
If no tasks match the filter, you'll get a helpful error message listing available tasks:

```
No tasks matched filter 'nonexistent' in domain 'cybench'.

Available tasks (12):
  - labyrinth_linguist_task_easy
  - labyrinth_linguist_task_hard
  - sql_injection_basic
  ...
```

## Lifecycle and Resource Management

### Server Startup
When you run a domain task, SABER:

1. **Preflight Check**: Detects already-running servers on the specified ports
2. **Domain Startup**: Starts Docker Compose services for the domain
3. **Health Checks**: Waits for server + permanent environments to be ready (retry with backoff)
4. **Task Discovery**: Queries REST API for available tasks
5. **Dataset Creation**: Converts tasks to Inspect AI samples with pre-assigned IDs
6. **Task Construction**: Returns fully-populated Task object to Inspect AI

### Server Shutdown
After evaluation completes, SABER:

1. **Sample Cleanup**: Ends episodes and terminates sessions for each sample
2. **Domain Shutdown**: Stops Docker Compose services
3. **Registry Cleanup**: Removes domain from active domains registry

### Concurrent Evaluation Protection

**Only one evaluation can run per domain at a time.** This prevents resource conflicts.

If you try to run a second evaluation while one is active:

```bash
# First terminal
uv run inspect eval domains/cybench --model openai/gpt-4

# Second terminal (will fail)
uv run inspect eval domains/cybench --model anthropic/claude-3-opus
```

**Error message:**
```
SABER domain 'cybench' is already active (owner: domain_task_cybench).

Only one evaluation can run per domain at a time to prevent resource conflicts.
Please wait for the current evaluation to complete, or use different ports:
  inspect eval domains/cybench -T rest_port=9000 -T mcp_port=9001
```

**Solutions:**
1. Wait for the first evaluation to complete
2. Use different ports for parallel evaluation
3. Manually cleanup: `docker compose -p saber-cybench down`

## Sample ID Format

Samples are assigned IDs during dataset creation using the format:

```
{task_id}__attempt_{attempt}
```

Examples:
- `labyrinth_linguist_task_hard__attempt_1`
- `labyrinth_linguist_task_hard__attempt_2`
- `sql_injection_basic__attempt_1`

**Note:** Double underscore (`__`) is used to avoid collisions with task IDs that may contain single underscores.

## Error Handling and Diagnostics

### Server Already Running
```
SABER server already running on port 8000 (domain: cybench).

This could mean:
1. Another evaluation is running (wait for it to complete)
2. Previous evaluation didn't cleanup (run: saber-domain stop cybench)
3. Port conflict with another service

To use different ports:
  inspect eval domains/cybench -T rest_port=9000 -T mcp_port=9001
```

### Health Check Timeout
```
SABER server health check failed after 30 attempts.

REST URL: http://localhost:8000

The server may have failed to start or is not responding.
Check server logs for details:
  docker logs <container_name>
  docker compose -p saber-cybench logs server
```

### Task Filter No Match
```
No tasks matched filter 'nonexistent*' in domain 'cybench'.

Available tasks (12):
  - labyrinth_linguist_task_easy
  - labyrinth_linguist_task_hard
  ...
```

## Creating Custom Domain Tasks

To add a new domain task, create a simple module in `domains/{domain}/__init__.py`:

```python
"""My custom domain for Inspect AI."""

from pathlib import Path
from saber.inspect_ai import create_domain_task

# Get workspace root (parent of domains/)
_domains_root = Path(__file__).resolve().parent.parent.parent

# Create task callable
my_domain = create_domain_task("my_domain", _domains_root)

__all__ = ["my_domain"]
```

Then use it:

```bash
uv run inspect eval domains/my_domain --model openai/gpt-4
```

## Advanced Usage

### Combine with Inspect AI Features

Domain tasks are standard Inspect AI tasks, so they work with all Inspect AI features:

```bash
# Multiple models
uv run inspect eval domains/cybench \
  --model openai/gpt-4,anthropic/claude-3-opus

# Limit samples
uv run inspect eval domains/cybench \
  -T task_filter=labyrinth_* \
  --limit 5

# Save logs to specific directory
uv run inspect eval domains/cybench \
  --log-dir ./my-eval-logs

# Continue from previous run
uv run inspect eval domains/cybench \
  --continue
```

### Integration with Custom Solvers

Use domain tasks with your own solvers:

```python
from inspect_ai import Task, eval
from inspect_ai.solver import generate, system_message
from domains.cybench import cybench

# Create custom task with domain dataset
task = cybench(task_filter="labyrinth_*")
task = Task(
    dataset=task.dataset,
    sandbox=task.sandbox,
    solver=[
        system_message("You are a security expert..."),
        generate(),
    ],
)

# Evaluate with custom solver
eval(task, model="openai/gpt-4")
```

## Troubleshooting

### Domain Won't Start

**Check Docker:**
```bash
docker ps
docker compose -p saber-{domain} ps
```

**Check Logs:**
```bash
docker compose -p saber-{domain} logs
docker logs saber-{domain}-server
```

**Manual Cleanup:**
```bash
# Stop domain manually
docker compose -p saber-{domain} down

# Or use SABER CLI
uv run python -m saber.domain stop {domain}
```

### Port Conflicts

**Check what's using ports:**
```bash
lsof -i :8000
lsof -i :8001
```

**Use different ports:**
```bash
uv run inspect eval domains/cybench -T rest_port=9000 -T mcp_port=9001
```

### Task Not Found in Filter

**List available tasks:**
```bash
# Start domain manually to see tasks
uv run python -m saber.domain start {domain}

# Query REST API
curl http://localhost:8000/api/v1/tasks | jq '.tasks[].task_id'

# Stop domain
uv run python -m saber.domain stop {domain}
```

## Architecture Details

### Task Factory Pattern

The domain task pattern uses a factory function that returns a callable. When Inspect AI invokes this callable:

1. **Portal Creation**: A process-wide `anyio.BlockingPortal` enables async operations in sync context
2. **Registry Check**: Prevents concurrent domain evaluations
3. **Server Startup**: `DomainController` starts Docker Compose services
4. **Health Checks**: Waits for server readiness with retry/backoff
5. **Task Query**: Fetches benchmark info from REST API
6. **Dataset Creation**: Converts tasks to Inspect AI `Sample` objects
7. **Task Construction**: Returns `Task` with `MemoryDataset` and sandbox config

### Ownership Transfer

The sandbox environment coordinates with the task factory:

- **Factory Mode**: Factory starts server, registers in `_active_domains`
- **Ownership Transfer**: Sandbox `task_init` detects running server and reuses it
- **Backward Compatibility**: If no factory server exists, sandbox starts it directly
- **Cleanup**: Sandbox `task_cleanup` stops server and clears both registries

This hybrid approach ensures:
- Clean shutdown via sandbox lifecycle
- No duplicate server startups
- Clear ownership semantics

## Related Documentation

- [SABER Client README](../external/saber/src/saber/client/README.md): Client architecture and CLI tools
- [Domain Development Guide](../docs/DOMAIN_DEVELOPMENT.md): Creating new SABER domains
- [SABER Architecture](../external/saber/docs/README.md): Overall system architecture
