---
name: inspect-eval-log-analysis
description: Guide for parsing and analyzing inspect_ai .eval log files. Use this when asked to interpret eval results, extract tool calls, find scores, or investigate agent behavior from .eval logs.
---

To parse and analyze inspect_ai `.eval` log files, follow this process:

## 1. Understanding the `.eval` File Format

`.eval` files are **ZIP archives** (not plain text). They contain structured JSON:

```
<hash>.eval (ZIP)
├── header.json                    # Eval metadata
├── _journal/
│   ├── start.json                 # Eval config, plan, model info
│   └── summaries/
│       └── 1.json                 # Per-epoch summary
├── samples/
│   └── <task_id>_epoch_1.json     # Full sample data per task
├── summaries.json                 # Aggregated score summaries
└── reductions.json                # Score reduction results
```

**Never try to read `.eval` files as plain text.** Always use `zipfile`:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    print(zf.namelist())  # See all files inside
```

## 2. Extract Sample Data (Messages, Tool Calls, Scores)

The richest data is in the `samples/` JSON files. Each sample contains the full conversation:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    for name in zf.namelist():
        if not name.startswith("samples/"):
            continue
        sample = json.loads(zf.read(name))

        # Key fields in a sample:
        # sample["id"]         — task ID
        # sample["messages"]   — full message history (list of dicts)
        # sample["scores"]     — dict of scorer_name → score result
        # sample["metadata"]   — task metadata
```

## 3. Analyze Tool Calls from Messages

Tool calls are embedded in assistant messages. The structure varies slightly between Completions API and Responses API, but inspect_ai normalizes them:

```python
import json, zipfile

def extract_tool_calls(eval_path):
    """Extract all tool calls from an eval log."""
    results = []
    with zipfile.ZipFile(eval_path, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("samples/"):
                continue
            sample = json.loads(zf.read(name))
            for msg in sample.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                for tc in msg.get("tool_calls", []):
                    if not isinstance(tc, dict):
                        continue
                    results.append({
                        "id": tc.get("id"),
                        "function": tc.get("function"),
                        "arguments": tc.get("arguments", {}),
                        "type": tc.get("type"),
                    })
    return results

# Usage
calls = extract_tool_calls("logs/<file>.eval")
for c in calls:
    fn = c["function"]
    args = c["arguments"]
    if isinstance(args, dict):
        cmd = args.get("cmd", args.get("code", ""))
    print(f"{fn}: {cmd[:80]}")
```

## 4. Analyze Scores

Scores are stored in the `scores` field of each sample:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    for name in zf.namelist():
        if not name.startswith("samples/"):
            continue
        sample = json.loads(zf.read(name))
        task_id = sample.get("id", name)
        scores = sample.get("scores", {})
        for scorer_name, score_data in scores.items():
            value = score_data.get("value")
            explanation = score_data.get("explanation", "")
            print(f"{task_id} | {scorer_name}: {value}")
            if explanation:
                print(f"  → {explanation[:200]}")
```

## 5. Scan for Specific Patterns Across Runs

Useful for tracking issues like model garbage output across multiple eval runs:

```python
import json, zipfile, os

log_dir = "logs"
evals = sorted([f for f in os.listdir(log_dir)
                if "<domain>" in f and f.endswith(".eval")])

for logname in evals:
    log_path = os.path.join(log_dir, logname)
    matches = 0
    total = 0
    with zipfile.ZipFile(log_path, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("samples/"):
                continue
            sample = json.loads(zf.read(name))
            for msg in sample.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                for tc in msg.get("tool_calls", []):
                    if not isinstance(tc, dict):
                        continue
                    total += 1
                    args = tc.get("arguments", {})
                    if isinstance(args, dict):
                        cmd = str(args.get("cmd", ""))
                        # Example: detect trailing garbage '}'
                        if cmd.rstrip().endswith("}"):
                            matches += 1
    print(f"{logname}: {matches}/{total} matched")
```

## 6. Extract the Model Call Details

For deeper debugging, the `_journal/start.json` contains the eval plan and model configuration:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    start = json.loads(zf.read("_journal/start.json"))

    # Eval metadata
    eval_info = start.get("eval", {})
    print(f"Model: {eval_info.get('model')}")
    print(f"Dataset: {eval_info.get('dataset', {}).get('name')}")
    print(f"Created: {eval_info.get('created')}")

    # Plan details
    plan = start.get("plan", {})
    print(f"Solver: {plan.get('solver', {}).get('name')}")
```

## 7. Read the Aggregated Summaries

For a quick overview without parsing individual samples:

```python
import json, zipfile

with zipfile.ZipFile("logs/<file>.eval", "r") as zf:
    summaries = json.loads(zf.read("summaries.json"))
    # summaries contains per-scorer aggregated stats (mean, stderr, etc.)
    print(json.dumps(summaries, indent=2)[:2000])
```

## 8. One-Liner for Quick Score Check

```bash
# List all recent eval logs with scores
python3 -c "
import json, zipfile, os
for f in sorted(os.listdir('logs'))[-5:]:
    if not f.endswith('.eval'): continue
    with zipfile.ZipFile(f'logs/{f}','r') as zf:
        for n in zf.namelist():
            if not n.startswith('samples/'): continue
            s = json.loads(zf.read(n))
            scores = {k: v.get('value') for k, v in s.get('scores', {}).items()}
            print(f'{f}: {s.get(\"id\",\"?\")} → {scores}')
"
```
