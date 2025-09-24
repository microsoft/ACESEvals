# OSS SABER - Open Source Security Benchmarks for SABER Framework

This repository contains **open source security benchmarks** designed for evaluation with the **SABER (Security Agent Benchmarking and Evaluation Research)** agentic benchmarking framework. These benchmarks test AI agents on realistic cybersecurity tasks including penetration testing, threat hunting, vulnerability assessment, and security analysis.

## Overview

**OSS SABER** is a collection of cybersecurity benchmarks adapted from open source CTF (Capture The Flag) challenges and security frameworks, specifically designed to evaluate autonomous security agents. The framework provides:

- **🎯 Realistic Security Scenarios**: Multi-phase attack chains and defensive workflows
- **🏗️ Modern Architecture**: Docker-based sandboxes with inspect_ai integration
- **📊 Comprehensive Evaluation**: Granular scoring with subtask progression tracking
- **🔄 Fail-Fast Design**: Clear error messages and immediate feedback
- **🛡️ Secure Execution**: Containerized environments with resource limits

### Currently Available Benchmarks

#### **Cybench** - CTF Challenge Collection
- **40 Tasks** from 4 distinct CTF competitions (HackTheBox, Project Sekai, etc.)
- **Challenge Categories**: Web exploitation, cryptography, reverse engineering, binary exploitation, forensics
- **Example Challenge**: `labyrinth_linguist` - Server-Side Template Injection (SSTI) in Java/Velocity
- **Evaluation Style**: Multi-step subtasks with progressive difficulty



# OSS SABER - Open Source Security Benchmarks

This repository contains **open source security benchmarks** designed for evaluation with the **SABER (Security Agent Benchmarking and Evaluation Research)** agentic benchmarking framework. These benchmarks test AI agents on realistic cybersecurity tasks including penetration testing, threat hunting, vulnerability assessment, and security analysis.

## Overview

**OSS SABER** is a collection of cybersecurity benchmarks adapted from open source CTF (Capture The Flag) challenges and security frameworks, specifically designed to evaluate autonomous security agents. The framework provides:

- **🎯 Realistic Security Scenarios**: Multi-phase attack chains and defensive workflows
- **🏗️ Modern Architecture**: Docker-based sandboxes with inspect_ai integration
- **📊 Comprehensive Evaluation**: Granular scoring with subtask progression tracking
- **🔄 Fail-Fast Design**: Clear error messages and immediate feedback
- **🛡️ Secure Execution**: Containerized environments with resource limits

### Currently Available Benchmarks

#### **Cybench** - CTF Challenge Collection
- **40 Tasks** from 4 distinct CTF competitions (HackTheBox, Project Sekai, etc.)
- **Challenge Categories**: Web exploitation, cryptography, reverse engineering, binary exploitation, forensics
- **Example Challenge**: `labyrinth_linguist` - Server-Side Template Injection (SSTI) in Java/Velocity
- **Evaluation Style**: Multi-step subtasks with progressive difficulty

## Installation

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

### Install uv

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env  # Add uv to PATH
```

### Install project dependencies

```bash
# Initialize git submodules (required for SABER framework)
git submodule update --init --recursive

# Install dependencies
uv sync

# Install with development dependencies  
uv sync --all-extras
```

### Build Docker Images

```bash
# Build SABER framework images
cd external/saber
./scripts/build-images.sh

# Build cybench-specific images
cd ../../cybench/docker
./build-images.sh
```

## Quick Start

### Running Cybench Benchmarks

```bash
# Start the cybench environment
cd cybench
docker compose up -d

# Run a benchmark evaluation
cd client
./run_saber.sh --verbose
```

### Configuration

The main configuration is in `cybench/client/saber.yaml`:

```yaml
# Model configuration
model: "openai/azure/gpt-4.1"

# Server configuration
server:
  rest_url: "http://saber-cybench-server:8000"
  mcp_url: "http://saber-cybench-server:8001"

# Task configuration
tasks:
  task_ids: ["labyrinth_linguist_task_hard"]

# Agent configuration
agent:
  id: "inspect_react"
  debug_mode: false
```

## Architecture

The system implements a modern distributed architecture:

```
┌─────────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│   SABER Client      │    │   SABER Server      │    │   Docker Sandbox │
│                     │    │                     │    │   Environment    │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │    │ ┌──────────────┐ │
│ │ inspect_ai      │ │    │ │ SessionManager  │ │    │ │ Victim       │ │
│ │ Integration     │ │    │ │                 │ │    │ │ Container    │ │
│ └─────────────────┘ │    │ └─────────────────┘ │    │ │ (Challenge)  │ │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │    │ └──────────────┘ │
│ │ ClientSession   │◄────┤ │ REST API        │ │    │ ┌──────────────┐ │
│ │ Manager         │ │    │ │ (FastAPI)       │ │    │ │ Agent        │ │
│ └─────────────────┘ │    │ └─────────────────┘ │    │ │ Sandbox      │ │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │    │ │ Container    │ │
│ │ MCP Client      │◄────┤ │ MCP API         │ │    │ └──────────────┘ │
│ │ (FastMCP)       │ │    │ │ (FastMCP)       │ │    └──────────────────┘
│ └─────────────────┘ │    │ └─────────────────┘ │
└─────────────────────┘    └─────────────────────┘
        │                            │
        └── REST + MCP Protocols ────┘
```

### Key Components

- **SABER Framework**: Modern async architecture with inspect_ai integration
- **Docker Sandboxes**: Isolated execution environments with security tools
- **Challenge Adaptations**: OSS benchmarks converted to SABER format
- **Evaluation Engine**: Multi-step subtask tracking with static criteria

## Available Benchmarks

### Cybench Collection

Located in `external/cybench/benchmark/`:

- **Web Exploitation**: SQL injection, XSS, template injection
- **Cryptography**: Encryption/decryption challenges
- **Reverse Engineering**: Binary analysis and exploitation
- **Binary Exploitation**: Memory corruption and privilege escalation
- **Forensics**: Digital investigation and analysis
- **Miscellaneous**: Various security challenges

### Example: Labyrinth Linguist

A Server-Side Template Injection challenge with 6 progressive subtasks:

1. **Contextualize**: Identify the programming language (Java)
2. **Templating Engine**: Discover Velocity templating engine
3. **Attack Vector**: Recognize SSTI vulnerability
4. **Template File**: Locate injection point
5. **Flag Location**: Find flag file path
6. **Exploitation**: Craft payload and extract flag

## Development

### Adding New Benchmarks

1. **Create Challenge Structure**: Place challenge files in appropriate directories
2. **Convert to SABER Format**: Use conversion scripts to adapt challenges
3. **Define Task Configuration**: Create YAML task definitions
4. **Setup Docker Environment**: Create sandbox and victim containers
5. **Test Evaluation**: Verify scoring and subtask progression

### Project Structure

```
oss_saber/
├── external/
│   ├── saber/              # SABER framework core
│   └── cybench/            # Original cybench benchmark
├── cybench/                # SABER-adapted cybench
│   ├── client/             # Client configuration and scripts
│   ├── server/             # Server configuration and tasks
│   ├── docker/             # Docker images and challenges
│   └── scripts/            # Conversion and utility scripts
└── reference/              # Documentation and examples
```

## Contributing

1. **Benchmark Submissions**: Follow existing patterns for challenge adaptation
2. **Code Quality**: Use type hints, fail-fast design, and comprehensive testing
3. **Documentation**: Include clear setup instructions and evaluation criteria
4. **Security**: Ensure proper containerization and resource limits


## Support

For questions and support:
- Review existing challenge implementations in `cybench/docker/challenges/`
- Check configuration examples in `cybench/server/config/`
- Examine conversion scripts in `cybench/scripts/`
