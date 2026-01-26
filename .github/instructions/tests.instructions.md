```instructions
---
applyTo: "**/tests/**"
---

# SABER Testing Instructions

## Framework

- **pytest** with markers for test categorization
- **pytest-asyncio** for async test support
- Run: `uv run pytest <path>`

## Test Categories

| Marker | Command | Dependencies |
|--------|---------|--------------|
| Unit (default) | `uv run pytest` | None |
| Integration | `uv run pytest -m integration` | Docker |
| E2E | `uv run pytest -m e2e` | Full stack + SABER server |

## Test Directory Structure

```
tests/
├── conftest.py          # Shared fixtures (mock_docker_validation, task YAMLs)
├── server/              # Server-side component tests
├── client/              # Client-side component tests
├── execution/           # ExecutionManager and sandbox tests
├── evaluation/          # Evaluation strategy tests
├── episodes/            # Episode lifecycle tests
├── benchmarks/          # Task/benchmark configuration tests
├── inspect_ai/          # Inspect AI integration tests
├── integration/         # Integration tests (Docker required)
└── e2e/                 # End-to-end tests (full stack)
```

## Test File Naming

- Test files: `test_<module>.py`
- Test functions: `test_<behavior>()` or `test_<method>_<scenario>()`

## Key Fixtures

The `conftest.py` provides essential fixtures for SABER testing:

```python
# Auto-applied: Mocks Docker validation for all tests
@pytest.fixture(autouse=True)
def mock_docker_validation():
    """Prevents tests from failing when Docker is not installed."""
    with patch('saber.domain.orchestrator.DockerRunner._validate_docker'):
        yield

# Common fixtures
def test_with_task_config(sample_task_yaml, temp_config_dir):
    """Use sample_task_yaml for task configuration testing."""
    # temp_config_dir creates hierarchical task structure
    ...

def test_with_temp_files(tmp_path: Path) -> None:
    """Use tmp_path for temporary file operations."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")
```

## Mocking

```python
from unittest.mock import patch, MagicMock, AsyncMock

def test_external_service() -> None:
    """Mock external services, never make real network calls."""
    with patch("saber.client.client_session.aiohttp.ClientSession") as mock_client:
        mock_client.return_value = MagicMock()
        # test code...

async def test_async_operation() -> None:
    """Use AsyncMock for async methods."""
    with patch("saber.server.session_manager.SessionManager.create_episode", new_callable=AsyncMock) as mock:
        mock.return_value = {"episode_id": "test-123"}
        # async test code...
```

## Conventions

1. **Isolation**: Tests must not depend on external state or other tests
2. **No network calls**: Mock all HTTP/REST/MCP interactions in unit tests
3. **No Docker calls**: Use `mock_docker_validation` fixture (auto-applied)
4. **Type hints**: Annotate test function parameters and return types
5. **Descriptive names**: Test name should describe the scenario being tested
6. **Arrange-Act-Assert**: Structure tests with clear sections

## Coverage

SABER uses `coverage.py` for measuring test coverage:

```bash
# Run tests with coverage collection
uv run coverage run -m pytest tests/ -q

# View terminal coverage report
uv run coverage report

# View coverage for specific module
uv run coverage report --include="src/saber/server/session_manager.py"

# Show missing lines
uv run coverage report --show-missing --include="src/saber/server/*.py"

# Generate HTML report (open htmlcov/index.html)
uv run coverage html

# Generate JSON for programmatic analysis
uv run coverage json
```

### Coverage Targets

| Component | Target |
|-----------|--------|
| Overall project | >80% |
| Core modules (session_manager, execution_manager) | >85% |
| Critical paths (security, evaluation) | >90% |

### Coverage Workflow

```bash
# 1. Run tests with coverage
uv run coverage run -m pytest tests/server/ -q

# 2. Check overall coverage
uv run coverage report

# 3. Identify gaps in specific module
uv run coverage report --show-missing --include="src/saber/server/session_manager.py"

# 4. Generate HTML for detailed line-by-line analysis
uv run coverage html
```

## Test Quality

1. **Provide value**: Each test should verify meaningful behavior
2. **Keep tests readable**: Tests serve as documentation
3. **Fewer, better tests**: A small set of well-designed tests beats many trivial ones
4. **Test async properly**: Use `pytest.mark.asyncio` and `AsyncMock` for async code

```
