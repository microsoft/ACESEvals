---
name: inspect-eval-debugging
description: Guide for debugging inspect_ai evaluation failures, score issues, and model behavior. Use this when eval results are unexpected, scores are wrong, scoring fails, or model output appears corrupted.
---

To debug inspect_ai evaluation issues in SABER, follow this systematic process:

## 1. Triage: Identify the Failure Category

Check the eval summary output. Common categories:

| Symptom | Likely Cause | Section |
|---------|-------------|---------|
| Score is `nan` for all scorers | Agent never reached scoring (sandbox error, tool failure) | §2 |
| Score is `0.0` but expected higher | Scorer ran but agent's work was incorrect or scorer has a bug | §3 |
| Score differs across runs of same model | Non-deterministic model behavior | §4 |
| Eval crashes with traceback | Code error in domain scoring/tools or inspect_ai | §5 |
| `0/0 trailing brace` or garbage in tool args | Model produces malformed tool call arguments | §4 |
| Docker/sandbox errors | Container issues | §6 |

## 2. Debug Agent Behavior (Score is `nan` or Unexpected)

Parse the eval log to see exactly what the agent did:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    for name in zf.namelist():
        if not name.startswith("samples/"):
            continue
        sample = json.loads(zf.read(name))

        print(f"Task: {sample.get('id')}")
        print(f"Scores: {sample.get('scores', {}).keys()}")

        # Walk through the conversation to see agent actions
        for i, msg in enumerate(sample.get("messages", [])):
            role = msg.get("role", "?")
            if role == "assistant":
                # Check for tool calls
                tcs = msg.get("tool_calls", [])
                if tcs:
                    for tc in tcs:
                        fn = tc.get("function", "?")
                        args = tc.get("arguments", {})
                        cmd = args.get("cmd", "") if isinstance(args, dict) else str(args)[:100]
                        print(f"  [{i}] TOOL: {fn}({cmd[:80]})")
                else:
                    content = msg.get("content", "")
                    text = content if isinstance(content, str) else str(content)[:100]
                    print(f"  [{i}] ASSISTANT: {text[:100]}")
            elif role == "tool":
                text = msg.get("content", "")[:80]
                print(f"  [{i}] TOOL_RESULT: {text}")
```

## 3. Debug Scorer Issues (Score is 0.0 Unexpectedly)

### 3a. Check the score explanation

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    for name in zf.namelist():
        if not name.startswith("samples/"):
            continue
        sample = json.loads(zf.read(name))
        for scorer_name, score_data in sample.get("scores", {}).items():
            print(f"--- {scorer_name} ---")
            print(f"  value: {score_data.get('value')}")
            print(f"  explanation: {score_data.get('explanation', 'none')[:500]}")
            metadata = score_data.get("metadata", {})
            if metadata:
                print(f"  metadata: {json.dumps(metadata, indent=2)[:300]}")
```

### 3b. Test the scorer in isolation

Write a standalone test or script that calls the scorer directly against a known-good input. For example, to test a patch-verify scorer:

```bash
# Enter the sandbox container manually
docker exec -it <container_id> bash

# Verify the patch applies
cd /workspace/source
patch -p1 --dry-run < /submit/patches/patch.diff

# Run the build
bash build.sh

# Run POVs manually
./build/fuzz_harness /workspace/povs/pov_0.blob
```

### 3c. Add debug logging to scorer code

Domain scoring code lives in `domains/<domain>/scoring/`. Add `logger.info()` or `logger.warning()` calls and run with `INSPECT_LOG_LEVEL=info`:

```bash
INSPECT_LOG_LEVEL=info uv run inspect eval domains/<domain> --model <model> --display plain --limit 1
```

Domain loggers use the `saber.domains.*` namespace and inherit inspect_ai's log handling automatically.

## 4. Debug Model Behavior (Non-Deterministic Issues)

### 4a. Scan multiple eval logs for patterns

```python
import json, zipfile, os

log_dir = "logs"
for f in sorted(os.listdir(log_dir)):
    if not f.endswith(".eval") or "<domain>" not in f:
        continue
    issues = []
    total = 0
    with zipfile.ZipFile(f"{log_dir}/{f}", "r") as zf:
        for name in zf.namelist():
            if not name.startswith("samples/"):
                continue
            sample = json.loads(zf.read(name))
            for msg in sample.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                for tc in msg.get("tool_calls", []):
                    total += 1
                    args = tc.get("arguments", {})
                    if isinstance(args, dict):
                        cmd = str(args.get("cmd", ""))
                        # Check for trailing garbage brace
                        if cmd.rstrip().endswith("}"):
                            issues.append(cmd[-60:])
    if issues:
        print(f"*** {f}: {len(issues)}/{total} issues ***")
        for ex in issues[:3]:
            print(f"    {ex!r}")
```

### 4b. Known model quirks

- **gpt-5.2 trailing `}`**: Sporadically appends `}` to bash commands in tool call arguments. This is model-generated garbage — it appears in the raw API response from the OpenAI SDK, before any inspect_ai processing. Frequency varies: 0-26% of tool calls per run.
- **gpt-5 series uses Responses API**: `openai.responses.create()` instead of `client.chat.completions.create()`. The code path in inspect_ai is completely different — see §5.
- **Reasoning tokens**: Models like o1/o3 and gpt-5 produce reasoning tokens that don't appear in visible content but consume output token budget.

## 5. Debug inspect_ai Code Path Issues

### 5a. Determine which API path a model uses

```python
# Check in the provider code:
# external/inspect_ai/src/inspect_ai/model/_providers/openai.py

# gpt-5 series: responses_api = True (automatic)
# o-series (except o1-early): responses_api = True
# codex models: responses_api = True
# Everything else: Completions API (default)
```

**Key code paths:**

| API | Entry Point | Tool Call Processing |
|-----|-------------|---------------------|
| Completions | `OpenAICompatibleAPI.generate()` → `_generate_completion()` | `chat_tool_calls_from_openai()` in `_openai.py` |
| Responses | `OpenAIAPI.generate()` → `generate_responses()` | `openai_responses_chat_choices()` in `_openai_responses.py` |

### 5b. Find which file Python actually imports

**Critical**: `inspect_ai` may be installed from a git URL, NOT as an editable install from `external/`. Editing files in `external/inspect_ai/src/` may have NO EFFECT:

```bash
# Check which file is loaded
uv run python -c "import inspect_ai.model._providers.openai_responses as m; print(m.__file__)"

# If it prints .venv/lib/.../site-packages/..., edit THAT file, not external/
```

### 5c. Add debug logging to inspect_ai internals

Since inspect_ai uses a custom `LogHandler` that can suppress standard logger output, the most reliable debugging approach is to **write directly to a file**:

```python
# Add this temporarily at the injection point:
with open("/tmp/debug_output.log", "a") as _dbg:
    _dbg.write(f"DEBUG: variable={value!r}\n")
    _dbg.flush()
```

**Do NOT rely on** `logger.warning()` or `sys.stderr.write()` — inspect_ai's Rich console and custom LogHandler can swallow these. File I/O always works.

After editing files in `.venv/lib/.../site-packages/`, always clear bytecode caches:

```bash
find .venv/lib/python3.11/site-packages/inspect_ai/model -name '__pycache__' -exec rm -rf {} +
```

### 5d. Using INSPECT_PY_LOGGER_FILE

An alternative to file-based debug prints:

```bash
INSPECT_PY_LOGGER_FILE=/tmp/inspect_debug.log uv run inspect eval domains/<domain> --model <model> --display plain --limit 1
```

This captures Python logger output to a file, but only for loggers in the `inspect_ai` namespace.

## 6. Debug Docker/Sandbox Issues

### 6a. Check container status during eval

```bash
# List running containers
docker ps --filter "name=saber"

# Check container logs
docker logs <container_id> 2>&1 | tail -50

# Enter container for manual inspection
docker exec -it <container_id> bash
```

### 6b. Verify sandbox compose file

```bash
# Validate compose syntax
docker compose -f domains/<domain>/compose/sandbox.compose.yml config

# Check environment variables are set
docker compose -f domains/<domain>/compose/sandbox.compose.yml config | grep -A5 environment
```

### 6c. Rebuild images from scratch

```bash
# Full rebuild (ignoring cache)
docker build --no-cache -t saber/<domain>/sandbox:latest -f domains/<domain>/docker/Dockerfile.sandbox domains/<domain>/

# Or via saber CLI
uv run saber build <domain> --rebuild
```

## 7. Comparing Results Across Models

When the same task produces different scores on different models, use this workflow:

1. **Run both models** on the same task with `--limit 1`:
   ```bash
   uv run inspect eval domains/<domain> --model openai/azure/gpt-4.1 --display plain --limit 1 -T task_filter="<task>"
   uv run inspect eval domains/<domain> --model openai/azure/gpt-5.2 --display plain --limit 1 -T task_filter="<task>"
   ```

2. **Extract and compare tool call sequences** from both eval logs (see §2)

3. **Diff the agent strategies**: Look at which commands each model ran, in what order, and where they diverged

4. **Check for model-specific issues**: Some models produce different JSON formatting, escape sequences, or garbage characters in tool call arguments

## 8. Rapid Iteration Checklist

When debugging a failing eval:

1. [ ] Run with `--limit 1` and `task_filter` to isolate
2. [ ] Check the score explanation in the `.eval` ZIP
3. [ ] Walk the agent's tool call sequence
4. [ ] If scorer issue: add logging to `domains/<domain>/scoring/`, run with `INSPECT_LOG_LEVEL=info`
5. [ ] If model issue: scan multiple runs for the pattern
6. [ ] If inspect_ai issue: find the actual imported file (`__file__`), add file-based debug logging, clear `__pycache__`
7. [ ] If Docker issue: check container status, enter container manually
8. [ ] After fixing: re-run eval, verify score changed as expected
9. [ ] Clean up all debug logging before committing
