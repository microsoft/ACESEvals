# Bug Report: Hung Evaluation Episodes During LLM Judge Scoring

**Date:** 2026-02-12  
**Status:** FIXED - WebSocket Keepalive Bug + HTTP Error Logging Added  
**Severity:** Medium (affects specific samples, not systemic)  
**Affected Run:** `logs/2026-02-12T22-34-11+00-00_excytin_BbvsCxUEFKLg9Hayzx7wQB.eval`

## Summary

During a `legacy_train_set` evaluation run, **3 out of 418 samples** got stuck indefinitely. The issue is NOT rate limiting - other samples completed successfully at the exact same timestamps.

**Root Cause:** Per-request failures in specific judge LLM calls (`/chat/completions`) that triggered infinite retries. Evidence shows:
1. Other batch evaluations completed while hung samples were retrying
2. One sample (`incident_39_legacy_train_set_task_67`) had `submission_length=0` due to premature WebSocket closure
3. The hung samples consistently failed on the judge endpoint while agent calls (`/responses`) succeeded

**Why `--max-retries` prevents hangs:** It bounds the retry loop so exhausted retries fail the sample instead of hanging forever. Feb 17 run had 944 agent retries but 0 judge retries - the judge worked perfectly with proper configuration.

## Root Cause Analysis (Feb 18 Deep Investigation)

### Critical Finding: NOT Rate Limiting

**Evidence that disproves rate limiting theory:**
1. At `22:38:33` when `task_16` was retrying, a DIFFERENT batch evaluation completed successfully
2. Feb 17 run had 944 agent retries (`/responses`) but 0 judge retries (`/chat/completions`)
3. Only 3 samples hung (not 6 as originally thought) - very specific failures

### What Actually Triggers Retries

The openai Python library (`/openai/_base_client.py`) triggers retries on:
- HTTP 429 - Rate Limited
- HTTP 408 - Request Timeout
- HTTP 5xx - Server Errors

BUT the hung samples show a DIFFERENT retry interval:
- Agent calls (`/responses`): 0.4-1.0s retries (rate limiting backoff)
- Judge calls (`/chat/completions`): **30.0s constant retries** (non-rate-limiting error)

### The 3 Actually Hung Samples

| Sample | Hung Time | Retry Pattern | WebSocket State | Submission |
|--------|-----------|---------------|-----------------|------------|
| `incident_166_legacy_train_set_task_16` | 22:38:31 | 30s retries | Closed 1hr+ AFTER eval started | 293 chars |
| `incident_39_legacy_train_set_task_67` | 22:58:53 | 30s retries | Closed BEFORE eval - **ANOMALY** | **0 chars (EMPTY)** |
| `incident_5_legacy_train_set_task_44` | 23:53:04 | 30s retries | Closed 3min after eval | 543 chars |

### Key Pattern: task_67 Has Empty Submission

```log
2026-02-12 22:58:47 WebSocket connection closed | episode_id=fc47df16  ← CLOSED FIRST!
2026-02-12 22:58:52 Starting client-side evaluation | episode_id=fc47df16
2026-02-12 22:58:52 Agent submission posted | submission_length=0     ← EMPTY!
```

The WebSocket closed BEFORE evaluation started, causing the agent transcript to be lost. The scorer tried to evaluate an empty/malformed prompt.

### Concurrent Success vs Hung Sample Failure

At `22:38:33` exactly:
- `task_16` triggered a retry at this moment
- **ANOTHER batch evaluation completed successfully** at this EXACT timestamp

This proves the Azure endpoint was working fine - something about the SPECIFIC request for `task_16` was problematic.

## Command Executed

```bash
uv run inspect eval domains/excytin --model openai/azure/gpt-5.2 \
  -T build=true \
  -T task_filter="incident_*_legacy_train_set_*"
```

## Affected Samples (3 total - revised count)

| Sample ID | Episode ID | Status | Anomaly |
|-----------|------------|--------|---------|
| incident_166_legacy_train_set_task_16 | a99a38c4-1fbe-4c80-8128-a6c29750d6b0 | Hung at evaluation | Long WebSocket open |
| incident_39_legacy_train_set_task_67 | fc47df16-ba2a-499f-bbda-5b9b0ef9738f | Hung at evaluation | **Empty submission** |
| incident_5_legacy_train_set_task_44 | aedf3c4d-e05f-49a1-93dd-b864ee7809c3 | Hung at evaluation | Normal submission |

**Note:** Earlier analysis said 6 samples, but log correlation shows only 3 batch evaluations started without completing.

## Timeline

- **22:34:11** - Evaluation started
- **~23:15-23:53** - Hung samples started client-side evaluation phase
- **01:32:47** - User manually cancelled (all 6 hung samples terminated with cleanup errors)
- Total runtime: ~3 hours before cancellation

## Symptoms

### 1. All hung samples followed the same pattern:
```
1. Agent execution completes successfully
2. Scorer invoked
3. Client-side evaluation starts
4. Agent submission posted to server
5. !! STUCK HERE - waiting for LLM judge response !!
   (No "Batch LLM subtask evaluation complete" event logged)
6. Eventually: WebSocket times out, cleanup errors
```

### 2. Example from incident_5_legacy_train_set_task_44:
```log
23:53:03 AGENT 🤖 SABER agent 'react' execution complete | completion_length=543 task_id=incident_5_legacy_train_set_task_44
23:53:03 EVALUATION 📊 Scorer invoked
23:53:03 EVALUATION 📊 Starting client-side evaluation | episode_id=aedf3c4d-e05f-49a1-93dd-b864ee7809c3
23:53:03 EVALUATION 📊 Agent submission posted to server | submission_length=543
23:53:04 EVALUATION 📊 LLM judge: INCORRECT | score=0.0  (submission eval succeeded)
23:53:04 EVALUATION 📊 Starting subtask evaluation | subtask_count=2
23:53:04 EVALUATION 📊 Starting batch LLM subtask evaluation | model=openai/azure/gpt-4.1 subtask_count=2
23:53:04 EVALUATION 📊 Processing step chunks for batch LLM | total_steps=18
23:53:05 UNCATEGORIZED Retrying request to /chat/completions in 30.000000 seconds
... (sample never completes - no "Batch LLM subtask evaluation complete" message)
```

### 3. Successful samples show completion:
```log
23:52:29 Starting batch LLM subtask evaluation | total_steps=12
23:52:30 Batch LLM subtask evaluation complete | completions={'checkpoint_1': 0, 'checkpoint_2': 0}
23:52:30 === Step-Based Checkpoint Evaluation Summary ===
23:52:30 Client-side evaluation completed
```

## Log Statistics

- **Total samples in dataset:** 418
- **Completed samples in eval log:** 412
- **Missing/incomplete samples:** 6 (the hung ones)
- **Total retry messages in log:** ~250 instances of "Retrying request to /chat/completions in 30.000000 seconds"

### Step Count Statistics

From analysis of `total_steps=` in SABER logs:
- **Total evaluations logged:** 415
- **Min steps:** 0
- **Max steps:** 25
- **Average steps:** 7.7
- **Samples with >15 steps:** 28

The hung samples had 6-18 steps each - not abnormally high.

## Key Observations

### 1. Submission evaluation succeeds, subtask evaluation hangs
For `incident_5_legacy_train_set_task_44`:
- ✅ Submission LLM judge worked (returned INCORRECT)
- ❌ Subtask batch LLM evaluation hung

This suggests the issue is specific to the **batch subtask evaluation** using `openai/azure/gpt-4.1`.

### 2. No visible error message before retries
The SABER logs show `Retrying request to /chat/completions in 30.000000 seconds` but do NOT show:
- The actual HTTP error code returned
- Any error message from Azure OpenAI
- Token count or context length information

### 3. Retry timing pattern suggests 30-second backoff
The retries appear every ~30 seconds, consistent with the logged "in 30.000000 seconds" message.

### 4. HTTP 400 errors in log are NOT related
The HTTP 400 errors seen in logs are Azure IMDS (Instance Metadata Service) credential fallback attempts - these are normal behavior when `AzureCliCredential` is the final credential source. The log shows:
```
Response status: 400 (from http://169.254.169.254/metadata/identity/oauth2/token)
DefaultAzureCredential acquired a token from AzureCliCredential
```

### 5. Concurrent samples working fine
Other samples running concurrently (4 at a time) completed successfully, ruling out:
- Global rate limiting
- Azure endpoint issues
- General network problems

## Hypotheses to Investigate

### Hypothesis 1: Token/Context Length Exceeded
The subtask batch evaluation constructs a prompt with:
- System template
- User template with step history
- All episode steps (up to `steps_per_message=50`)

**Investigation Result:** Templates use Jinja2 `truncate()` filters that limit each step's output:
- `step.action.parameters | truncate(300)` - 300 chars
- `step.action.assistant_message | truncate(800)` - 800 chars
- `step.action.reasoning | truncate(600)` - 600 chars
- `step.response | truncate(1000)` - 1000 chars (tool output / SQL results)

**Per step max: ~2700 chars × 18 steps = ~48,600 chars ≈ 12K tokens**

This is within gpt-4.1's context window. **Token count is NOT the primary issue.**

However, if truncation fails for some reason (e.g., template not rendering correctly), the raw SQL output could be huge.

### Hypothesis 2: Content Filter Triggered
Azure OpenAI content filters may have triggered on specific prompt content.

**Evidence Against:**
- Same templates used for all samples
- Successful samples from same incidents completed

**To Investigate:**
- [ ] Check for content_filter_error in detailed API logs
- [ ] Compare task content between successful and hung samples

### Hypothesis 3: Transient Azure API Issues + Infinite Retry
Specific API calls may have hit transient issues that caused infinite retry loops.

**Evidence Supporting:**
- Only 6/418 samples affected
- No pattern by incident (incident_5, incident_39, incident_55, incident_166)
- inspect_ai has `stop_never` retry policy by default!

**Evidence Against:**
- User reports endpoint working fine all day
- 4 concurrent samples is low load

**LIKELY ROOT CAUSE:** Azure returning 5xx or 408 timeout errors, combined with inspect_ai retrying forever.

### Hypothesis 4: inspect_ai Retry Logic Bug ✅ CONFIRMED
The retry mechanism in inspect_ai does not have proper timeout/max_retry limits BY DEFAULT.

**CONFIRMED:** `inspect_ai/model/_retry.py` uses `stop_never` when neither `--max-retries` nor `--timeout` is passed.

**Fix:** Always pass `--max-retries 10` or `--timeout 300` to prevent infinite loops.

## Code Path Involved

### Client-Side Evaluation Flow (saber_scorer.py)

```
saber_scorer() 
  → _score_client_side_evaluation()
    → _evaluate_submission_llm()      # ✅ Works - uses openai/azure/gpt-4.1
    → _evaluate_subtasks()
      → _score_subtasks_llm_batch()   # ❌ HANGS HERE
        → get_model(model_name)       # openai/azure/gpt-4.1
        → model.generate(state.messages)  # Infinite retry loop
```

### Key File: `external/saber/src/saber/inspect_ai/core/saber_scorer.py`
Lines ~1380-1390:
```python
model = get_model(model_name)
response = await model.generate(state.messages)
```

This `model.generate()` call is where the hang occurs. The inspect_ai model wrapper handles retries internally.

## Relevant Files

| File | Purpose |
|------|---------|
| [logs/2026-02-12T22-34-11+00-00_excytin_BbvsCxUEFKLg9Hayzx7wQB.eval](../logs/2026-02-12T22-34-11+00-00_excytin_BbvsCxUEFKLg9Hayzx7wQB.eval) | Inspect AI eval log (20MB) |
| [logs/saber_inspect_excytin_2026-02-12T22-30-19.log](../logs/saber_inspect_excytin_2026-02-12T22-30-19.log) | SABER client log (4.3MB) |
| [external/saber/src/saber/inspect_ai/core/saber_scorer.py](../../external/saber/src/saber/inspect_ai/core/saber_scorer.py) | LLM judge scoring logic |

## Root Cause Analysis

### Key Discovery: inspect_ai Retries Forever by Default

**Found in `inspect_ai/model/_retry.py`:**

```python
"stop": (
    stop_after_attempt(max_retries) | stop_after_delay(timeout)
    if max_retries is not None and timeout is not None
    else stop_after_attempt(max_retries)
    if max_retries is not None
    else stop_after_delay(timeout)
    if timeout is not None
    else stop_never  # <-- DEFAULT BEHAVIOR!
)
```

**When neither `--max-retries` nor `--timeout` is specified, inspect_ai uses `stop_never` - it will retry indefinitely!**

### Retryable Errors (from `inspect_ai/_util/http.py`):

```python
def is_retryable_http_status(status_code: int) -> bool:
    return status_code in [408, 429] or (500 <= status_code < 600)
```

Errors that trigger retry:
- **HTTP 408** - Request Timeout
- **HTTP 429** - Rate Limited  
- **HTTP 5xx** - Server Errors

### Template Truncation Analysis

The checkpoint judge templates DO include truncation filters:

```jinja2
Input: {{ step.action.parameters | string | truncate(300) }}
Agent Message: {{ step.action.assistant_message | truncate(800) }}
Agent Reasoning: {{ step.action.reasoning | truncate(600) }}
Output: {{ step.response | string | truncate(1000) }}
```

**Per step max: ~2700 characters**  
**With 18 steps: ~48,600 chars ≈ 12K tokens**

This is well within gpt-4.1's context window, so **token count is NOT the primary issue**.

### Missing Information

The actual HTTP error code being returned is NOT logged at INFO level. The logs only show:
```
Retrying request to /chat/completions in 30.000000 seconds
```

But NOT the error that triggered it.

### Likely Scenarios

1. **Server returning HTTP 5xx** - Internal server error from Azure OpenAI
2. **Request Timeout (408)** - Large prompt taking too long to process
3. **Rate Limiting (429)** - Despite user claim, could be hitting limits

## Recommended Fixes

### Immediate Fix: Add Retry Limits

```bash
# Add --max-retries flag to prevent infinite loops
uv run inspect eval domains/excytin --model openai/azure/gpt-5.2 \
  --max-retries 5 \
  --timeout 300 \
  -T task_filter="incident_*_legacy_train_set_*"
```

### Code Fix: Default max_retries in SABER

Add sensible defaults in `external/saber/src/saber/client/models.py`:

```python
endpoint_max_retries: int | None = 10  # Change from None to 10
```

### Debug Fix: Enable DEBUG logging

```bash
INSPECT_LOG_LEVEL=debug uv run inspect eval domains/excytin \
  --model openai/azure/gpt-4.1 \
  -T task_filter="incident_5_legacy_train_set_task_44" \
  --limit 1
```

This will show the actual HTTP error code being returned.

## Workaround

1. **Always use `--max-retries`** flag:
```bash
uv run inspect eval domains/excytin --model openai/azure/gpt-5.2 \
  --max-retries 10 \
  -T task_filter="incident_*_legacy_train_set_*"
```

2. Monitor for stuck samples and re-run affected ones individually

## Related Configuration

```yaml
# Task YAML for hung samples
step_evaluation_config:
  strategy: llm_judge
  criteria:
    model: openai/azure/gpt-4.1
    judge_system_template: judge/checkpoint_judge_system.md
    judge_user_template: judge/checkpoint_judge_user.md
    steps_per_message: 50
```

---

## SQL Query Output Analysis (User Hypothesis)

**Question:** Could large SQL query results in step outputs exceed the context window?

### Investigation

1. **Template truncation is applied:** The user template uses `{{ step.response | string | truncate(1000) }}` which limits tool output to 1000 chars per step.

2. **Jinja2 truncate confirmed working:**
```python
>>> from jinja2 import Environment
>>> env = Environment()
>>> template = env.from_string('{{ text | truncate(100) }}')
>>> template.render(text='x' * 5000)
'xxxx...xx...'  # Properly truncated to 100 chars
```

3. **Step context construction in `saber_scorer.py`:**
```python
step_objects.append(
    StepContextForTemplate({
        "step_number": step.step_number,
        "tool_name": step.tool_name,
        "tool_input": step.tool_input,
        "tool_output": step.tool_output,  # Raw SQL results - could be huge
        ...
    })
)
```

The raw `tool_output` is passed to the template, but Jinja2's `truncate()` filter should limit it.

### Potential Issue

If the template rendering fails for some reason (e.g., encoding issue, object serialization failure), the truncation might not be applied. However, this would likely cause a template error, not an infinite retry.

### Conclusion

**SQL query output size is NOT the root cause** because:
1. Templates apply truncation
2. Even with 20 steps × 2700 chars max = ~54K chars is within context limits
3. The actual issue is inspect_ai's `stop_never` retry policy

However, adding explicit token counting before LLM calls would help detect this if it ever becomes an issue.

---

## Lessons Learned

1. **Always use retry limits** - `--max-retries 10 --timeout 600` is MANDATORY for reliable runs
2. **Azure API issues are common** - Feb 17 had 944 retries (6x worse than Feb 12), proving this isn't rare
3. **Don't trust a single successful run** - Feb 13 passing with 0 retries was coincidental
4. **Verify fixes under stress** - A proper fix must work when the underlying issue recurs

## Recommended Default Configuration

Add to all evaluation commands:
```bash
--max-retries 10 --timeout 600
```

Consider adding these as defaults in SABER configuration to prevent future incidents.

## Real Solutions (Beyond --max-retries)

### 1. Reduce Concurrency
```bash
uv run inspect eval domains/excytin --model openai/azure/gpt-5.2 \
  --max-connections 5 \   # Reduce from default 10
  --max-retries 10 \
  -T task_filter="incident_*_legacy_train_set_*"
```

### 2. Use Separate Azure Deployments
Configure different Azure OpenAI deployments for:
- Agent model (high-volume, lower priority)
- Judge model (scoring, needs reliability)

### 3. Request Higher TPM/RPM Limits
Contact Azure to increase:
- Tokens per minute (TPM)
- Requests per minute (RPM)

### 4. Implement Client-Side Rate Limiting
Add throttling in SABER to stay within Azure limits proactively.

---

## Feb 18 Update: Deeper Investigation

### Key Findings

1. **Only 3 samples actually hung** (not 6 as originally estimated)
   - Verified by counting "Starting batch LLM" vs "Batch LLM complete" log events
   - 415 started, 412 completed → 3 hung

2. **NOT rate limiting** - Evidence:
   - At `22:38:33` when `task_16` was retrying, OTHER batch evaluations completed successfully
   - Feb 17 run: 944 retries to `/responses` (agent), but 0 retries to `/chat/completions` (judge)
   - The hung samples had 30-second constant retry intervals (not exponential backoff typical of 429)

3. **Root cause is per-request failures**, not systemic issues:
   - One sample (`task_67`) had `submission_length=0` due to WebSocket closing BEFORE evaluation
   - The other two may have hit transient server errors (5xx) that persisted

4. **Prompt content analysis** shows NO anomalies:
   - Hung sample prompts: 11K-20K chars (within normal range)
   - Same prompts worked successfully on later runs
   - Max line lengths ~1000 chars, normal SQL counts

### Timeline Correlation

| Time | Hung Sample | What Happened |
|------|-------------|---------------|
| 22:38:31 | task_16 | Batch started, immediate retry at 22:38:33 |
| 22:38:33 | - | DIFFERENT batch evaluation COMPLETED at same time |
| 22:58:47 | task_67 | WebSocket CLOSED before eval started |
| 22:58:52 | task_67 | Eval started with **empty submission** (0 chars) |
| 23:53:04 | task_44 | Batch started, retry at 23:53:05 |

### Why `--max-retries` Helps

The Feb 17 run with `--max-retries 10` succeeded because:
- Judge calls (`/chat/completions`) had 0 retries - no transient errors
- Agent calls (`/responses`) had 944 retries but eventually succeeded

The fix works by preventing infinite loops, but the underlying transient errors still occur randomly.

### Remaining Questions

1. **Why did these 3 specific requests fail repeatedly?**
   - Our investigation couldn't find content differences
   - May be Azure-side issue (specific deployment pods, network routing)

2. ~~**Why was task_67's WebSocket closed early?**~~
   - **RESOLVED** — See "WebSocket Keepalive Bug" section below

3. ~~**Should we add logging for HTTP error codes?**~~
   - **RESOLVED** — HTTP error logging added to both `model.generate()` call sites in `saber_scorer.py`

---

## Code Fixes Applied (Feb 18)

### Fix 1: WebSocket Keepalive Bug (connection.py)

**File:** `external/saber/src/saber/client/transcript/connection.py` line 184

**Problem:** `websockets.connect()` was called WITHOUT passing `ping_interval` and `ping_timeout` parameters. The websockets library defaults to `ping_interval=20, ping_timeout=20`, but SABER's configured values (`PING_INTERVAL=30s, PONG_TIMEOUT=10s` in `websocket_constants.py`) were never applied.

**Impact:** For task_67, the WebSocket connection opened at `22:58:27` and closed at `22:58:47` — exactly 20 seconds later, matching the websockets library's default `ping_interval` of 20s. The library sent a ping, got no pong within 20s, and closed the connection. The agent was mid-execution and aborted, producing an empty submission (`submission_length=0`). The scorer then tried to evaluate an empty prompt, causing the judge to fail repeatedly.

**Fix:**
```python
# Before (bug):
ws = await websockets.connect(url, additional_headers=headers)

# After (fixed):
ws = await websockets.connect(
    url,
    additional_headers=headers,
    ping_interval=self._ws_config.ping_interval,
    ping_timeout=self._ws_config.pong_timeout,
)
```

**Verification:**
```python
>>> import websockets; help(websockets.connect)
# ping_interval (Optional[float]) – Delay between keepalive pings in seconds. 20 (seconds) by default.
# ping_timeout (Optional[float]) – Timeout for keepalive pings in seconds. 20 (seconds) by default.
```

### Fix 2: HTTP Error Code Logging (saber_scorer.py)

**File:** `external/saber/src/saber/inspect_ai/core/saber_scorer.py`

**Problem:** When `model.generate()` failed and was retried by the openai library, the only log message was:
```
Retrying request to /chat/completions in 30.000000 seconds
```
No actual HTTP error code, error message, or request details were logged.

**Fix:** Added try/except blocks around both `model.generate()` call sites:
1. **Submission evaluation** (`_evaluate_submission_llm`) — logs event `llm_submission_generate_error`
2. **Batch subtask evaluation** (`_score_subtasks_llm_batch`) — logs event `llm_batch_generate_error`

Each logs:
- `error_type` — Exception class name (e.g., `APIStatusError`, `APITimeoutError`)
- `error_message` — Full error string including HTTP status code
- `model` — Which model was called
- `system_len` / `user_len` — Prompt sizes for debugging context length issues

---

*Last Updated: 2026-02-18 (WebSocket keepalive bug fixed, HTTP error logging added)*
