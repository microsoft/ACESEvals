# OSS SABER - Open Source Security Agent Benchmarking

**Production-ready security benchmarking domains for agentic workflow evaluation.**

SABER is a modern distributed system for benchmarking AI security agents using the inspect_ai framework with Model Context Protocol (MCP) integration. This repository contains open-source security domains for penetration testing, incident response, and multi-agent coordination scenarios.

### Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        OSS SABER                               │
│  Open Source Security Agent Benchmarking & Evaluation         │
└────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼───────┐    ┌────────▼────────┐   ┌───────▼───────┐
│    Excytin    │    │    CyBench      │   │  SABER Dual   │
│   Incident    │    │   CTF/Pentest   │   │   Red vs Blue │
│   Response    │    │   Challenges    │   │   Adversarial │
└───────────────┘    └─────────────────┘   └───────────────┘

Each domain contains:
├── domain.yaml          # Domain manifest and configuration
├── server/              # Task definitions and execution logic
│   ├── config/
│   │   ├── tasks/       # YAML task definitions
│   │   ├── prompts/     # Agent prompts and templates
│   │   └── environments/# Docker compose environments
│   └── data/            # Domain-specific data
├── client/              # Agent configuration
│   └── saber.yaml       # Client evaluation config
└── docker/              # Container images
    ├── Dockerfile.server
    └── Dockerfile.sandbox
```

---

## Quick Start

### Prerequisites

- **Docker** (with Docker Compose v2)
- **Python 3.10+**
- **uv** package manager
- **Azure OpenAI** or compatible LLM endpoint

### Installation

```bash
# 1. Clone the repository
git clone https://dev.azure.com/MSECAIModels/Benchmarking/_git/oss_saber
cd oss_saber

# 2. Install uv package manager (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env  # Add uv to PATH

# 3. Install SABER git submodule
git submodule update --init external/saber

# 4. Install SABER dependencies
uv sync --all-extras

# 5. Configure Azure OpenAI credentials
cp .env.template .env
# Edit .env with your Azure OpenAI credentials:
#   AZUREAI_OPENAI_API_KEY=your-key-here
#   AZUREAI_OPENAI_BASE_URL=https://your-endpoint.openai.azure.com
#   AZUREAI_OPENAI_API_VERSION=2024-12-01-preview
```

### Run Your First Evaluation

#### NOTE: Excytin cold start extra step
If you are running excytin benchmark, you will need to reach out to Anand Mudgerikar or Kyle DeProw and get the excytin data. You will need to have a <>/csv_files and <>/sql_files directory at domains/excytin/server/data after this step.

**All domain evaluations now use `inspect eval` commands.** The SABER server is automatically managed - started on first evaluation and kept running for faster subsequent runs.

```bash
# List available domains
uv run inspect list tasks

# Basic evaluation (server auto-starts and stays running)
uv run inspect eval domains/excytin --model openai/azure/gpt-4

# Build images automatically before evaluation
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T build=true

# Rebuild all images (clean slate)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T rebuild_all=true

# Rebuild only server image
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T rebuild=server

# Stop server after evaluation completes
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T stop_saber_after=true

# Filter to specific tasks
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T task_filter="incident_5*"

# Combine options
uv run inspect eval domains/cybench --model openai/azure/gpt-4 \
  -T build=true \
  -T task_filter="labyrinth_*" \
  --limit 5

# Clean run with server cleanup
uv run inspect eval domains/cybench --model openai/azure/gpt-4 \
  -T rebuild_all=true \
  -T stop_saber_after=true
```

**What happens automatically:**
1. Server validation and startup with health checks
2. Docker image building (if `-T build=true` or rebuild flags)
3. Task loading from SABER server
4. Evaluation execution
5. Server stays running for faster re-runs (use `-T stop_saber_after=true` to stop)

## 📚 Available Domains

### 1. Excytin - Incident Response

**Cybersecurity incident response with database forensics.**

Excytin includes four task sets for different evaluation purposes:

| Task Set | Description | Task Count | Recommended Use |
|----------|-------------|------------|-----------------|
| `latest_test_set` | New O3-generated test questions | 599 tasks | **Benchmarking & Evaluation** |
| `latest_train_set` | New O3-generated training questions | 418 tasks | **Training & Fine-tuning** |
| `legacy_test_set` | Legacy O1-preview generated test tasks | 589 tasks | Paper comparison only |
| `legacy_train_set` | Legacy O1-preview generated training questions | 418 tasks | Paper comparison only |

#### Task Set Details

**`latest_test_set` / `latest_train_set` (Recommended)**
- High-quality questions generated with GPT-o3 model.
- **Use these for training, fine-tuning, and accurate benchmarking**

**`legacy_test_set` / `legacy_train_set` (Paper Comparison Only)**
- Original datasets generated using GPT-o1-preview (test) and GPT-o1-ga (train) used in the [arXiv paper](https://arxiv.org/abs/2507.14201)
- If you want to reproduce or compare results with the paper, use these sets.
- ⚠️ **Note:** These are noisier datasets with less consistent formatting
- **Not recommended** for training, hill climbing, or new model development
- Use `latest_test_set` and `latest_train_set` for most accurate evaluations

#### Running Specific Task Sets

```bash
# Run ALL tasks (all task sets combined)
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1

# Run only the latest test set (recommended for evaluation)
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_latest_test_set_*"

# Run only the latest train set (for training/fine-tuning)
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_latest_train_set_*"

# Run only legacy test set (original tasks)
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_legacy_test_set_*"

# Run only legacy train set
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_legacy_train_set_*"

# Run specific incident within a task set
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_5_latest_test_set_*"

# Limit number of tasks for quick testing
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_latest_test_set_*" \
  --limit 10
```

#### Quick Start Examples

```bash
# Quick evaluation with latest test set
uv run inspect eval domains/excytin --model openai/azure/gpt-4.1 \
  -T task_filter="incident_*_latest_test_set_*"

# With image build and cleanup
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4.1 \
  -T build=true \
  -T task_filter="incident_*_latest_test_set_*" \
  -T stop_saber_after=true
```

---

### 2. CyBench - CTF Challenges

**Web application penetration testing and CTF scenarios.**

```bash
# Quick evaluation
uv run inspect eval domains/cybench --model openai/azure/gpt-4

# With image build and task filtering
uv run inspect eval domains/cybench \
  --model openai/azure/gpt-4 \
  -T build=true \
  -T task_filter="labyrinth_*"
```

---

### 3. SABER Dual - Red vs Blue Adversarial

**Multi-agent adversarial cyber simulation with red team penetration testing vs blue team incident response.**

```bash
# Red team only
uv run inspect eval domains/saber_dual \
  --model openai/azure/gpt-4 \
  -T task_filter="saber_dual_red_team"

# Blue team only
uv run inspect eval domains/saber_dual \
  --model openai/azure/gpt-4 \
  -T task_filter="saber_dual_blue_team"

# Both teams (orchestrated)
uv run inspect eval domains/saber_dual \
  --model openai/azure/gpt-4 \
  -T roles_file=domains/saber_dual/saber_dual_roles.yaml \
  -T task_filter="saber_dual_blue_team,saber_dual_red_team"
```

---

## 🛠️ Development Workflow

### Evaluation Commands

All domain operations use `inspect eval` with task parameters (`-T`) to control SABER behavior:

```bash
# List available domains and tasks
uv run inspect list tasks

# Basic evaluation (server auto-starts and stays running)
uv run inspect eval domains/excytin --model openai/azure/gpt-4

# Build options (mutually exclusive):
# 1. Incremental build - build only missing images (fastest)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T build=true

# 2. Complete rebuild - rebuild all images (clean slate)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T rebuild_all=true

# 3. Selective rebuild - rebuild specific images by prefix
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T rebuild=server
uv run inspect eval domains/cybench --model openai/azure/gpt-4 -T rebuild=labryinth

# Server lifecycle management:
# Keep running (default, faster re-runs)
uv run inspect eval domains/excytin --model openai/azure/gpt-4

# Stop after evaluation
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T stop_saber_after=true

# Task filtering:
# Filter to specific tasks (exact match)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T task_filter=incident_5_task_1

# Filter with glob patterns
uv run inspect eval domains/excytin --model openai/azure/gpt-4 -T task_filter="incident_5_*"

# Custom ports (for running multiple domains):
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T rest_port=9000 \
  -T mcp_port=9001

# Combined options:
uv run inspect eval domains/cybench \
  --model openai/azure/gpt-4 \
  -T rebuild=server \
  -T task_filter="labyrinth_*" \
  -T stop_saber_after=true \
  --limit 5

# Concurrency control:
# --max-connections: Limits concurrent API calls to the LLM (default 10)
#                    Use this to avoid rate limiting from your model provider
# --max-samples:     Limits how many samples/episodes run in parallel (default 8)
#                    Each sample is an independent evaluation episode

# Reduce LLM API concurrency (useful for rate-limited endpoints)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 --max-connections 5

# Run samples sequentially (one at a time)
uv run inspect eval domains/excytin --model openai/azure/gpt-4 --max-samples 1

# Run 4 samples in parallel with 20 concurrent LLM connections
uv run inspect eval domains/excytin --model openai/azure/gpt-4 \
  --max-samples 4 \
  --max-connections 20
```
**Enable detailed logging for debugging:**

The `INSPECT_LOG_LEVEL` environment variable is extremely helpful for debugging SABER evaluations:

```bash
# Enable detailed logging to see server communication, tool calls, and execution details
INSPECT_LOG_LEVEL=info uv run inspect eval domains/excytin --model openai/gpt-4

# Combine with other options for comprehensive debugging
INSPECT_LOG_LEVEL=info uv run inspect eval domains/excytin \
    --model openai/azure/gpt-4.1 \
    --max-samples 12 \
    -T task_filter="incident_*"
```

### Viewing Results

```bash
# Inspect AI provides built-in log viewing
uv run inspect view

# View specific log file
uv run inspect view logs/<timestamp>_excytin_<id>.eval
```

### Configuration Files

#### Domain Manifest (`domains/*/domain.yaml`)

Defines domain infrastructure, images, capabilities, and resources:

```yaml
schemaVersion: "1.0.0"

domain:
  slug: "excytin"
  name: "Excytin Incident Response"
  description: "Cybersecurity incident response scenarios..."
  version: "1.0.0"

images:
  server:
    tag: "saber/excytin/server:latest"
    dockerfile: "docker/Dockerfile.server"
  sandbox:
    tag: "saber/excytin/sandbox:latest"
    dockerfile: "docker/Dockerfile.sandbox"

ports:
  rest: { container: 8000, public: false }
  mcp: { container: 8001, public: false }

capabilities:
  networking:
    internet_access: false
  execution:
    docker_socket: true
    privileged: false
```

#### Task Definitions (`domains/*/server/config/tasks/`)

Define individual evaluation scenarios:

```yaml
# global.yaml - Domain-wide defaults
domain: excytin
permanent_environment: incident_5

global_defaults:
  execution_config:
    allowed_executors: [bash, python]
    timeout: 30
  episode_config:
    max_steps: 15
  benchmark_config:
    episode_attempts: 3

# Task-specific YAML files define:
# - Task description and context
# - Evaluation criteria
# - Subtask checkpoints
# - Environment requirements
```

---

## Advanced Topics

### Building Custom Domains

1. Create domain directory structure:
```bash
mkdir -p domains/my_domain/{server,client,docker}
```

2. Create `domain.yaml` manifest following the schema
3. Define tasks in `server/config/tasks/`
4. Create Dockerfiles in `docker/`
5. Configure client in `client/saber.yaml`

See [Domain Development Guide](docs/DOMAIN_DEVELOPMENT.md)

### Docker Image Issues

```bash
# Rebuild images from scratch
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T rebuild_all=true

# Check image existence
docker images | grep saber/excytin
```

### Service Health Checks

```bash
# Check running containers
docker ps -a | grep saber

# View server logs
docker logs saber-excytin-server

# Check server health
curl http://localhost:8000/health
```
