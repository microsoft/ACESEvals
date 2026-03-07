---
name: inspect-eval-execution
description: Guide for running SABER inspect_ai evaluations locally. Use this when asked to run, re-run, or configure an inspect eval for any SABER domain.
---

To run SABER inspect_ai evaluations locally, follow this process:

## 1. Understand the Domain Structure

Each domain lives in `domains/<domain>/` and follows this layout:

```
domains/<domain>/
  <domain>.py          # @task entry point — calls create_task()
  eval.yaml            # Domain metadata, Docker image definitions
  tasks/
    global.yaml        # Default prompts, tools, max_steps, aggregation
    <task_group>/
      <task>.yaml      # Individual task definitions
  compose/
    sandbox.compose.yml  # Docker Compose for sandbox containers
  scoring/             # Domain-specific scoring strategies
  tools/               # Domain-specific MCP tools
  prompts/             # Jinja2 prompt templates (instructions/, assistants/, etc.)
  docker/              # Dockerfiles for sandbox images
```

The `<domain>.py` file is minimal — it just calls `saber.task.create_task(**kwargs)` which wires up config loading, prompt rendering, scoring, tools, and the agent.

## 2. Build Docker Images First

Before running evals, ensure Docker images are built:

```bash
# Build all images for a domain
uv run saber build <domain>

# Or auto-build during eval (slower, builds missing images)
uv run inspect eval domains/<domain> --model <model> --display plain -T build=true

# Force rebuild all images
uv run inspect eval domains/<domain> --model <model> --display plain -T rebuild_all=true

# Rebuild specific images by prefix
uv run inspect eval domains/<domain> --model <model> --display plain -T rebuild=sandbox
```

## 3. Run an Evaluation

Always use `--display plain` to disable the Rich interactive progress display.
This outputs clean, parseable text instead of ANSI escape sequences and cursor
manipulation that pollute AI agent context windows.

```bash
# Basic evaluation (all tasks)
uv run inspect eval domains/<domain> --model <model> --display plain

# Common model formats:
#   openai/azure/gpt-4.1        (Azure OpenAI)
#   openai/azure/gpt-5.2        (Azure OpenAI)
#   openai/gpt-4o               (OpenAI direct)
#   anthropic/claude-sonnet-4-20250514 (Anthropic)

# Run a single sample for quick iteration
uv run inspect eval domains/<domain> --model <model> --display plain --limit 1

# Filter to specific tasks
uv run inspect eval domains/<domain> --model <model> --display plain -T task_filter="sanity_*"
uv run inspect eval domains/<domain> --model <model> --display plain -T task_filter="incident_response_01"

# Multiple task patterns (comma-separated)
uv run inspect eval domains/<domain> --model <model> --display plain -T task_filter="sanity_*,advanced_*"
```

## 4. Key `-T` Parameters

| Parameter | Purpose | Example |
|-----------|---------|---------|
| `task_filter` | Glob pattern to select tasks | `-T task_filter="sanity_*"` |
| `build=true` | Build missing Docker images | `-T build=true` |
| `rebuild_all=true` | Rebuild ALL Docker images | `-T rebuild_all=true` |
| `rebuild=<prefix>` | Rebuild images matching prefix | `-T rebuild=sandbox` |
| `agent=<name>` | Agent implementation | `-T agent=react` |
| `run_preflight=true` | Health check before eval | `-T run_preflight=true` |
| `keep_permanent=true` | Keep permanent services alive | `-T keep_permanent=true` |

## 5. Control Concurrency and Limits

```bash
# Limit number of concurrent samples
uv run inspect eval domains/<domain> --model <model> --display plain --max-samples 4

# Limit concurrent model API connections
uv run inspect eval domains/<domain> --model <model> --display plain --max-connections 20

# Combine limits for stability
uv run inspect eval domains/<domain> --model <model> --display plain --limit 1 --max-samples 1
```

## 6. Enable Verbose Logging

```bash
# Show info-level logs during eval
INSPECT_LOG_LEVEL=info uv run inspect eval domains/<domain> --model <model> --display plain

# Show debug-level logs (very verbose)
INSPECT_LOG_LEVEL=debug uv run inspect eval domains/<domain> --model <model> --display plain

# Write Python logger output to file
INSPECT_PY_LOGGER_FILE=/tmp/eval_debug.log uv run inspect eval domains/<domain> --model <model> --display plain
```

## 7. Iterative Development Workflow

When developing or debugging a domain:

1. **Start with `--limit 1`** to run a single sample quickly
2. **Use `task_filter`** to isolate the specific task you're working on
3. **Pipe output** to capture both stdout and stderr: `2>&1 | tee /tmp/eval_output.log`
4. **Check the eval log** — the path is printed at the end: `Log: logs/<timestamp>_<domain>_<id>.eval`
5. **Iterate on scoring/tools** — changes to domain code in `domains/<domain>/` take effect immediately (no reinstall needed)
6. **Changes to `saber` or `inspect_ai`** — if installed as editable, take effect immediately; if installed from git, you must edit the files in `.venv/lib/python3.11/site-packages/` directly and clear `__pycache__` dirs

## 8. Understand the Score Output

The eval summary shows scores organized by task and scorer:

```
saber_overall         task_name_1            task_name_2
mean           0.500  accuracy        1.000  accuracy        0.000
stderr         0.000  stderr          0.000  stderr          0.000
```

- `saber_overall` is the aggregate across all tasks
- Each task shows its `accuracy` (the final aggregated score)
- `nan` means the scorer did not produce a result (e.g., the agent didn't reach that evaluation point)
- Multiple scorers per task (e.g., `submission`, `crash_analysis`, `root_cause`) are aggregated per the task's `scoring_aggregation` config

## 9. Common Issues

- **"No tasks found"**: Check `task_filter` matches task YAML filenames (without `.yaml` extension)
- **Docker build failures**: Run `uv run saber build <domain>` separately to see full build output
- **Model API errors**: Verify environment variables (`AZURE_OPENAI_API_KEY`, `OPENAI_API_KEY`, etc.)
