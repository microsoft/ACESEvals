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

```bash
# Start a domain and run evaluation (all-in-one command)
uv run saber-domain test excytin \
  --saber-yaml domains/excytin/client/saber.yaml \
  --build

# What this does:
# 1. Validates domain configuration
# 2. Builds missing Docker images (--build = incremental build)
#    Options: --build (missing only), --rebuild-all (all), --rebuild <prefix> (specific)
# 3. Starts SABER server + required services
# 4. Runs inspect_ai evaluation with configured agent
# 5. Stops services when complete (with --stop-after flag)
```

## 📚 Available Domains

### 1. Excytin - Incident Response

**Cybersecurity incident response with database forensics.**

```bash
# Quick test run
uv run saber-domain test excytin \
  --build
```

**Capabilities:**
- Digital forensics investigation of compromised systems
- SQL-based analysis of security logs and artifacts
- Threat actor attribution and IOC extraction
- Multi-table database correlation

---

### 2. CyBench - CTF Challenges

**Web application penetration testing and CTF scenarios.**

```bash
# Quick test run
uv run saber-domain test cybench \
  --build
```

**Capabilities:**
- Web application vulnerability assessment
- SQL injection and XSS exploitation
- Authentication bypass techniques
- Network reconnaissance and enumeration

---

## 🛠️ Development Workflow

### Domain CLI Commands

The `saber-domain` CLI provides comprehensive domain management:

```bash
# List available domains
uv run saber-domain list --verbose

# Validate domain configuration
uv run saber-domain validate excytin --verbose

# Build domain images only
uv run saber-domain build excytin

# Build options:
# (default)      - Build only missing images (incremental, fastest)
# --rebuild-all  - Rebuild all images (clean slate)
# --rebuild <prefix> - Rebuild specific images (e.g., server, cookie)

# Start domain services (manual control)
uv run saber-domain start excytin \
  --rest-port 8000 \
  --mcp-port 8001 \
  --log-level DEBUG

# Check domain status
uv run saber-domain status

# Stop domain services
uv run saber-domain stop excytin

# Test domain (automated: validate + build/rebuild + start + eval + optional stop)
uv run saber-domain test excytin \
  --saber-yaml domains/excytin/client/saber.yaml \
  --build \
  --stop-after  # Stop services after evaluation

# Build options for test command:
# --build        - Build only missing images (incremental, fastest)
# --rebuild-all  - Rebuild all images before testing
# --rebuild <prefix> - Rebuild specific images (e.g., --rebuild server)
```

### Manual Evaluation Workflow

For more control over the evaluation process:

```bash
# 1. Start domain services
uv run saber-domain start excytin --build

# 2. Run evaluation from client config
uv run python -m saber.client run \
  --config domains/excytin/client/saber.yaml

# 3. View results
uv run python -m saber.client inspect view \
  --log-dir logs/client-logs \
  --host 0.0.0.0 \
  --port 7575

# 4. Stop services when done
uv run saber-domain stop excytin
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

#### Client Configuration (`domains/*/client/saber.yaml`)

Configures agent behavior and evaluation parameters:

```yaml
# Server connection (auto-hydrated by saber-domain test)
server:
  mode: auto  # URLs injected at runtime
  client_id: "saber-client"

# Task selection
tasks:
  task_ids: ["incident_5_task_1"]  # Or ["*"] for all tasks

# Agent configuration
agents:
  - id: "inspect_react"
    model: "openai/azure/gpt-4.1"
    tasks: ["incident_5_task_1"]

# Execution settings
log_level: "INFO"
max_parallel_tasks: 2
container_timeout: 300
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

See [Domain Development Guide](docs/DOMAIN_DEVELOPMENT.md) *(coming soon)*

### Custom Agent Integration

SABER uses inspect_ai for agent integration. Create custom agents by:

1. Implementing inspect_ai agent interface
2. Configuring in `client/saber.yaml`
3. Registering with agent manager

See [Agent Integration Guide](external/saber/docs/client/README.md)

### Environment Variables

Key environment variables (auto-configured by CLI):

```bash
# LLM Configuration (required in .env)
AZUREAI_OPENAI_API_KEY=your-key-here
AZUREAI_OPENAI_BASE_URL=https://your-endpoint.openai.azure.com
AZUREAI_OPENAI_API_VERSION=2024-12-01-preview

# Domain Configuration (auto-generated by saber-domain CLI)
DOMAIN=excytin
DOMAINS_ROOT=/path/to/oss_saber/domains
SERVER_IMAGE=saber/excytin/server:latest
REST_PORT=8000
MCP_PORT=8001
LOG_LEVEL=INFO
```

---

## 🐛 Troubleshooting

### Port Conflicts

```bash
# Use custom ports
uv run saber-domain start excytin \
  --rest-port 9000 \
  --mcp-port 9001
```

### Docker Image Issues

```bash
# Rebuild images from scratch
uv run saber-domain build excytin

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

**"Domain not found"**
```bash
# Verify domain exists
uv run saber-domain list

# Check domains directory structure
ls -la domains/
```

**"Image not found"**
```bash
# Build domain images
uv run saber-domain build excytin
```

**"Port already in use"**
```bash
# Find process using port
lsof -i :8000

# Use different ports
uv run saber-domain start excytin --rest-port 9000 --mcp-port 9001
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

- **[SABER Framework Documentation](external/saber/README.md)** - Core framework architecture
- **[Domain CLI Reference](external/saber/src/saber/domain/README.md)** - Complete CLI documentation
- **[Client Architecture](external/saber/docs/client/README.md)** - Agent integration patterns
- **[Server Architecture](external/saber/docs/server/)** - Server implementation details

### Architecture Documentation

- **System Overview**: Modern async architecture with inspect_ai integration
- **Client-Server Protocol**: REST API for session management, MCP for tool execution
- **Docker Sandbox**: Secure command execution with allowlist validation
- **Episode Management**: Stateful task execution with resource cleanup

---
