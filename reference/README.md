# SABER - Security Agent Benchmarking and Evaluation Research

A modern distributed system for benchmarking agentic workflows in cybersecurity domains using **inspect_ai integration** with **Model Context Protocol (MCP)** for industry-standard agent evaluation.

## Features

### Modern Agent Integration
- **🔥 inspect_ai Native**: Direct Python API integration for seamless agent evaluation
- **📊 MCP Protocol**: Industry-standard Model Context Protocol for tool communication  
- **⚡ Fail-Fast Design**: Immediate error detection with clear, actionable messages
- **🎯 Type Safety**: Strict Pydantic models throughout with compile-time validation
- **🔄 Async Lifecycle**: Context manager patterns for guaranteed resource cleanup

### Security Domain Benchmarking
- **🎯 Multi-Step Workflows**: Complex security tasks (penetration testing, malware analysis, threat hunting)
- **📈 Session Management**: Stateful execution with episode-based progress tracking
- **🔐 Secure Execution**: Docker sandbox with security-first command validation
- **📋 YAML Configuration**: Declarative benchmark and task definitions
- **📊 Comprehensive Evaluation**: Action tracking and trajectory analysis

## Architecture Overview

SABER implements a **modern dual-protocol architecture** optimized for security agent benchmarking:

```
┌─────────────────────┐    ┌─────────────────────┐
│   SABER Client      │    │   SABER Server      │
│                     │    │                     │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │ inspect_ai      │ │    │ │ SessionManager  │ │
│ │ Integration     │ │    │ │                 │ │
│ └─────────────────┘ │    │ └─────────────────┘ │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │ ClientSession   │◄────┤ │ SessionRestAPI  │ │
│ │ Manager         │ │    │ │ (FastAPI)       │ │
│ └─────────────────┘ │    │ └─────────────────┘ │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │ MCP Client      │◄────┤ │ SessionMCPAPI   │ │
│ │ (FastMCP)       │ │    │ │ (FastMCP)       │ │
│ └─────────────────┘ │    │ └─────────────────┘ │
└─────────────────────┘    └─────────────────────┘
        │                            │
        └── REST + MCP Protocols ────┘
```

### Key Components

#### Client Side
- **🎯 run_saber_eval_async**: Main inspect_ai compatible entry point
- **⚡ SABEREvaluationOrchestrator**: Async context manager for component lifecycle
- **🔗 ClientSessionManager**: Unified API layer for REST + MCP communication
- **🤖 AgentManager**: Agent discovery and lifecycle management
- **📊 DatasetManager**: SABER dataset creation from server tasks

#### Server Side  
- **🎯 SessionManager**: Central orchestrator with multi-session support
- **🌐 SessionRestAPI**: FastAPI server for session and episode management
- **🔧 SessionMCPAPI**: FastMCP server for tool discovery and execution
- **📋 BenchmarkManager**: YAML-based task and benchmark configuration
- **🐳 ExecutionManager**: Docker sandbox execution with security validation

### Design Principles

Following **SABER best practices**:

- ✅ **FAIL FAST**: Upfront validation with clear error messages
- ✅ **NO BACKWARDS COMPATIBILITY**: Clean modern API without legacy baggage  
- ✅ **TYPE SAFETY**: Strict Pydantic models throughout
- ✅ **NO DEFENSIVE PROGRAMMING**: Hard failures instead of silent fallbacks
- ✅ **SEPARATION OF CONCERNS**: Clean component boundaries with async patterns

For detailed architecture documentation, see [docs/README.md](docs/README.md).

## Quick Start

### Prerequisites

- **Python 3.10+** with modern async/await support
- **Docker** for sandbox execution environments  
- **Git** for repository management

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd SABER
   ```

2. **Install uv package manager:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.local/bin/env  # Add uv to PATH
   ```

3. **Install dependencies (choose your pathway):**

   **Pathway 1: Local Development with External Directory (Default & Recommended)**
   ```bash
   # Initialize git submodule (usually already done)
   git submodule update --init --recursive
   
   # Install with local inspect_ai (default configuration)
   uv sync --all-extras
   ```

   **Pathway 2: ADO Repository Installation**  
   ```bash
   # Edit pyproject.toml to use ADO repository:
   # Uncomment: inspect-ai = { git = "https://MSECAIModels@dev.azure.com/..." }
   # Comment: inspect-ai = { path = "./external/inspect_ai" }
   
   # Install with ADO repository source
   uv sync --all-extras
   ```

4. **Verify installation:**
   ```bash
   uv run python -c "from saber.client.inspect_ai import run_saber_eval_async; print('✅ SABER installed')"
   ```

## Module Documentation

### Client Documentation
- **[Client Architecture](docs/client/README.md)**: inspect_ai integration patterns and MCP client usage
- **[API Reference](src/saber/client/)**: Type-safe client components and configuration models

### Server Documentation  
- **[Server Architecture](docs/server/)**: SessionManager, REST API, and MCP API implementation
- **[Benchmark Management](src/saber/server/benchmarks/)**: YAML-driven task and benchmark configuration
- **[Command Registry](src/saber/server/execution/)**: Secure Docker sandbox execution framework

### System Documentation
- **[System Architecture](docs/README.md)**: Complete system overview and integration patterns
- **[Domain Examples](domains/)**: Ready-to-use security domain implementations

## Development

### Code Quality & Testing

SABER follows strict quality standards with fail-fast validation:

```bash
# Run full test suite with coverage
uv run pytest --cov=src

# Type checking (strict mode)
uv run mypy src/

# Code formatting (no configuration needed)
uv run black src/

# Import sorting
uv run isort src/

# Linting with security checks  
uv run flake8 src/

# Run all quality checks (recommended)
uv run pre-commit run --all-files
```

### Development Workflow

#### Dependency Management

**Switching Between Installation Pathways:**

```bash
# To switch to ADO repository (inspect_ai from MSEC ADO):
# 1. Edit pyproject.toml [tool.uv.sources] section:
#    Uncomment:   inspect-ai = { git = "https://MSECAIModels@dev.azure.com/..." }
#    Comment out: inspect-ai = { path = "./external/inspect_ai" }

# 2. Reinstall with ADO source
uv sync --all-extras

# To switch back to local development (default):
# 1. Initialize submodule if not already done
git submodule update --init --recursive

# 2. Edit pyproject.toml [tool.uv.sources] section:
#    Comment out: inspect-ai = { git = "https://MSECAIModels@dev.azure.com/..." }
#    Uncomment:   inspect-ai = { path = "./external/inspect_ai" }

# 3. Reinstall with local source
uv sync --all-extras
```

#### Standard Development Process

1. **Set up development environment:**
   ```bash
   uv sync --all-extras
   uv run pre-commit install
   ```

2. **Create feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make changes with fail-fast validation:**
   ```bash
   # Edit code with type hints and Pydantic models
   # Run tests frequently for immediate feedback
   uv run pytest tests/your_test.py -v
   ```

4. **Validate before commit:**
   ```bash
   uv run pre-commit run --all-files
   uv run pytest --cov=src
   ```

5. **Submit pull request with clear description**

### Architecture Guidelines

#### Type Safety (Required)
```python
from typing import Optional
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    """Fail-fast configuration with strict validation."""
    name: str = Field(..., description="Agent identifier")
    timeout: Optional[int] = Field(default=300, ge=1)
    
    class Config:
        extra = "forbid"  # Fail on unknown fields
```

#### Async Context Managers (Required)
```python
async def process_episodes():
    async with SABEREvaluationOrchestrator(config) as orchestrator:
        # Guaranteed cleanup even on exceptions
        tasks = await orchestrator.discover_tasks()
        return await orchestrator.run_evaluation(tasks)
```

#### Error Handling (No Silent Failures)
```python
def validate_config(config: dict) -> SABERConfig:
    try:
        return SABERConfig(**config)
    except ValidationError as e:
        # Clear, actionable error message
        raise ConfigurationValidationError(
            f"Invalid SABER configuration: {e}",
            details={"validation_errors": e.errors()},
            suggestion="Check configuration against SABERConfig schema"
        ) from e
```

### Contributing Guidelines

- ✅ **Type hints required** for all functions and methods
- ✅ **Pydantic models** for all configuration and data structures  
- ✅ **Async context managers** for resource management
- ✅ **Fail-fast validation** with clear error messages
- ✅ **No backwards compatibility** - break things to improve design
- ✅ **No defensive programming** - fail clearly instead of silently
- ✅ **Tests required** for new functionality
- ✅ **Documentation updates** for API changes

## SABER vs Alternatives

### Why SABER?

| Feature | SABER | Traditional Frameworks |
|---------|-------|----------------------|
| **Agent Integration** | Native inspect_ai + MCP | Custom adapters |
| **Type Safety** | Strict Pydantic models | Runtime validation |
| **Error Handling** | Fail-fast with context | Silent fallbacks |
| **Resource Management** | Async context managers | Manual cleanup |
| **Security Focus** | Docker sandboxing | Basic isolation |
| **Protocol Support** | REST + MCP dual protocol | HTTP only |

### Design Philosophy

SABER prioritizes **software engineering best practices** over backwards compatibility:

- 🚫 **No defensive programming** - Clear failures over silent errors
- 🚫 **No legacy support** - Modern patterns without historical constraints  
- ✅ **Fail-fast validation** - Catch errors at configuration time
- ✅ **Type safety** - Compile-time guarantees via Pydantic
- ✅ **Async patterns** - Proper resource management with context managers
- ✅ **Industry standards** - MCP protocol for tool communication

## Examples

### Domain Implementations

Ready-to-use security domains:

- **[Web Application Penetration Testing](domains/webapp_pentest/)**: SQL injection, XSS, authentication bypass
- **[Malware Analysis](domains/excytin_demo/)**: Dynamic analysis, sandbox execution, threat intelligence

---

**SABER Development Team** | [Documentation](docs/) | [Examples](examples/) | [Domain Implementations](domains/)
