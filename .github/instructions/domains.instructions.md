```instructions
---
applyTo: "**/domains/**"
---

# SABER Domain Instructions

## Domain Structure

Each SABER domain follows this structure:

```
domains/<domain_slug>/
├── domain.yaml           # Domain manifest (images, capabilities, ports)
├── <domain_slug>.py      # Inspect AI task factory
├── README.md             # Domain documentation
├── client/
│   └── saber.yaml        # Client-side configuration
└── server/
    ├── config/
    │   ├── tasks/        # Task YAML files (global.yaml + task_*.yaml)
    │   ├── prompts/      # Prompt templates (instruction/, assistant/, submit/)
    │   └── environments/ # Docker Compose templates
    ├── data/             # Static data files for tasks
    ├── docker/           # Dockerfiles (server, sandbox, services)
    └── logs/             # Server logs (gitignored)
```

## Key Configuration Files

| File | Purpose |
|------|---------|
| `domain.yaml` | Domain manifest: images, capabilities, ports, volumes |
| `server/config/tasks/global.yaml` | Domain-level defaults and benchmark_config |
| `server/config/tasks/task_*.yaml` | Individual task definitions |
| `server/config/environments/*.yaml` | Docker Compose environment templates |
| `server/config/prompts/` | Prompt templates organized by type |

## Domain Manifest (domain.yaml)

```yaml
schemaVersion: "1.0.0"

domain:
  slug: "my_domain"
  name: "My Domain Name"
  description: "Description of the domain"
  version: "1.0.0"

images:
  server:
    tag: "saber/my_domain/server:latest"
    dockerfile: "server/docker/Dockerfile.server"
  sandbox:
    tag: "saber/my_domain/sandbox:latest"
    dockerfile: "server/docker/Dockerfile.sandbox"

ports:
  rest:
    container: 8000
  mcp:
    container: 8001

capabilities:
  execution:
    tools:
      - "python"
      - "bash"
```

## Task Configuration

### Global Defaults (global.yaml)

```yaml
domain: "my_domain"

benchmark_config:
  episode_attempts: 3

global_defaults:
  prompts:
    instruction: "instructions/default.md"
    assistant: "assistants/default.md"
    submit: "submits/default.md"
    continue: "continues/default.md"
  execution_config:
    executors:
      bash_executor:
        timeout: 300
  episode_config:
    max_steps: 50

executors:
  - bash_executor
  - python_executor
```

### Task Definition (task_*.yaml)

```yaml
tasks:
  - task_id: "my_task"
    title: "Task Title"
    description: "Task description"
    environment: "my_environment"  # Reference to environments/*.yaml
    prompts:
      instruction: "instructions/my_task.md"
      assistant: "assistants/my_task.md"
      submit: "submits/my_task.md"
      continue: "continues/my_task.md"
    submission_evaluation_config:
      strategy: "static"
      criteria:
        expected_answers:
          - "task_completion"
      scoring:
        max_score: 1.0
    subtasks:
      - subtask_id: "step_1"
        title: "First Step"
        description: "Description of first step"
        objective: "What to achieve"
        completion_conditions: ["command_1", "command_2"]
```

## Docker Configuration

### Dockerfile Patterns

- `Dockerfile.server`: SABER server with FastAPI + FastMCP
- `Dockerfile.sandbox`: Agent execution environment with tools
- `Dockerfile.<service>`: Additional services (databases, etc.)

### Environment Templates

```yaml
# server/config/environments/my_environment.yaml
services:
  sandbox:
    image: "${SANDBOX_IMAGE}"
    networks:
      - shared-network
    environment:
      - EPISODE_ID=${EPISODE_ID}

networks:
  shared-network:
    driver: bridge
```

## Building and Testing

```bash
# Build domain images incrementally
uv run inspect eval domains/my_domain --model openai/gpt-4 -T build=true

# Rebuild all domain images
uv run inspect eval domains/my_domain --model openai/gpt-4 -T rebuild_all=true

# Test specific tasks
uv run inspect eval domains/my_domain --model openai/gpt-4 -T task_filter="my_task"

# Run with preflight validation
uv run inspect eval domains/my_domain --model openai/gpt-4 -T run_preflight=true
```

## Naming Conventions

- Domain slug: `snake_case` (e.g., `excytin_demo`)
- Task IDs: `snake_case` (e.g., `incident_5_task_1`)
- Environment names: `snake_case` (e.g., `incident_5_db`)
- Docker image tags: `saber/<domain>/<component>:latest`

## Evaluation Strategies

| Strategy | Use Case |
|----------|----------|
| `static` | Exact answer matching |
| `llm_judge` | LLM-based evaluation with rubrics |
| `tool_call` | Verify specific tool invocations |
| `none` | No submission evaluation (continuous tasks) |

```
