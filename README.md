# OSS SABER - Open Source Security Agent Benchmarking

**Production-ready security benchmarking domains for agentic workflow evaluation.**

SABER is a modern distributed system for benchmarking AI security agents using the inspect_ai framework with Model Context Protocol (MCP) integration. This repository contains open-source security domains for penetration testing, incident response, and multi-agent coordination scenarios.

---

## 🎯 What is SABER?

SABER evaluates autonomous AI agents against realistic cybersecurity challenges:

- **🔐 Security Domains**: Penetration testing, incident response, threat hunting
- **🤖 Agent Evaluation**: Multi-step workflows with real-world security tools
- **🐳 Isolated Execution**: Docker sandbox environments with secure command validation
- **📊 MCP Integration**: Industry-standard Model Context Protocol for tool communication
- **⚡ Modern Architecture**: Async Python with fail-fast design and type safety

### Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        OSS SABER                               │
│  Open Source Security Agent Benchmarking & Evaluation         │
└────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼
        │                     │
┌───────▼───────┐    ┌────────▼────────┐
│    Excytin    │    │    CyBench      │
│   Incident    │    │   CTF/Pentest   │
│   Response    │    │   Challenges    │
└───────────────┘    └─────────────────┘

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

## 🚀 Quick Start

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

```bash
# Quick evaluation
uv run inspect eval domains/excytin --model openai/azure/gpt-4

# With image build and cleanup
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T build=true \
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
uv run inspect eval domains/cybench --model openai/azure/gpt-4 -T rebuild=cookie

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
```
**Enable detailed logging for debugging:**

The `INSPECT_LOG_LEVEL` environment variable is extremely helpful for debugging SABER evaluations:

```bash
# Enable detailed logging to see server communication, tool calls, and execution details
INSPECT_LOG_LEVEL=info uv run inspect eval domains/excytin --model openai/gpt-4

# Combine with other options for comprehensive debugging
INSPECT_LOG_LEVEL=info uv run inspect eval domains/excytin \
    --model openai/azure/gpt-4.1 \
    -T max_concurrent_episodes=12 \
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

## 🔧 Advanced Topics

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

### Environment Variables

Key environment variables (auto-configured by CLI):

```bash
# LLM Configuration (required in .env)
AZUREAI_OPENAI_API_KEY=your-key-here
AZUREAI_OPENAI_BASE_URL=https://your-endpoint.openai.azure.com
AZUREAI_OPENAI_API_VERSION=2024-12-01-preview

# Domain Configuration (auto-configured by inspect_ai task)
# These are set via -T task parameters:
#   -T rest_port=8000
#   -T mcp_port=8001
#   -T log_level=INFO
# No environment variables needed for domain-specific settings
```

---

## 🐛 Troubleshooting

### Port Conflicts

```bash
# Use custom ports
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T rest_port=9000 \
  -T mcp_port=9001
```

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

### Agent Evaluation Issues

```bash
# Enable debug logging
# Edit domains/*/client/saber.yaml:
log_level: "DEBUG"

# Check agent logs
tail -f logs/client-logs/*/saber_client.log

# Verify MCP connection
curl http://localhost:8001/tools  # Should list available tools
```

### Common Errors

**"Domain not found" or "Task not found"**
```bash
# List available tasks
uv run inspect list tasks

# Check domains directory structure
ls -la domains/
```

**"Image not found"**
```bash
# Build domain images
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T build=true
```

**"Port already in use"**
```bash
# Find process using port
lsof -i :8000

# Use different ports
uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4 \
  -T rest_port=9000 \
  -T mcp_port=9001
```

**"Azure OpenAI authentication failed"**
```bash
# Verify credentials in .env
cat .env

# Test connection
uv run python -c "
from openai import AzureOpenAI
import os
client = AzureOpenAI(
    api_key=os.getenv('AZUREAI_OPENAI_API_KEY'),
    api_version=os.getenv('AZUREAI_OPENAI_API_VERSION'),
    azure_endpoint=os.getenv('AZUREAI_OPENAI_BASE_URL')
)
print('✓ Connection successful')
"
```

---

## 📖 Documentation

### Quick Links

- **[SABER Framework Documentation](external/saber/README.md)** - Core framework architecture and inspect_ai integration
- **[Excytin Demo Domain](external/saber/domains/excytin_demo/README.md)** - Example domain with incident response tasks
- **[Inspect AI Sandboxing Documentation](external/inspect_ai/docs/sandboxing.qmd)** - SABER sandbox configuration guide
- **[Server Architecture](external/saber/docs/server/)** - Server implementation details

### Architecture Documentation

- **System Overview**: Modern async architecture with inspect_ai integration
- **Client-Server Protocol**: REST API for session management, MCP for tool execution
- **Docker Sandbox**: Secure command execution with allowlist validation
- **Episode Management**: Stateful task execution with resource cleanup

---
