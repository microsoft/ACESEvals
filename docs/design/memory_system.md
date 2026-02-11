# SABER Memory System Design

## 1. Overview

The SABER Memory System provides agents with persistent, queryable memory 
capabilities that span individual episodes, domain runs, and cross-domain 
evaluations. This enables agents to leverage historical context, learned 
patterns, and accumulated knowledge.

## 2. Design Goals

### 2.1 Primary Goals
- **Seeded Memory**: Pre-populate agent memory with domain knowledge
- **Cross-Run Learning**: Load insights from previous .eval files (historical memory)
- **Cross-Domain Transfer**: Enable knowledge transfer between domains

> **Note:** Episode persistence (memory persisting across steps within a single agent run) 
> is provided by Inspect AI's `memory()` tool by default - not something we implement.

### 2.2 Non-Goals (Phase 1)
- Real-time memory synchronization between agents
- Automatic memory consolidation/summarization
- Memory access control/permissions

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     SABER Memory System                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │   Static    │    │   Episode   │    │    Persistent       │  │
│  │   Seeds     │───▶│   Memory    │───▶│    Memory Store     │  │
│  │             │    │  (Runtime)  │    │   (.eval files)     │  │
│  └─────────────┘    └─────────────┘    └─────────────────────┘  │
│        │                   │                     │              │
│        ▼                   ▼                     ▼              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Memory Resolver                          ││
│  │  - Loads seeds from config/files                            ││
│  │  - Hydrates from .eval logs                                 ││
│  │  - Provides to inspect_ai.tool.memory()                     ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Inspect AI Memory Tool                         ││
│  │              (Agent Interface)                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 4. Design Decisions

This section documents key architectural decisions and their trade-offs.

---

### DD-1: Tool Integration Approach

**Question:** How should the memory tool be integrated into the SABER framework?

#### Option A: Domain-Level Integration (Quick/Flexible)

Create a custom tool wrapper in the domain's client code:

```python
# filepath: domains/excytin/client/tools/memory_tool.py
from inspect_ai.tool import memory, Tool
from pathlib import Path

def excytin_memory(task_id: str = None) -> Tool:
    """Memory tool with domain-specific seeded data."""
    
    initial_data = {
        "/memories/investigation_notes.md": "",
        "/memories/findings.md": "",
        "/memories/threat_intel.md": load_threat_intel(),
    }
    
    if task_id:
        task_seeds = load_task_seeds(task_id)
        initial_data.update(task_seeds)
    
    return memory(initial_data=initial_data)
```

**Pros:**
- Quick to implement
- Domain has full control
- No framework changes required
- Easy to customize per-domain

**Cons:**
- Code duplication across domains
- No standardized configuration
- Harder to share patterns
- No framework-level persistence support

#### Option B: Framework-Level Integration (Standardized)

Extend the SABER tool resolver to support memory configuration in YAML:

```yaml
# global.yaml
execution_config:
  executors:
    bash:
      timeout: 180
    python:
      timeout: 180
  
  memory:
    enabled: true
    initial_data:
      - path: "/memories/notes.md"
        content: ""
      - path: "/memories/threat_intel.md"
        source: "seeds/threat_intel.md"
    
    persistence:
      enabled: false  # Phase 2
      source: "eval_logs"
```

**Pros:**
- Standardized across all domains
- Configuration-driven (no code changes)
- Framework handles persistence
- Easier to add features (compression, versioning)

**Cons:**
- Requires framework changes
- Less flexibility for domain-specific logic
- Longer initial implementation time
- Schema changes affect all domains

#### Option C: Hybrid Approach

Framework provides base memory resolver, domains can extend/override:

```python
# Framework provides base
from saber.tools import BaseMemoryResolver

# Domain extends (Phase 2 - TBD)
class ExcytinMemoryResolver(BaseMemoryResolver):
    def load_domain_seeds(self):
        # Custom domain logic
        pass
```

**Pros:**
- Best of both worlds
- Standardized base with flexibility
- Domains can opt-in to customization

**Cons:**
- More complex architecture
- Need to define extension points carefully

**Decision:** [x] Option C (Hybrid Approach)

**Rationale:** 
Memory is needed across all domains, so standardization via framework integration is important. 
However, different domains may have unique memory hydration requirements (e.g., loading from 
different sources, domain-specific transformations, custom relevance scoring).

**Implementation Plan:**
- **Phase 1:** Implement `BaseMemoryResolver` in the framework with YAML-driven configuration. 
  Use this base resolver for excytin and all domains. No custom extension support yet.
- **Phase 2:** Add extension points for domain-specific `MemoryResolver` subclasses that can 
  override seed loading, historical memory retrieval, and relevance scoring.
  *[TO BE IMPLEMENTED: Custom MemoryResolver extension mechanism]*

---

### DD-2: Memory Storage Location

**Question:** Where should memory seeds and configuration be stored?

#### Option A: Alongside Prompts (Server Config)

```
domains/excytin/server/config/
├── prompts/
│   └── instructions/
├── seeds/
│   ├── threat_intel.md
│   └── query_patterns.md
└── tasks/
    └── global.yaml
```

**Pros:**
- Co-located with other agent configuration
- Server-side, versioned with task definitions
- Clear separation from client code

**Cons:**
- Seeds are really agent knowledge, not server config
- May need different access patterns

#### Option B: In Client Directory

```
domains/excytin/client/
├── agents/
├── tools/
└── memory/
    ├── seeds/
    │   ├── threat_intel.md
    │   └── query_patterns.md
    └── memory_config.yaml
```

**Pros:**
- Agent-centric location
- Client owns agent knowledge
- Clear ownership model

**Cons:**
- Disconnected from task configuration
- May duplicate across agents

#### Option C: Dedicated Memory Directory

```
domains/excytin/
├── client/
├── server/
└── memory/
    ├── seeds/
    │   ├── global/
    │   └── tasks/
    ├── historical/
    └── config.yaml
```

**Pros:**
- Clear dedicated location
- Supports all memory types
- Easy to find and manage

**Cons:**
- New directory structure
- Need to update tooling

**Decision:** [x] Option A (Server Config)

**Rationale:**
Memory is conceptually similar to prompts—content that shapes agent behavior. Keeping seeds 
alongside prompts in `server/config/` maintains consistency with existing patterns and couples 
memory configuration naturally with task definitions in YAML files.

**Chosen Directory Structure:**
```
domains/excytin/server/config/
├── prompts/
│   └── instructions/
│       └── excytin_demo.md
├── seeds/                        ← NEW: Memory seeds
│   ├── global/                   ← Seeds for all tasks
│   │   ├── threat_intel.md
│   │   └── query_patterns.md
│   └── tasks/                    ← Task-specific seeds (optional)
│       └── incident_5/
│           └── context.md
└── tasks/
    ├── global.yaml               ← memory_config defined here
    └── incident_5/
        └── incident_5_1.yaml
```

**Notes:**
- Task-specific seeds use parallel structure in `seeds/tasks/` (optional, for future use)
- *[TO BE IMPLEMENTED: Client-side memory for domain-specific agent knowledge]*

---

### DD-3: Memory Path Namespace

**Question:** How should memory paths be structured?

#### Option A: Flat Namespace

```
/memories/notes.md
/memories/findings.md
/memories/threat_intel.md
```

**Pros:**
- Simple, matches Inspect's default
- Easy to understand
- Minimal path handling

**Cons:**
- No organization for complex memory
- Potential name collisions

#### Option B: Hierarchical by Type

```
/memories/seeds/threat_intel.md
/memories/seeds/query_patterns.md
/memories/runtime/notes.md
/memories/runtime/findings.md
/memories/historical/previous_run.md
```

**Pros:**
- Clear organization
- Separates seeded vs runtime memory
- Easier to filter/query

**Cons:**
- More complex paths
- Agent needs to know structure

#### Option C: Hierarchical by Task

```
/memories/global/threat_intel.md
/memories/incident_5/context.md
/memories/incident_5_task_1/notes.md
```

**Pros:**
- Task-scoped memory
- Clear inheritance model
- Supports task-specific seeds

**Cons:**
- Agent needs task context
- More complex resolution

**Decision:** [x] Option B (Hierarchical by Type)

**Rationale:**
The Inspect AI `memory()` tool is based on the Anthropic Claude memory tool, which expects a 
directory structure. Most future agents will likely follow this pattern, so adopting hierarchy 
now aligns with industry direction. The path structure and descriptive filenames provide 
sufficient clarity for agents to understand memory organization.

**Chosen Path Structure:**
```
/memories/
├── seeds/                          ← Pre-loaded domain knowledge (read-mostly)
│   ├── threat_intel.md
│   └── query_patterns.md
├── runtime/                        ← Agent workspace (read-write)
│   ├── notes.md
│   └── findings.md
└── historical/                     ← From previous runs (Phase 3+)
    └── previous_findings.md
```

**Conventions (Excytin as template, domains can customize):**
- `seeds/` - Pre-loaded content, agents should read but rarely modify
- `runtime/` - Agent's working space for notes, findings, scratchpad
- `historical/` - Memories loaded from previous .eval files (Phase 3+)
- Descriptive filenames (e.g., `threat_intel.md`, `findings.md`)
- If agent confusion occurs, add clarifying instructions in task prompt

**Notes:**
- This structure serves as the base convention for all domains
- Domain developers can add custom paths/files as needed
- Path hierarchy helps agents choose relevant memories

---

### DD-4: Historical Memory Extraction

**Question:** How should memories be extracted from .eval files for reuse?

**Decision:** [x] **Modular Memory Types** - Support all extraction modes as configurable types

#### Inspect AI Log API

We will use the native **Inspect AI Log API** for reading `.eval` files and extracting memories.
This avoids maintaining a custom parser and ensures compatibility across Inspect AI versions.

##### API Overview

```python
from inspect_ai.log import read_eval_log

# Read full log with all samples
log = read_eval_log("path/to/file.eval")

# Read header only (faster, no samples loaded)
log = read_eval_log("path/to/file.eval", header_only=True)
```

##### Available Data Structures

**EvalLog (top-level):**
| Attribute | Type | Description |
|-----------|------|-------------|
| `log.eval.task` | `str` | Task name (e.g., "excytin") |
| `log.eval.model` | `str` | Model used (e.g., "openai/azure/gpt-4.1") |
| `log.eval.created` | `str` | ISO timestamp |
| `log.eval.eval_id` | `str` | Unique eval identifier |
| `log.eval.run_id` | `str` | Run identifier |
| `log.results.total_samples` | `int` | Total sample count |
| `log.results.completed_samples` | `int` | Completed sample count |
| `log.samples` | `list[EvalSample]` | List of sample objects |

**EvalSample:**
| Attribute | Type | Description |
|-----------|------|-------------|
| `sample.id` | `str` | Sample identifier (e.g., "incident_5_task_3__attempt_1") |
| `sample.epoch` | `int` | Epoch number |
| `sample.input` | `list` | Input messages |
| `sample.target` | `str` | Expected target |
| `sample.messages` | `list` | Full conversation messages |
| `sample.output` | `ModelOutput` | Final model output |
| `sample.scores` | `dict[str, Score]` | Scoring results |
| `sample.metadata` | `dict` | Sample metadata |
| `sample.store` | `dict` | Key-value store state |
| `sample.events` | `list[Event]` | All events in trajectory |

**Event Types:**
| Event Type | Description | Key Attributes |
|------------|-------------|----------------|
| `model` | LLM call | `output.completion` (agent thinking), `input`, `tools`, `timestamp` |
| `tool` | Tool execution | `function`, `arguments`, `result`, `error` |
| `score` | Scoring event | Score value and explanation |
| `store` | State store update | Key-value changes |
| `state` | Agent state change | State transitions |
| `sample_init` | Sample initialization | Initial setup |
| `span_begin` | Span start | Span metadata |
| `span_end` | Span end | Duration, status |

**ModelEvent Details:**
```python
model_event.output.completion  # Agent's thinking/reasoning (string)
model_event.output.message     # Structured message with role, content
model_event.input              # Input messages to model
model_event.tools              # Available tools
model_event.timestamp          # ISO timestamp
```

**ToolEvent Details:**
```python
tool_event.function    # Tool name (e.g., "bash", "submit", "memory")
tool_event.arguments   # Dict of arguments (e.g., {"command": "..."})
tool_event.result      # Result object or string
tool_event.error       # Error dict if failed
tool_event.timestamp   # ISO timestamp
```

**Score Details:**
```python
sample.scores["scorer_name"].value        # Numeric score (0.0 - 1.0)
sample.scores["scorer_name"].answer       # Agent's answer
sample.scores["scorer_name"].explanation  # Scoring explanation
sample.scores["scorer_name"].metadata     # Additional scoring metadata
```

##### CLI Access

```bash
# List available logs
inspect log list

# Dump full log as JSON
inspect log dump path/to/file.eval

# Dump header only (no samples)
inspect log dump path/to/file.eval --header-only

# Resolve attachments
inspect log dump path/to/file.eval --resolve-attachments full
```

#### Memory Type System

We implement a **modular memory type system** where each type extracts different information:

| Memory Type | Description | Size | Use Case |
|-------------|-------------|------|----------|
| `final_state` | Final memory paths at episode end | Small | Quick context loading |
| `trajectory` | Full agent trajectory with thoughts | Large | Debugging, detailed replay |
| `operations` | All tool calls with results | Medium | Pattern analysis |
| `insights` | LLM-summarized learnings | Small | Cross-task transfer |
| `checkpoints` | State at checkpoint completions | Medium | Milestone tracking |
| `errors` | Failed operations and resolutions | Small | Error avoidance |

##### Memory Type: `final_state`

Extract only the final memory state from the sample's store:

```python
def extract_final_state(sample: EvalSample) -> dict:
    """Extract final memory state from sample."""
    return {
        "type": "final_state",
        "sample_id": sample.id,
        "score": sample.scores.get("saber_scorer", {}).value,
        "memory_paths": sample.store.get("memory", {}),
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "model": log.eval.model,
        }
    }
```

**Output Example:**
```json
{
  "type": "final_state",
  "sample_id": "incident_5_task_3__attempt_1",
  "score": 1.0,
  "memory_paths": {
    "/memories/notes.md": "## Investigation Notes\n- Found C2 IP...",
    "/memories/findings.md": "## Findings\n1. 107.224.99.179"
  }
}
```

##### Memory Type: `trajectory`

Extract full agent trajectory with thinking:

```python
def extract_trajectory(sample: EvalSample) -> dict:
    """Extract full trajectory with agent thoughts."""
    steps = []
    current_step = {"step": 0, "thoughts": [], "actions": []}
    
    for event in sample.events:
        if event.event == "model":
            # New model call = new step
            if current_step["thoughts"] or current_step["actions"]:
                steps.append(current_step)
            current_step = {
                "step": len(steps) + 1,
                "thoughts": [event.output.completion] if event.output.completion else [],
                "actions": [],
                "timestamp": event.timestamp,
            }
        elif event.event == "tool":
            current_step["actions"].append({
                "tool": event.function,
                "args": event.arguments,
                "result_preview": str(event.result)[:500] if event.result else None,
                "error": event.error,
            })
    
    if current_step["thoughts"] or current_step["actions"]:
        steps.append(current_step)
    
    return {
        "type": "trajectory",
        "sample_id": sample.id,
        "score": sample.scores.get("saber_scorer", {}).value,
        "total_steps": len(steps),
        "steps": steps,
    }
```

##### Memory Type: `operations`

Extract all tool operations for pattern analysis:

```python
def extract_operations(sample: EvalSample) -> dict:
    """Extract all tool operations."""
    operations = []
    
    for event in sample.events:
        if event.event == "tool":
            operations.append({
                "function": event.function,
                "arguments": event.arguments,
                "success": event.error is None,
                "timestamp": event.timestamp,
            })
    
    # Aggregate statistics
    tool_counts = {}
    for op in operations:
        tool_counts[op["function"]] = tool_counts.get(op["function"], 0) + 1
    
    return {
        "type": "operations",
        "sample_id": sample.id,
        "score": sample.scores.get("saber_scorer", {}).value,
        "operations": operations,
        "tool_usage": tool_counts,
        "total_operations": len(operations),
    }
```

##### Memory Type: `insights`

LLM-summarized learnings from trajectory:

```python
def extract_insights(sample: EvalSample, llm_client) -> dict:
    """Extract summarized insights using LLM."""
    trajectory = extract_trajectory(sample)
    
    prompt = f"""Analyze this agent trajectory and extract key learnings:

Score: {trajectory['score']}
Steps: {trajectory['total_steps']}

Trajectory:
{json.dumps(trajectory['steps'], indent=2)[:8000]}

Extract:
1. Successful techniques (what worked)
2. Key findings (important discoveries)
3. Query patterns (useful SQL/shell patterns)
4. Mistakes to avoid (what didn't work)

Output as JSON with keys: techniques, findings, patterns, mistakes
"""
    
    response = llm_client.complete(prompt)
    insights = json.loads(response)
    
    return {
        "type": "insights",
        "sample_id": sample.id,
        "score": trajectory["score"],
        "insights": insights,
        "metadata": {
            "source_steps": trajectory["total_steps"],
            "extracted_at": datetime.now().isoformat(),
        }
    }
```

##### Memory Type: `checkpoints`

Extract state at checkpoint completions:

```python
def extract_checkpoints(sample: EvalSample) -> dict:
    """Extract state at checkpoint completions."""
    score_meta = sample.scores.get("saber_scorer", {}).metadata or {}
    step_evals = score_meta.get("step_evaluations", [])
    
    checkpoints = []
    for eval_item in step_evals:
        if eval_item.get("completed"):
            checkpoints.append({
                "objective_id": eval_item["objective_id"],
                "objective_type": eval_item["objective_type"],
                "completed_at_step": eval_item["step_number"],
            })
    
    return {
        "type": "checkpoints",
        "sample_id": sample.id,
        "score": sample.scores.get("saber_scorer", {}).value,
        "checkpoints_completed": checkpoints,
        "total_checkpoints": len(checkpoints),
    }
```

##### Memory Type: `errors`

Extract errors and how they were resolved:

```python
def extract_errors(sample: EvalSample) -> dict:
    """Extract errors and their resolutions."""
    errors = []
    
    for i, event in enumerate(sample.events):
        if event.event == "tool" and event.error:
            # Look for resolution in subsequent events
            resolution = None
            for j in range(i + 1, min(i + 5, len(sample.events))):
                next_event = sample.events[j]
                if next_event.event == "tool" and not next_event.error:
                    if next_event.function == event.function:
                        resolution = {
                            "fixed_args": next_event.arguments,
                            "steps_to_fix": j - i,
                        }
                        break
            
            errors.append({
                "tool": event.function,
                "error": event.error,
                "original_args": event.arguments,
                "resolution": resolution,
            })
    
    return {
        "type": "errors",
        "sample_id": sample.id,
        "score": sample.scores.get("saber_scorer", {}).value,
        "errors": errors,
        "total_errors": len(errors),
        "resolved_errors": len([e for e in errors if e["resolution"]]),
    }
```

#### Configuration

```yaml
memory_config:
  historical:
    enabled: true
    
    # Memory types to extract
    extraction_types:
      - final_state      # Always extract (small)
      - operations       # Extract tool patterns
      - checkpoints      # Track milestone completions
      - errors          # Learn from failures
      # - trajectory     # Full trajectory (large, optional)
      # - insights       # LLM summarization (requires LLM call)
    
    # Filter criteria for loading memories
    loading:
      min_score: 0.5              # Only load from successful runs
      max_memories: 10            # Limit memories loaded per type
      prefer_recent: true         # Prioritize recent runs
      same_incident_only: false   # Allow cross-incident memories
    
    # LLM settings for insights extraction
    insights:
      enabled: false
      model: "openai/gpt-4o-mini"
      max_tokens: 1000
```

#### Memory Extraction Pipeline

```python
class MemoryExtractor:
    """Extract memories from .eval files using Inspect AI Log API."""
    
    EXTRACTORS = {
        "final_state": extract_final_state,
        "trajectory": extract_trajectory,
        "operations": extract_operations,
        "checkpoints": extract_checkpoints,
        "errors": extract_errors,
        # insights requires LLM, handled separately
    }
    
    def __init__(self, config: dict):
        self.config = config
        self.extraction_types = config.get("extraction_types", ["final_state"])
    
    def extract_from_eval(self, eval_path: str) -> list[dict]:
        """Extract memories from an eval file."""
        from inspect_ai.log import read_eval_log
        
        log = read_eval_log(eval_path)
        memories = []
        
        min_score = self.config.get("loading", {}).get("min_score", 0.0)
        
        for sample in log.samples:
            # Check score threshold
            score = sample.scores.get("saber_scorer", Score(value=0)).value
            if score < min_score:
                continue
            
            # Extract each configured memory type
            for mem_type in self.extraction_types:
                if mem_type in self.EXTRACTORS:
                    memory = self.EXTRACTORS[mem_type](sample)
                    memory["source_eval"] = eval_path
                    memory["source_task"] = log.eval.task
                    memory["source_model"] = log.eval.model
                    memories.append(memory)
        
        return memories
    
    def aggregate_memories(self, memories: list[dict]) -> dict:
        """Aggregate memories by type for loading."""
        aggregated = {}
        
        for mem in memories:
            mem_type = mem["type"]
            if mem_type not in aggregated:
                aggregated[mem_type] = []
            aggregated[mem_type].append(mem)
        
        # Apply limits
        max_per_type = self.config.get("loading", {}).get("max_memories", 10)
        for mem_type in aggregated:
            if len(aggregated[mem_type]) > max_per_type:
                # Sort by score descending, take top N
                aggregated[mem_type].sort(
                    key=lambda m: m.get("score", 0),
                    reverse=True
                )
                aggregated[mem_type] = aggregated[mem_type][:max_per_type]
        
        return aggregated
```

**Rationale:** The modular approach provides flexibility:
- **Small memory footprint:** Use `final_state` + `errors` only
- **Full debugging:** Add `trajectory` for complete replay
- **Pattern learning:** Use `operations` for tool usage patterns
- **Cross-task transfer:** Use `insights` for summarized learnings
- **Checkpoint tracking:** Use `checkpoints` for milestone analysis

This approach integrates directly with Inspect AI's native log API, ensuring compatibility
and avoiding custom parsing logic. All memory types can be implemented in Phase 1.

---

### DD-5: [REMOVED]

> **Note:** DD-5 (Cross-Domain Memory Format) was removed as redundant.
> 
> **Rationale:** The memory extraction format defined in DD-4 is already domain-agnostic.
> All .eval files use the same Inspect AI format regardless of domain. Cross-domain
> memory loading is simply loading memories from different source domains, with
> relevance/filtering handled by DD-7. The path structure from DD-3 already supports
> organizing memories by source domain (e.g., `/memories/historical/excytin/...`).

---

### DD-6: Memory Size Management

**Question:** How should memory size be managed to prevent unbounded growth?

#### Option A: Hard Limits per Path

```yaml
memory_config:
  limits:
    max_size_per_path: 50KB
    max_total_size: 500KB
    behavior_on_limit: truncate_oldest  # or error, summarize
```

**Pros:**
- Simple, predictable
- Prevents runaway costs
- Easy to implement

**Cons:**
- May lose important content
- Arbitrary limits
- No intelligence in what to keep

#### Option B: Token-Based Limits

```yaml
memory_config:
  limits:
    max_tokens_per_path: 10000
    max_total_tokens: 50000
    model_for_counting: gpt-4  # Use model's tokenizer
```

**Pros:**
- Aligned with LLM context limits
- More meaningful for agents
- Consistent with prompt budgeting

**Cons:**
- Model-specific
- Slower (tokenization overhead)
- May vary by model

#### Option C: Automatic Summarization

```yaml
memory_config:
  limits:
    summarize_at_tokens: 5000
    target_after_summarization: 2000
    summarization_model: gpt-4-mini
```

**Pros:**
- Preserves important information
- Intelligent compression
- Adapts to content

**Cons:**
- LLM cost for summarization
- Latency impact
- May lose details

**Decision:** [x] **Option A**  [ ] Option B  [ ] Option C

**Rationale:** 
- **Simplicity first** - No external dependencies, easy to implement and debug
- **Predictable behavior** - Users know exactly what will happen at limits
- **Phase 1 scope** - Token counting and LLM summarization add complexity for later phases
- **Upgradeable** - Can add Option B (tokens) or C (summarization) in Phase 3+ if needed

**Defaults:**
```yaml
memory_config:
  limits:
    max_size_per_path: 100KB    # ~25K tokens roughly (4 chars ≈ 1 token)
    max_total_size: 1MB         # Total across all memory paths
    behavior_on_limit: truncate_oldest  # Options: truncate_oldest, error, warn
```

---

### DD-7: Memory Relevance Scoring for Historical Loading

**Question:** How should the system determine which historical memories to load?

> **Scope:** This decision covers both same-domain and cross-domain memory loading.
> Since all memories use the same format (DD-4), the relevance scoring determines
> which memories to load regardless of source domain.

#### Cross-Domain Considerations

When loading memories from different domains, additional factors apply:

| Factor | Same-Domain | Cross-Domain |
|--------|-------------|---------------|
| Task similarity | High weight | Medium weight |
| Domain match | N/A (always matches) | Bonus/penalty factor |
| Tool overlap | Assumed | Must verify tools exist |
| Schema relevance | High | Low (different DBs) |
| Technique transfer | Direct | May need adaptation |

**Cross-domain filtering strategy:**
```python
def is_cross_domain_relevant(memory, target_domain):
    source_domain = memory["source_task"]  # From DD-4 metadata
    
    # Always relevant: error patterns, general techniques
    if memory["type"] in ["errors", "insights"]:
        return True
    
    # Domain-specific: operations often contain domain-specific queries
    if memory["type"] == "operations":
        # Check if tools used exist in target domain
        return all(tool in target_domain.available_tools 
                   for tool in memory.get("tool_usage", {}).keys())
    
    # Trajectories: generally too domain-specific
    if memory["type"] == "trajectory":
        return False
    
    return True
```

#### Option A: Recency-Based

Most recent evaluations weighted highest:

```python
def score_memory(memory, current_task):
    age_days = (now - memory["timestamp"]).days
    return 1.0 / (1.0 + age_days * 0.1)  # Decay over time
```

**Pros:**
- Simple to implement
- Recent = more relevant assumption
- No semantic analysis needed

**Cons:**
- Old valuable memories lost
- No content awareness
- May load irrelevant recent data

#### Option B: Task Similarity

Score based on task/incident similarity:

```python
def score_memory(memory, current_task):
    # Simple: same incident type bonus
    if get_incident_type(memory["source_task"]) == get_incident_type(current_task):
        return 1.0
    
    # Could use embeddings for semantic similarity
    return compute_similarity(
        memory.get("task_description", ""),
        current_task.description
    )
```

**Pros:**
- Content-aware
- Loads relevant memories
- Works across time

**Cons:**
- Requires similarity computation
- Need to define similarity metric
- May miss generally useful memories

#### Option C: Success-Weighted

Weight by evaluation success:

```python
def score_memory(memory, current_task):
    success_score = memory.get("score", 0)
    recency = recency_score(memory)
    return success_score * 0.7 + recency * 0.3
```

**Pros:**
- Learns from successful runs
- Avoids repeating failures
- Outcome-driven

**Cons:**
- May overfit to specific solutions
- Doesn't help with novel tasks
- Biased toward "easy" memories

#### Option D: Hybrid Scoring

Combine multiple signals:

```python
def score_memory(memory, current_task):
    # Base scores
    recency = recency_score(memory)
    similarity = task_similarity_score(memory, current_task)
    success = memory.get("score", 0)
    
    # Cross-domain penalty
    same_domain = memory["source_task"].split("_")[0] == current_task.split("_")[0]
    domain_factor = 1.0 if same_domain else 0.7
    
    # Memory type weights (some types transfer better)
    type_weights = {
        "errors": 1.0,       # Errors are universally useful
        "insights": 0.9,     # Insights transfer well
        "operations": 0.7,   # Tool patterns partially transfer
        "checkpoints": 0.5,  # Checkpoints are task-specific
        "trajectory": 0.3,   # Full trajectories rarely transfer
        "final_state": 0.6,  # Final state moderately useful
    }
    type_factor = type_weights.get(memory["type"], 0.5)
    
    return (
        0.25 * recency +
        0.35 * similarity +
        0.25 * success +
        0.15 * type_factor
    ) * domain_factor
```

**Pros:**
- Balanced approach
- Configurable weights
- Multiple relevance signals
- Handles cross-domain gracefully

**Cons:**
- More complex
- Need to tune weights
- More computation

**Decision:** [x] **Configurable (A + C + Explicit)**

**Rationale:** 
Provide user flexibility through configuration rather than hardcoding a single strategy.
Users can choose based on their use case:
- **Recency (default):** Good for iterative development, uses latest learnings
- **Success:** Good for production runs, prioritizes proven approaches
- **Explicit:** Good for controlled experiments, reproducible runs

**Configuration:**
```yaml
memory_config:
  historical:
    enabled: true
    
    # Selection strategy: "recent" | "successful" | "explicit"
    strategy: recent  # Default
    
    # For strategy: recent
    recent:
      max_evals: 5              # Load from N most recent evals
      max_age_days: 30          # Ignore evals older than this
    
    # For strategy: successful  
    successful:
      min_score: 0.7            # Minimum score threshold
      max_evals: 10             # Maximum evals to consider
      sort_by: score            # "score" or "recency"
    
    # For strategy: explicit
    explicit:
      eval_files:
        - logs/2026-01-23T22-39-10+00-00_excytin_erPasm6Z36cX8a43xF89n7.eval
        - logs/2026-01-22T19-41-27+00-00_excytin_ftgDY3Vd3R9vWbN8SAoLmv.eval
      # Or use patterns
      eval_patterns:
        - "logs/*_excytin_*.eval"  # All excytin evals
    
    # Common filters (apply to all strategies)
    filters:
      memory_types: [final_state, errors, operations]  # Types to load
      same_domain_only: false    # If true, only load from same domain
      min_score: 0.0             # Global minimum score filter
```

**Implementation:**
```python
class MemorySelector:
    """Select historical memories based on configured strategy."""
    
    def __init__(self, config: dict, eval_dir: Path):
        self.config = config
        self.eval_dir = eval_dir
        self.strategy = config.get("strategy", "recent")
    
    def select_eval_files(self) -> list[Path]:
        """Select eval files based on strategy."""
        if self.strategy == "explicit":
            return self._select_explicit()
        elif self.strategy == "successful":
            return self._select_successful()
        else:  # recent (default)
            return self._select_recent()
    
    def _select_recent(self) -> list[Path]:
        """Select most recent eval files."""
        cfg = self.config.get("recent", {})
        max_evals = cfg.get("max_evals", 5)
        max_age_days = cfg.get("max_age_days", 30)
        
        eval_files = sorted(
            self.eval_dir.glob("*.eval"),
            key=lambda p: p.stat().st_mtime,
            reverse=True  # Most recent first
        )
        
        # Filter by age
        cutoff = datetime.now() - timedelta(days=max_age_days)
        eval_files = [
            f for f in eval_files 
            if datetime.fromtimestamp(f.stat().st_mtime) > cutoff
        ]
        
        return eval_files[:max_evals]
    
    def _select_successful(self) -> list[Path]:
        """Select eval files with highest scores."""
        from inspect_ai.log import read_eval_log
        
        cfg = self.config.get("successful", {})
        min_score = cfg.get("min_score", 0.7)
        max_evals = cfg.get("max_evals", 10)
        
        scored_files = []
        for eval_file in self.eval_dir.glob("*.eval"):
            try:
                log = read_eval_log(str(eval_file), header_only=True)
                # Get average score from results
                scores = log.results.scores if log.results else []
                if scores:
                    avg_score = sum(s.value for s in scores) / len(scores)
                    if avg_score >= min_score:
                        scored_files.append((eval_file, avg_score))
            except Exception:
                continue
        
        # Sort by score descending
        scored_files.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in scored_files[:max_evals]]
    
    def _select_explicit(self) -> list[Path]:
        """Select explicitly specified eval files."""
        cfg = self.config.get("explicit", {})
        files = []
        
        # Direct file paths
        for path in cfg.get("eval_files", []):
            p = Path(path)
            if p.exists():
                files.append(p)
        
        # Glob patterns
        for pattern in cfg.get("eval_patterns", []):
            files.extend(self.eval_dir.glob(pattern))
        
        return list(set(files))  # Deduplicate
```

---

### DD-8: Agent Prompt Integration

**Question:** How should memory availability be communicated to the agent?

#### Option A: Implicit (Tool Discovery)

Agent discovers memory through tool list, no special prompting:

```python
tools = [bash(), python(), memory(initial_data=...)]
# Agent sees memory tool in available tools
```

**Pros:**
- No prompt changes needed
- Consistent with other tools
- Agent figures it out

**Cons:**
- Agent may not use effectively
- No guidance on memory structure
- May underutilize seeded content

#### Option B: Explicit Prompt Section

Add dedicated memory section to agent prompt:

```markdown
MEMORY SYSTEM:
You have access to a persistent memory system with the following pre-seeded knowledge:
- /memories/threat_intel.md: Known threat actors and IOCs
- /memories/query_patterns.md: Common investigation SQL queries

Use memory to:
1. Reference pre-seeded domain knowledge
2. Track your investigation findings
3. Note important discoveries for future steps

Memory operations:
- memory_read(path): Read memory content
- memory_write(path, content): Write/update memory
- memory_list(): List all memory paths
```

**Pros:**
- Clear guidance
- Agent knows what's available
- Better utilization

**Cons:**
- Prompt space overhead
- Need to update prompt when memory changes
- May be prescriptive

#### Option C: Dynamic Prompt Injection

Inject memory contents directly into prompt:

```markdown
PRE-LOADED KNOWLEDGE:
The following information has been pre-loaded for your reference:

## Threat Intelligence
{{ memory["/memories/threat_intel.md"] }}

## Query Patterns
{{ memory["/memories/query_patterns.md"] }}
```

**Pros:**
- No tool calls needed for seeds
- Immediate access
- Reduces back-and-forth

**Cons:**
- Uses context window
- Can't update during episode
- Duplicates tool functionality

**Decision:** [x] **Option B (Simplified)**  [ ] Option A  [ ] Option C

**Rationale:** 
- **Minimal context overhead** - Just mention that memory tool exists, not full path listing
- **Agent discovers structure** - Use `memory_list()` to explore available paths
- **Consistent with Claude memory** - Follows familiar pattern agents understand
- **No prompt updates needed** - Static description, dynamic discovery

**Prompt Addition:**
```markdown
MEMORY SYSTEM:
You have access to a persistent memory tool with a hierarchical directory structure.
Use memory_list() to see available paths, memory_read(path) to read content,
and memory_write(path, content) to store findings. Pre-seeded knowledge and
historical learnings may be available - check memory_list() at the start.
```

**Implementation:**
```python
MEMORY_PROMPT_SECTION = """
MEMORY SYSTEM:
You have access to a persistent memory tool with a hierarchical directory structure.
Use memory_list() to see available paths, memory_read(path) to read content,
and memory_write(path, content) to store findings. Pre-seeded knowledge and
historical learnings may be available - check memory_list() at the start.
"""

def get_agent_prompt(base_prompt: str, memory_enabled: bool) -> str:
    """Add memory section to agent prompt if enabled."""
    if memory_enabled:
        return base_prompt + "\n" + MEMORY_PROMPT_SECTION
    return base_prompt
```

---

### DD-9: Multi-Agent Memory Sharing

**Question:** How should memory be shared between agents in multi-agent scenarios?

#### Option A: No Sharing (Isolated)

Each agent has its own memory space:

```
Agent A: /memories/a/notes.md
Agent B: /memories/b/notes.md
```

**Pros:**
- Simple implementation
- No coordination needed
- Clear ownership

**Cons:**
- No collaboration benefit
- Duplicate discoveries
- Missed synergies

#### Option B: Shared Namespace

All agents share memory namespace:

```
All Agents: /memories/shared/notes.md
```

**Pros:**
- True collaboration
- Immediate knowledge sharing
- Single source of truth

**Cons:**
- Race conditions
- Conflict resolution needed
- Attribution unclear

#### Option C: Publish/Subscribe

Agents publish to personal space, subscribe to others:

```
Agent A writes: /memories/a/findings.md
Agent B subscribes: /memories/a/findings.md (read-only)
```

**Pros:**
- Clear ownership
- Controlled sharing
- No conflicts

**Cons:**
- More complex model
- Subscription management
- Delayed visibility

#### Option D: Shared + Personal

Hybrid with personal and shared spaces:

```
Personal: /memories/agent_a/notes.md
Shared:   /memories/shared/findings.md
```

**Pros:**
- Flexibility
- Private scratchpad + shared knowledge
- Balanced approach

**Cons:**
- More complex
- Need to decide what goes where
- Potential duplication

**Decision:** [x] **Option A (Isolated)**  [ ] Option B  [ ] Option C  [ ] Option D

**Rationale:** 
- **SABER is single-agent** - No multi-agent scenarios planned
- **Simplest implementation** - No coordination, no race conditions
- **No overhead** - No need for complex sharing logic
- **Revisit if needed** - Can upgrade to Option D (Hybrid) if multi-agent is ever added

> **Note:** Multi-agent memory sharing is out of scope for the foreseeable future.
> This decision can be revisited if SABER adds multi-agent support.

---

### DD-10: Sensitive Data Handling

**Question:** How should sensitive data in memories be handled for cross-run/cross-domain transfer?

#### Option A: No Filtering

Transfer all memory content as-is:

**Pros:**
- Simple
- No data loss
- Full context preserved

**Cons:**
- Privacy risks
- May leak credentials/PII
- Compliance concerns

#### Option B: Pattern-Based Redaction

Redact known sensitive patterns:

```python
SENSITIVE_PATTERNS = [
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
    r'password[=:]\s*\S+',     # Passwords
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
]
```

**Pros:**
- Automated protection
- Known patterns caught
- Configurable

**Cons:**
- May miss novel patterns
- False positives
- Maintenance burden

#### Option C: LLM-Based Sanitization

Use LLM to identify and redact sensitive content:

```python
def sanitize_memory(content: str) -> str:
    return llm_call(
        "Identify and redact any sensitive information (passwords, "
        "PII, credentials) from this content, replacing with [REDACTED]",
        content
    )
```

**Pros:**
- Intelligent detection
- Catches novel patterns
- Context-aware

**Cons:**
- LLM cost
- Latency
- May be overly aggressive

#### Option D: Category-Based Persistence

Only persist non-sensitive memory categories:

```yaml
persistence:
  allowed_categories:
    - techniques
    - tool_patterns
    - general_findings
  blocked_categories:
    - credentials
    - raw_data
    - pii
```

**Pros:**
- Clear policy
- No analysis needed
- Predictable

**Cons:**
- Requires categorization
- May miss valuable content
- Agent must categorize correctly

**Decision:** [x] **Option A (No Filtering)**  [ ] Option B  [ ] Option C  [ ] Option D

**Rationale:** 
- **Benchmarking framework** - SABER is not a production system, no real user data
- **Synthetic data** - Domains use simulated/synthetic data, not real PII
- **Controlled environment** - Evals run in isolated environments
- **Simplicity** - No filtering logic to maintain
- **Revisit if needed** - Can add pattern-based filtering later if real data concerns arise

> **Phase 1 Access Policy:** Only local eval files are accessible.
> Memory extraction is limited to `.eval` files stored in the local `logs/` directory.
> No remote storage (S3, GCS, etc.) access in Phase 1.

---

### DD-11: Memory Initialization Timing

**Question:** When should memory be initialized and loaded during the task lifecycle?

#### Option A: Eager Loading (At Task Start)

Load all memory (seeds + historical) before the first agent step:

```python
def create_task():
    memory_data = load_all_memory()  # Blocking
    tools = [bash(), python(), memory(initial_data=memory_data)]
    return Task(solver=react(tools=tools), ...)
```

**Pros:**
- Simple mental model
- Memory always available
- No async complexity

**Cons:**
- Slower task startup
- May load unused memories
- Blocks on I/O

#### Option B: Lazy Loading (On First Access)

Load memory content when first accessed:

```python
class LazyMemory:
    def read(self, path):
        if path not in self._cache:
            self._cache[path] = self._load(path)
        return self._cache[path]
```

**Pros:**
- Fast startup
- Only loads what's needed
- Better for large memory sets

**Cons:**
- First access has latency
- More complex implementation
- Harder to debug

#### Option C: Background Loading

Start loading in background, block only if accessed before ready:

```python
async def create_task():
    memory_future = asyncio.create_task(load_all_memory())
    # ... other setup ...
    memory_data = await memory_future  # Wait if not ready
```

**Pros:**
- Parallel with other setup
- No wasted startup time
- Best of both worlds

**Cons:**
- Async complexity
- Race condition potential
- Harder to debug

**Decision:** [x] **Option A (Eager Loading)**  [ ] Option B  [ ] Option C

**Rationale:** 
- **Simplicity** - Easy to understand and debug
- **Inspect AI API** - `memory(initial_data=...)` expects data at tool creation time
- **Small memory sizes** - With DD-6 limits (100KB/path, 1MB total), loading is fast
- **DD-7 limits scope** - Max 5-10 eval files, minimal I/O overhead
- **Predictable** - Memory is always ready when agent starts

---

### DD-12: Memory vs Context Window Trade-off

**Question:** How should we balance between storing information in memory (tool-accessible) vs including it directly in the prompt context?

#### Option A: Memory-First

All domain knowledge goes to memory, minimal prompt:

```markdown
# Agent Prompt
You have access to memory tool with pre-seeded knowledge.
Use memory_read() to access domain information.
```

**Pros:**
- Keeps prompt small
- Agent decides what to read
- Scales to large knowledge bases

**Cons:**
- Extra tool calls
- Agent may not know what's available
- Slower if agent needs everything

#### Option B: Context-First

Critical knowledge in prompt, memory for notes only:

```markdown
# Agent Prompt
## Domain Knowledge
{{ threat_intel }}
{{ query_patterns }}

Use memory tool for your investigation notes.
```

**Pros:**
- Agent has immediate access
- No tool calls for seeds
- Better for small knowledge sets

**Cons:**
- Uses context window
- Can't update during episode
- Doesn't scale

#### Option C: Tiered Approach

Critical info in prompt, detailed info in memory:

```markdown
# Agent Prompt
## Quick Reference
- Manatee Tempest: ransomware group, C2 at vectorsandarrows.com
- Storm-0875: credential theft via Mimikatz

For detailed information, see /memories/threat_intel.md
```

**Pros:**
- Balanced approach
- Key info immediately available
- Details accessible when needed

**Cons:**
- Need to decide what's "critical"
- Potential duplication
- More complex prompts

**Decision:** [x] **Option A (Memory-First)**  [ ] Option B  [ ] Option C

**Rationale:** 
- **Aligns with DD-8** - Agent discovers memory via `memory_list()`, not prompt injection
- **Consistent UX** - All knowledge in one place (memory), no split
- **Scales** - Works whether we have 1KB or 1MB of seeds
- **Agent autonomy** - Agent decides what it needs, when it needs it
- **Simpler prompts** - No templating knowledge into prompts
- **No duplication** - Single source of truth in memory

---

### DD-13: Memory and Checkpoint Evaluation Integration

**Question:** How should memory interact with the checkpoint/subtask evaluation system in SABER?

#### Option A: Memory Ignored by Checkpoints

Checkpoints evaluate agent actions only, not memory state:

```yaml
checkpoint_1:
  evaluation:
    # Only looks at agent messages/actions
    strategy: llm_judge
```

**Pros:**
- Simple integration
- No checkpoint changes needed
- Memory is internal tool

**Cons:**
- Can't reward good note-taking
- Miss memory-related behaviors
- No visibility into memory usage

#### Option B: Memory as Checkpoint Evidence

Checkpoints can access memory state as additional context:

```yaml
checkpoint_1:
  evaluation:
    strategy: llm_judge
    include_memory: true  # Pass memory state to judge
```

**Pros:**
- Judge sees agent's notes
- Can evaluate reasoning quality
- Better understanding of agent behavior

**Cons:**
- More complex checkpoint config
- Judge prompt complexity
- May bias scoring

#### Option C: Memory-Based Checkpoints

Some checkpoints specifically evaluate memory content:

```yaml
checkpoint_memory:
  type: memory_checkpoint
  criteria:
    path: "/memories/findings.md"
    must_contain: ["198.43.121.209", "Manatee Tempest"]
```

**Pros:**
- Explicit memory requirements
- Can guide agent behavior
- Measurable memory usage

**Cons:**
- Prescriptive
- May encourage gaming
- New checkpoint type needed

**Decision:** [x] **Option A (Memory Ignored)**  [ ] Option B  [ ] Option C

**Rationale:** 
- **Decoupled concerns** - Memory access ≠ evaluation criteria
- **No checkpoint changes** - Existing SABER checkpoint system works as-is
- **Outcome-focused** - Evaluate task outcomes, not note-taking behavior
- **Avoid gaming** - Agents shouldn't optimize memory usage over task completion
- **Simplicity** - No additional checkpoint configuration needed

---

### DD-14: Eval Reproducibility with Historical Memory

**Question:** How do we maintain eval reproducibility when loading historical memories that may change over time?

#### Option A: No Reproducibility Guarantee

Accept that historical memory makes evals non-deterministic:

```yaml
memory_config:
  historical:
    enabled: true
    # Note: Results may vary based on available history
```

**Pros:**
- Simple implementation
- Reflects real-world learning
- No extra storage

**Cons:**
- Can't reproduce results
- Hard to debug regressions
- A/B testing difficult

#### Option B: Snapshot Historical Memory

Capture and store the exact historical memory used:

```json
{
  "eval": {
    "memory_snapshot": {
      "historical_sources": ["eval_abc123.eval", "eval_def456.eval"],
      "loaded_memories": {...}
    }
  }
}
```

**Pros:**
- Full reproducibility
- Can replay exact conditions
- Debug-friendly

**Cons:**
- Storage overhead
- Complexity in .eval format
- Snapshot management

#### Option C: Versioned Memory Sets

Maintain versioned memory snapshots:

```yaml
memory_config:
  historical:
    enabled: true
    version: "v2024.01"  # Use specific memory version
```

**Pros:**
- Controlled reproducibility
- Named versions for reference
- Can compare across versions

**Cons:**
- Version management overhead
- Need to create/maintain versions
- Storage for all versions

**Decision:** [x] **Option A (No Reproducibility Guarantee)**  [ ] Option B  [ ] Option C

**Rationale:** 
- **User's responsibility** - Reproducibility burden is on the user, not SABER
- **Don't alter .eval format** - It's an Inspect AI standard, we should not modify it
- **DD-7 explicit mode** - Users can use `strategy: explicit` to specify exact eval files
- **External static sets** - For reproducibility, users can load from cloud storage with
  fixed memory sets (outside SABER scope)
- **Simplicity** - No snapshot management or storage overhead

> **Future: External .eval Repository**
> 
> SABER will provide a cloud storage repository with curated .eval files for reproducible
> benchmarking in a later phase. This will include:
> - Versioned memory sets for each domain
> - Pre-extracted memories from high-quality runs
> - Standard baselines for comparison
>
> This is outside Phase 1 scope but planned for future releases.

**Reproducibility guidance for users:**
```yaml
# For reproducible runs, use explicit strategy with fixed sources:
memory_config:
  historical:
    strategy: explicit
    explicit:
      eval_files:
        - s3://my-bucket/fixed-memory-sets/v1/eval1.eval
        - s3://my-bucket/fixed-memory-sets/v1/eval2.eval
      # Or use local copies of a fixed set
      eval_patterns:
        - "memory_sets/v1/*.eval"

# For exploratory runs, use recent (default) - not reproducible:
memory_config:
  historical:
    strategy: recent  # Loads from local logs/, may change over time
```

---

### DD-15: Memory Content Validation

**Question:** Should memory content be validated, and how should malformed content be handled?

#### Option A: No Validation

Accept any content the agent writes:

```python
def memory_write(path: str, content: str):
    self.data[path] = content  # Store as-is
```

**Pros:**
- Simple implementation
- Maximum flexibility
- No overhead

**Cons:**
- Agent can write garbage
- May break downstream processing
- No quality assurance

#### Option B: Format Validation

Validate content matches expected format (markdown, JSON, etc.):

```python
def memory_write(path: str, content: str):
    if path.endswith('.md'):
        validate_markdown(content)
    elif path.endswith('.json'):
        validate_json(content)
    self.data[path] = content
```

**Pros:**
- Ensures parseable content
- Catches obvious errors
- Enables downstream processing

**Cons:**
- Overhead per write
- May reject valid content
- Format detection complexity

#### Option C: Schema Validation

Validate against defined schemas:

```yaml
memory_config:
  validation:
    "/memories/findings.md":
      schema: findings_schema.json
    "/memories/notes.md":
      schema: null  # No validation
```

**Pros:**
- Strict content control
- Enables typed memory
- Better for structured data

**Cons:**
- Schema maintenance
- Reduced flexibility
- Complex configuration

#### Option D: Post-Episode Validation

Validate only when persisting to .eval:

```python
def persist_memory(memory_state: dict):
    for path, content in memory_state.items():
        if not validate(path, content):
            log_warning(f"Invalid memory at {path}")
            memory_state[path] = sanitize(content)
```

**Pros:**
- No runtime overhead
- Catches issues before persistence
- Can sanitize/fix

**Cons:**
- Late error detection
- May lose context for fixes
- Validation separate from usage

**Decision:** [x] **Option A (No Validation)**  [ ] Option B  [ ] Option C  [ ] Option D

**Rationale:** 
- **Memory is agent's scratchpad** - Let the agent use it however it wants
- **Inspect AI memory tool** - Underlying tool handles storage, we pass through
- **No downstream processing** - We don't parse memory content programmatically (DD-13)
- **Simplicity** - No validation logic to maintain
- **Agent autonomy** - Constraining writes could hurt flexibility
- **DD-4 extraction handles it** - We just take raw content when extracting

---

## 5. Memory Types

### 5.1 Static Seeded Memory
Pre-defined knowledge loaded at agent initialization.

**Sources:**
- Inline YAML configuration
- Markdown/text files in `config/seeds/`
- Domain-specific threat intelligence
- Tool usage examples and patterns

**Example Configuration:**
```yaml
memory_config:
  seeds:
    static:
      - path: "/memories/threat_intel.md"
        source: "seeds/threat_intelligence.md"
      - path: "/memories/tool_patterns.md"
        source: "seeds/common_queries.md"
      - path: "/memories/notes.md"
        content: ""  # Empty, agent-writable
```

### 5.2 Task-Specific Seeds
Memory content specific to a task or incident type.

```yaml
# incident_5_1.yaml
tasks:
  - task_id: incident_5_task_1
    memory_config:
      seeds:
        task:
          - path: "/memories/incident_context.md"
            content: |
              ## Known Context for Incident 5
              - Manatee Tempest activity group
              - C2 domain: vectorsandarrows.com
```

### 5.3 Historical Memory (from .eval files)
Loaded from previous evaluation runs.

**Memory Extraction Pipeline:**
```
.eval file → Parse episodes → Extract memory operations 
           → Filter relevant memories → Inject as seeds
```

### 5.4 Cross-Domain Memory
Knowledge transfer between different SABER domains.

```yaml
memory_config:
  cross_domain:
    enabled: true
    sources:
      - domain: "cybench"
        eval_path: "logs/cybench_*.eval"
        filter:
          - type: "technique"
          - type: "tool_pattern"
```

## 6. Implementation Phases

### Phase 1: Memory System Foundation (MVP)
**Goal:** Enable pre-populated memory with static seeds AND historical memory extraction

**Components:**
1. Memory configuration schema in YAML
2. Memory resolver in tool pipeline
3. Integration with `inspect_ai.tool.memory()`
4. **Historical memory extraction using Inspect AI Log API**
5. **Modular memory type extractors**

**Deliverables:**
- `saber/inspect_ai/tools/memory_resolver.py`
- `saber/inspect_ai/memory/extractor.py` - Memory extraction from .eval files
- `saber/inspect_ai/memory/types.py` - Memory type definitions
- Updated `global.yaml` schema with memory configuration
- Documentation and examples

**Memory Types Implemented:**
- [x] `final_state` - Final memory paths at episode end
- [x] `operations` - All tool calls with results
- [x] `checkpoints` - State at checkpoint completions  
- [x] `errors` - Failed operations and resolutions
- [x] `trajectory` - Full agent trajectory with thoughts
- [ ] `insights` - LLM-summarized learnings (optional, requires LLM)

**Acceptance Criteria:**
- [ ] Memory tool appears in agent tool list
- [ ] Seeds load from YAML configuration
- [ ] Seeds load from external files
- [ ] Agent can read/write to memory paths
- [ ] Memory persists across steps within episode
- [ ] **Can extract memories from existing .eval files**
- [ ] **Memory types are modular and configurable**
- [ ] **Historical memories can be loaded into new runs**

### Phase 2: Episode Persistence & Auto-Extraction
**Goal:** Automatically extract and store memories from completed episodes

**Components:**
1. Memory extraction hooks in episode lifecycle
2. Automatic extraction on eval completion
3. Memory storage in .eval file metadata
4. Memory aggregation across runs

**Deliverables:**
- Episode lifecycle hooks for memory extraction
- Auto-extraction configuration
- .eval file schema extension for embedded memory
- Memory aggregation utilities

**Acceptance Criteria:**
- [ ] Memories auto-extracted on eval completion
- [ ] Memory operations logged with timestamps
- [ ] Memory metadata (read/write counts) captured
- [ ] Aggregated memories stored for future runs

### Phase 3: Intelligent Memory Selection
**Goal:** Smart selection of relevant historical memories

**Components:**
1. Relevance scoring algorithms
2. Memory deduplication
3. Context-aware memory selection
4. Memory size optimization

**Deliverables:**
- Relevance scoring implementation
- Deduplication algorithms
- Memory selection strategies
- Size management utilities

**Acceptance Criteria:**
- [ ] Relevance scoring filters memories effectively
- [ ] Duplicate memories detected and merged
- [ ] Memory selection improves agent performance
- [ ] Memory size stays within limits

### Phase 4: Cross-Domain Transfer
**Goal:** Enable knowledge transfer between domains

**Components:**
1. Universal memory format
2. Domain-agnostic memory categories
3. Cross-domain memory resolver
4. LLM-based insight extraction

**Deliverables:**
- Cross-domain memory schema
- Domain mapping configuration
- Transfer validation tools
- `insights` memory type with LLM summarization

**Acceptance Criteria:**
- [ ] Memories transferable between domains
- [ ] Domain-specific content filtered
- [ ] LLM insights extraction working
- [ ] Transfer improves agent performance

## 7. Dependencies & Prerequisites

### 7.1 Inspect AI Dependencies

**Required:** Understanding of `inspect_ai.tool.memory()` API and `inspect_ai.log` API

#### Memory Tool API

| Aspect | Status | Notes |
|--------|--------|-------|
| Memory tool availability | ✅ Confirmed | Available in inspect_ai |
| `initial_data` parameter | ✅ Confirmed | Accepts dict of path→content |
| `memory_read()` function | ❓ To verify | Agent-facing read API |
| `memory_write()` function | ❓ To verify | Agent-facing write API |
| `memory_list()` function | ❓ To verify | Agent-facing list API |
| Memory state extraction | ❓ To verify | Can we get final state from tool? |
| Memory operation hooks | ❓ To verify | Can we intercept read/write? |

#### Inspect AI Log API (✅ Verified)

| Aspect | Status | Notes |
|--------|--------|-------|
| `read_eval_log()` function | ✅ Confirmed | Reads .eval files |
| `header_only` parameter | ✅ Confirmed | Fast header-only reads |
| `log.eval` metadata | ✅ Confirmed | Task, model, timestamps |
| `log.samples` list | ✅ Confirmed | All sample data |
| `sample.events` list | ✅ Confirmed | Full event stream |
| `sample.scores` dict | ✅ Confirmed | Scoring results with metadata |
| `sample.store` dict | ✅ Confirmed | Key-value store state |
| Event type: `model` | ✅ Confirmed | `output.completion` for agent thinking |
| Event type: `tool` | ✅ Confirmed | `function`, `arguments`, `result`, `error` |
| Event type: `score` | ✅ Confirmed | Scoring events |
| CLI: `inspect log dump` | ✅ Confirmed | JSON output, header-only option |
| CLI: `inspect log list` | ✅ Confirmed | List available logs |

**Usage Example:**
```python
from inspect_ai.log import read_eval_log

# Read full log
log = read_eval_log("path/to/file.eval")

# Access samples
for sample in log.samples:
    print(f"Sample: {sample.id}")
    print(f"Score: {sample.scores.get('saber_scorer', {}).value}")
    
    # Access events
    for event in sample.events:
        if event.event == "model":
            print(f"Thought: {event.output.completion[:100]}...")
        elif event.event == "tool":
            print(f"Tool: {event.function}({event.arguments})")
```

**Action Items:**
- [x] ~~Review Inspect AI memory tool source code~~
- [x] ~~Verify .eval file reading API~~ → Using `inspect_ai.log.read_eval_log()`
- [ ] Verify all agent-facing memory operations
- [ ] Determine if we can hook into memory operations for logging
- [ ] Check if memory tool supports custom backends

### 7.2 SABER Framework Dependencies

| Component | Dependency | Notes |
|-----------|------------|-------|
| Tool Resolver | Modify existing | Add memory tool to resolution |
| Task Factory | Modify existing | Pass memory config |
| Episode Lifecycle | Extend | Add memory extraction hooks |
| .eval Format | Extend schema | Add memory section |
| YAML Parser | Extend schema | Add memory_config parsing |

### 7.3 External Dependencies

| Dependency | Phase | Purpose |
|------------|-------|----------|
| None | Phase 1 | Static seeds only |
| .eval parser | Phase 2 | Extract memory from evals |
| Embedding model (optional) | Phase 4 | Semantic memory search |
| LLM for summarization (optional) | Phase 3+ | Memory summarization |

### 7.4 Backward Compatibility

**Constraint:** Existing domains without memory config must continue to work.

```python
# Memory should be opt-in
if config.memory_config and config.memory_config.enabled:
    tools.append(memory_tool)
# Else: no memory tool, existing behavior preserved
```

## 8. Configuration Schema

```yaml
# Full memory configuration schema
memory_config:
  # Enable/disable memory system
  enabled: true
  
  # Static seeds loaded at initialization
  seeds:
    # Global seeds (all tasks)
    global:
      - path: "/memories/domain_knowledge.md"
        source: "seeds/domain_knowledge.md"
      - path: "/memories/notes.md"
        content: ""
    
    # Task-specific seeds (merged with global)
    task: []  # Defined per-task
  
  # Historical memory loading
  historical:
    enabled: false  # Phase 2+
    
    # Same-domain memory
    same_domain:
      enabled: true
      eval_pattern: "logs/${domain}_*.eval"
      max_evals: 5
      recency_weight: 0.8
    
    # Cross-domain memory
    cross_domain:
      enabled: false
      sources: []
  
  # Memory persistence settings
  persistence:
    # Save memories to .eval file
    save_to_eval: true
    
    # Memory categories to persist
    categories:
      - findings
      - techniques
      - tool_patterns
      - errors_learned
  
  # Memory size limits (see DD-6)
  limits:
    max_size_per_path: 50KB
    max_total_size: 500KB
    behavior_on_limit: truncate_oldest
```

## 8. Memory Resolver Implementation

```python
# filepath: external/saber/src/saber/inspect_ai/tools/memory_resolver.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from inspect_ai.tool import memory, Tool

@dataclass
class MemoryConfig:
    enabled: bool = True
    seeds: dict = field(default_factory=dict)
    historical: dict = field(default_factory=dict)
    persistence: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

class MemoryResolver:
    """Resolves and initializes memory for SABER agents."""
    
    def __init__(
        self,
        config: MemoryConfig,
        domain: str,
        task_id: str,
        config_root: Path,
    ):
        self.config = config
        self.domain = domain
        self.task_id = task_id
        self.config_root = config_root
    
    def resolve(self) -> Optional[Tool]:
        """Resolve memory tool with all configured data."""
        if not self.config.enabled:
            return None
        
        initial_data = {}
        
        # Phase 1: Load static seeds
        initial_data.update(self._load_static_seeds())
        
        # Phase 1: Load task-specific seeds
        initial_data.update(self._load_task_seeds())
        
        # Phase 3+: Load historical memories
        if self.config.historical and self.config.historical.get("enabled"):
            initial_data.update(self._load_historical_memories())
        
        return memory(initial_data=initial_data)
    
    def _load_static_seeds(self) -> dict:
        """Load static seed files."""
        seeds = {}
        global_seeds = self.config.seeds.get("global", [])
        
        for seed in global_seeds:
            path = seed["path"]
            if "content" in seed:
                seeds[path] = seed["content"]
            elif "source" in seed:
                source_path = self.config_root / seed["source"]
                if source_path.exists():
                    seeds[path] = source_path.read_text()
                else:
                    # Log warning about missing seed file
                    pass
        
        return seeds
    
    def _load_task_seeds(self) -> dict:
        """Load task-specific seeds."""
        seeds = {}
        task_seeds = self.config.seeds.get("task", [])
        
        for seed in task_seeds:
            path = seed["path"]
            if "content" in seed:
                seeds[path] = seed["content"]
            elif "source" in seed:
                source_path = self.config_root / seed["source"]
                if source_path.exists():
                    seeds[path] = source_path.read_text()
        
        return seeds
    
    def _load_historical_memories(self) -> dict:
        """Load memories from previous .eval files."""
        # Phase 3+ implementation
        memories = {}
        
        # Get eval files matching pattern
        eval_pattern = self.config.historical.get(
            "same_domain", {}
        ).get("eval_pattern", "")
        
        if not eval_pattern:
            return memories
        
        # TODO: Implement eval file parsing and memory extraction
        # - Find matching .eval files
        # - Extract memory states
        # - Score for relevance
        # - Merge into initial_data
        
        return memories
```

## 9. Integration Points

### 9.1 Tool Pipeline Integration
```python
# In saber/inspect_ai/tools/tool_resolver.py
def resolve_tools(config: TaskConfig) -> list[Tool]:
    tools = []
    
    # Existing tool resolution
    tools.extend(resolve_executor_tools(config.execution_config))
    
    # Memory tool resolution
    if config.memory_config and config.memory_config.enabled:
        memory_resolver = MemoryResolver(
            config=config.memory_config,
            domain=config.domain,
            task_id=config.task_id,
            config_root=config.config_root,
        )
        memory_tool = memory_resolver.resolve()
        if memory_tool:
            tools.append(memory_tool)
    
    return tools
```

### 9.2 Agent Prompt Integration
Update agent prompts to reference memory:

```markdown
# In excytin_demo.md
AVAILABLE TOOLS:
- bash: Execute shell commands
- python: Execute Python code
- memory: Store and retrieve investigation notes
  - Use memory to track findings, theories, and progress
  - Memory persists across your investigation steps
  - Pre-seeded with domain knowledge in /memories/

MEMORY USAGE:
- Read: memory_read(path="/memories/notes.md")
- Write: memory_write(path="/memories/notes.md", content="...")
- List: memory_list()

PRE-SEEDED MEMORY LOCATIONS:
- /memories/threat_intel.md: Known threat actors and IOCs
- /memories/query_patterns.md: Common SQL investigation queries
- /memories/notes.md: Your investigation notes (empty, use this!)
```

### 9.3 Quick Start: Domain-Level Implementation

For immediate use without framework changes:

```python
# filepath: domains/excytin/client/agents/react_with_memory.py
"""React agent with seeded memory for Excytin domain."""

from inspect_ai.solver import Solver, solver
from inspect_ai.agent import react
from inspect_ai.tool import bash, python, memory
from pathlib import Path


def load_seed_file(filename: str) -> str:
    """Load seed content from domain seeds directory."""
    seeds_dir = Path(__file__).parent.parent.parent / "server/config/seeds"
    seed_path = seeds_dir / filename
    if seed_path.exists():
        return seed_path.read_text()
    return ""


@solver
def react_with_memory(
    timeout: int = 180,
    max_steps: int = 15,
) -> Solver:
    """React agent with pre-seeded memory."""
    
    # Initialize memory with domain knowledge
    initial_memory = {
        "/memories/notes.md": "# Investigation Notes\n\n",
        "/memories/findings.md": "# Key Findings\n\n",
        "/memories/threat_intel.md": load_seed_file("threat_intel.md"),
        "/memories/query_patterns.md": load_seed_file("query_patterns.md"),
    }
    
    tools = [
        bash(timeout=timeout),
        python(timeout=timeout),
        memory(initial_data=initial_memory),
    ]
    
    return react(
        tools=tools,
        max_steps=max_steps,
    )
```

Run with:
```bash
inspect eval domains/excytin -T agent=react_with_memory
```

## 10. .eval File Memory Format

```json
{
  "eval": {
    "task": "incident_5_task_1",
    "domain": "excytin",
    "run_id": "abc123"
  },
  "samples": [
    {
      "id": "sample_1",
      "memory": {
        "initial_state": {
          "/memories/threat_intel.md": "# Threat Intel...",
          "/memories/notes.md": ""
        },
        "final_state": {
          "/memories/notes.md": "## Investigation Notes\n- Found C2 at ...",
          "/memories/findings.md": "## Key Findings\n1. IP: 198.43.121.209"
        },
        "operations": [
          {"step": 1, "type": "read", "path": "/memories/threat_intel.md", "timestamp": "2026-01-24T10:00:01Z"},
          {"step": 3, "type": "write", "path": "/memories/notes.md", "timestamp": "2026-01-24T10:00:15Z"},
          {"step": 5, "type": "read", "path": "/memories/notes.md", "timestamp": "2026-01-24T10:00:30Z"},
          {"step": 7, "type": "write", "path": "/memories/findings.md", "timestamp": "2026-01-24T10:00:45Z"}
        ],
        "metadata": {
          "total_reads": 5,
          "total_writes": 8,
          "paths_accessed": ["/memories/threat_intel.md", "/memories/notes.md", "/memories/findings.md"],
          "final_score": 0.85
        }
      }
    }
  ]
}
```

## 11. Example: Seeded Memory for Excytin

### Seed File: Threat Intelligence

```markdown
# filepath: domains/excytin/server/config/seeds/threat_intel.md
# Excytin Threat Intelligence Database

## Known Threat Actors

### Manatee Tempest
- **Type:** Ransomware/Extortion group
- **Known IOCs:**
  - Domain: vectorsandarrows.com
  - Common IPs: Check ThreatIntel table
- **TTPs:**
  - Initial Access: Phishing, Exploitation
  - Execution: PowerShell, cmd.exe
  - C2: HTTP-based communication

### Storm-0875
- **Type:** Credential Theft
- **Tools:**
  - Mimikatz (mimikatz.exe, mimidrv.sys, mimispool.dll)
  - Custom credential harvesters
- **Objectives:** Lateral movement, privilege escalation

## Common Investigation Queries

### Find C2 Communications
```sql
SELECT * FROM NetworkConnections 
WHERE RemoteUrl LIKE '%vectorsandarrows%';
```

### Find Process Executions
```sql
SELECT * FROM ProcessEvents 
WHERE ProcessCommandLine LIKE '%mimikatz%';
```

## Investigation Methodology
1. Identify affected hosts from alerts
2. Trace process trees for suspicious activity
3. Correlate network connections with known IOCs
4. Identify lateral movement patterns
5. Document timeline of compromise
```

### Seed File: Query Patterns

```markdown
# filepath: domains/excytin/server/config/seeds/query_patterns.md
# Common SQL Query Patterns for Security Investigation

## Schema Discovery
```sql
-- List all tables
SHOW TABLES;

-- Describe table structure
DESCRIBE TableName;

-- Count records
SELECT COUNT(*) FROM TableName;
```

## Alert Investigation
```sql
-- Get alerts for a device
SELECT * FROM Alerts WHERE DeviceName = 'hostname';

-- Get alerts by severity
SELECT * FROM Alerts WHERE Severity = 'High' ORDER BY Timestamp DESC;

-- Get alerts by category
SELECT * FROM Alerts WHERE Category = 'Malware';
```

## Process Analysis
```sql
-- Find process by name
SELECT * FROM ProcessEvents WHERE FileName LIKE '%mimikatz%';

-- Get process tree
SELECT * FROM ProcessEvents WHERE ParentProcessId = 1234;

-- Find suspicious command lines
SELECT * FROM ProcessEvents 
WHERE ProcessCommandLine LIKE '%powershell%' 
  AND ProcessCommandLine LIKE '%encoded%';
```

## Network Analysis
```sql
-- Find connections to IP
SELECT * FROM NetworkConnections WHERE RemoteIP = '1.2.3.4';

-- Find connections by port
SELECT * FROM NetworkConnections WHERE RemotePort = 443;

-- Find DNS queries
SELECT * FROM DnsEvents WHERE QueryName LIKE '%suspicious%';
```
```

## 12. Risks & Concerns

### 12.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Inspect AI memory API changes | Medium | High | Pin versions, abstract behind wrapper |
| Memory size causes OOM | Low | High | Implement size limits (DD-6) |
| Slow memory loading delays tasks | Medium | Medium | Lazy/background loading (DD-11) |
| .eval file size bloat | Medium | Low | Compress memory content |
| Memory corruption from agent | Low | Medium | Validation (DD-15) |

### 12.2 Architectural Concerns

**Concern 1: Memory vs Transcript Overlap**
- SABER has a transcript system for agent communication
- How does memory differ from transcript?
- Should they share infrastructure?

**Concern 2: Memory Tool vs Custom Tools**
- Domains may have existing note-taking tools
- How to migrate/coexist with memory tool?
- Should memory be the standard, or optional enhancement?

**Concern 3: Agent Over-reliance on Memory**
- Agent might read memory instead of exploring
- Could create echo chambers from historical memory
- Need to measure if memory helps or hurts

**Concern 4: Memory Debugging Complexity**
- When agent fails, was it memory-related?
- How to inspect memory state during debugging?
- Need tooling for memory inspection

### 12.3 Operational Concerns

**Concern 5: Memory Storage Growth**
- Historical memories accumulate over time
- Need retention policy or cleanup
- Cross-domain transfer multiplies storage

**Concern 6: Memory Security**
- Memories may contain sensitive investigation data
- Cross-run transfer could leak between users
- Need clear security model

**Concern 7: Memory Performance Impact**
- Every memory operation adds latency
- Historical memory loading at scale
- Need performance benchmarks

### 12.4 Product Concerns

**Concern 8: User Understanding**
- Memory is invisible to benchmark users
- How do users know memory is being used?
- Need documentation and observability

**Concern 9: Fair Comparison**
- Agents with historical memory vs without
- How to ensure fair benchmarking?
- Need clear disclosure of memory usage

## 13. Testing Strategy

### 13.1 Unit Tests

```python
# Test: Memory resolver loads seeds correctly
def test_memory_resolver_loads_seeds():
    config = MemoryConfig(
        enabled=True,
        seeds={"global": [{"path": "/memories/test.md", "content": "test"}]}
    )
    resolver = MemoryResolver(config, domain="test", task_id="t1", config_root=Path("."))
    tool = resolver.resolve()
    assert tool is not None
    # Verify initial_data contains our seed

# Test: Memory resolver handles missing files gracefully
def test_memory_resolver_missing_file():
    config = MemoryConfig(
        enabled=True,
        seeds={"global": [{"path": "/memories/test.md", "source": "nonexistent.md"}]}
    )
    resolver = MemoryResolver(config, domain="test", task_id="t1", config_root=Path("."))
    tool = resolver.resolve()  # Should not raise
    # Verify warning logged or empty content

# Test: Memory disabled returns None
def test_memory_disabled():
    config = MemoryConfig(enabled=False)
    resolver = MemoryResolver(config, domain="test", task_id="t1", config_root=Path("."))
    assert resolver.resolve() is None
```

### 13.2 Integration Tests

```python
# Test: Agent can use memory tool in episode
def test_agent_memory_integration():
    # Run a minimal task with memory tool
    # Verify agent can read seeded content
    # Verify agent can write new content
    # Verify memory persists across steps
    pass

# Test: Memory state captured in .eval
def test_memory_in_eval_output():
    # Run task to completion
    # Parse resulting .eval file
    # Verify memory section exists with final state
    pass
```

### 13.3 End-to-End Tests

```python
# Test: Full memory workflow
def test_e2e_memory_workflow():
    # Phase 1: Run task with seeded memory
    # Verify agent uses seeds
    
    # Phase 2: Verify memory persisted to .eval
    
    # Phase 3: Run new task loading historical memory
    # Verify historical memory available
    
    # Phase 4: Run cross-domain task
    # Verify cross-domain memory works
    pass
```

### 13.4 Performance Tests

| Test | Target | Measurement |
|------|--------|-------------|
| Seed loading (10 files) | < 50ms | Time to initialize memory |
| Seed loading (100 files) | < 200ms | Time to initialize memory |
| Historical memory loading | < 1s | Time to load from 5 .eval files |
| Memory write operation | < 10ms | Per-operation latency |
| Memory read operation | < 5ms | Per-operation latency |
| .eval with memory | < 10% size increase | Storage overhead |

### 13.5 Behavioral Tests

```python
# Test: Agent actually uses memory
def test_agent_memory_utilization():
    # Run task with useful seeds
    # Measure: Did agent read seeds?
    # Measure: Did agent write findings?
    # Compare: Score with vs without memory
    pass
```

## 14. Success Metrics

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target | Phase 4 Target |
|--------|----------------|----------------|----------------|----------------|
| Memory integration latency | < 100ms | < 150ms | < 300ms | < 500ms |
| Seed file load time | < 50ms | < 50ms | N/A | N/A |
| Historical memory load time | N/A | N/A | < 1s | < 2s |
| Agent memory utilization rate | > 30% | > 50% | > 70% | > 80% |
| Memory read ops per episode | > 2 | > 3 | > 5 | > 5 |
| Memory write ops per episode | > 1 | > 2 | > 3 | > 3 |
| Cross-run score improvement | N/A | N/A | > 5% | > 10% |
| Cross-domain score improvement | N/A | N/A | N/A | > 5% |

## 15. Open Questions

### Inspect AI Integration Questions
1. **Memory tool API:** What exact operations does `inspect_ai.tool.memory()` support?
2. **Memory state access:** Can we programmatically access memory state after episode?
3. **Memory hooks:** Can we intercept memory operations for logging?
4. **Custom memory backends:** Does Inspect AI support custom memory implementations?
5. **Memory tool limitations:** Are there known limitations or gotchas?

### Implementation Questions
6. **Memory versioning:** How to version memory schemas across SABER versions?
7. **Memory compression:** Should large memories be compressed in .eval files?
8. **Memory TTL:** Should historical memories expire after a certain time?
9. **Memory conflicts:** How to handle conflicting memories from different runs?
10. **Memory debugging:** How to debug memory-related agent behavior issues?
11. **Memory rollback:** Should we support undoing memory writes?
12. **Memory diff:** Should we track what changed in memory during episode?

### Operational Questions
13. **Memory metrics:** What telemetry should we collect on memory usage?
14. **Memory quotas:** Should there be per-domain or per-user memory quotas?
15. **Memory backup:** Should memories be backed up separately from .eval files?
16. **Memory migration:** How to migrate memories when schema changes?
17. **Memory cleanup:** How to garbage collect old historical memories?
18. **Memory CLI:** Should we provide CLI tools for memory management?

### Architecture Questions
19. **Memory vs transcript:** How does memory relate to SABER's transcript system?
20. **Memory vs checkpoints:** Should checkpoints have access to memory state?
21. **Memory ownership:** Who owns memory - framework, domain, or agent?
22. **Memory extension points:** How can domains extend memory behavior?
23. **Memory in multi-task runs:** How does memory work across tasks in single run?

### Research Questions
24. **Memory effectiveness:** How to measure if memory actually helps agents?
25. **Memory content:** What types of content are most useful to seed?
26. **Memory format:** Is markdown the best format for memory content?
27. **Memory retrieval:** Should we support semantic search within memories?
28. **Memory learning:** Can we automatically learn what to put in seeds?
29. **Memory ablation:** How much does each memory type contribute?

## 16. Timeline

| Phase | Description | Duration | Target Completion |
|-------|-------------|----------|-------------------|
| Phase 1 | Static seeded memory | 2 weeks | TBD |
| Phase 2 | Episode persistence | 2 weeks | TBD |
| Phase 3 | Run persistence | 3 weeks | TBD |
| Phase 4 | Cross-domain transfer | 3 weeks | TBD |

## 17. Decision Summary

| ID | Decision Topic | Choice | Date | Notes |
|----|----------------|--------|------|-------|
| DD-1 | Tool Integration Approach | **Option C: Hybrid** | 2026-01-24 | Base resolver in Phase 1, custom extensions in Phase 2 |
| DD-2 | Memory Storage Location | **Option A: Server Config** | 2026-01-24 | Seeds in `server/config/seeds/`, config in YAML |
| DD-3 | Memory Path Namespace | **Option B: Hierarchical by Type** | 2026-01-24 | `/memories/seeds/`, `/memories/runtime/`, `/memories/historical/` |
| DD-4 | Historical Memory Extraction | **Modular Memory Types** | ✅ | Use Inspect Log API with 6 configurable memory types |
| DD-5 | ~~Cross-Domain Memory Format~~ | **REMOVED** | ✅ | Redundant - uses same format as DD-4, filtering in DD-7 |
| DD-6 | Memory Size Management | **Option A: Hard Limits** | ✅ | 100KB per path, 1MB total, truncate_oldest |
| DD-7 | Memory Relevance Scoring | **Configurable Strategy** | ✅ | recent (default), successful, or explicit eval specification |
| DD-8 | Agent Prompt Integration | **Option B (Simplified)** | ✅ | Mention memory tool exists, agent uses memory_list() to discover |
| DD-9 | Multi-Agent Memory Sharing | **Option A (Isolated)** | ✅ | Single-agent only, no sharing needed. Revisit if multi-agent added |
| DD-10 | Sensitive Data Handling | **Option A (No Filtering)** | ✅ | Benchmark framework with synthetic data, local-only access in Phase 1 |
| DD-11 | Memory Initialization Timing | **Option A (Eager Loading)** | ✅ | Load all memory at task start, simple and predictable |
| DD-12 | Memory vs Context Trade-off | **Option A (Memory-First)** | ✅ | All knowledge in memory, agent reads as needed |
| DD-13 | Checkpoint Integration | **Option A (Memory Ignored)** | ✅ | Memory access decoupled from evaluation |
| DD-14 | Eval Reproducibility | **Option A (No Guarantee)** | ✅ | User's responsibility; use explicit strategy for reproducibility |
| DD-15 | Memory Content Validation | **Option A (No Validation)** | ✅ | Agent's scratchpad, no constraints on content |

## 18. References

- [Inspect AI Memory Tool Documentation](https://inspect.ai-safety-institute.org.uk/tools.html#memory)
- [SABER Framework Architecture](../architecture.md)
- [Excytin Domain Documentation](../../domains/excytin/README.md)
- [Inspect AI Tools Overview](https://inspect.ai-safety-institute.org.uk/tools.html)

## 19. Glossary

| Term | Definition |
|------|------------|
| **Seed** | Pre-defined memory content loaded at agent initialization |
| **Episode** | A single agent run on a task (start to submit) |
| **Run** | A collection of episodes across tasks in a benchmark |
| **Historical Memory** | Memories extracted from previous .eval files |
| **Cross-Domain Memory** | Memories transferred between different SABER domains |
| **Memory Path** | Virtual file path for memory content (e.g., `/memories/notes.md`) |
| **Memory Resolver** | Component that loads and initializes memory for agents |

## 20. Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-24 | Initial | Created design document with 10 design decisions |
| 2026-01-24 | Review | Added DD-11 through DD-15 (initialization timing, context trade-off, checkpoint integration, reproducibility, validation) |
| 2026-01-24 | Review | Added Dependencies & Prerequisites section |
| 2026-01-24 | Review | Added Risks & Concerns section |
| 2026-01-24 | Review | Added Testing Strategy section |
| 2026-01-24 | Review | Expanded Open Questions (29 total across 5 categories) |
| 2026-01-24 | Review | Added Glossary section |
| 2026-01-24 | DD-1 | Decided: Option C (Hybrid) - Base resolver Phase 1, custom extensions Phase 2 |
| 2026-01-24 | DD-2 | Decided: Option A (Server Config) - Seeds in `server/config/seeds/` |
| 2026-01-24 | DD-3 | Decided: Option B (Hierarchical by Type) - `/memories/seeds/`, `/memories/runtime/`, `/memories/historical/` |
| 2026-01-24 | DD-4 | Decided: Modular Memory Types - 6 configurable extraction types using Inspect AI Log API |
| 2026-01-24 | DD-4 | Documented complete Inspect AI Log API reference with examples |
| 2026-01-24 | Phases | Updated Phase 1 to include historical memory extraction (moved from Phase 3) |
| 2026-01-24 | Deps | Added Inspect AI Log API verification table (all confirmed) |
| 2026-01-24 | DD-5 | REMOVED: Redundant - cross-domain uses same format as DD-4, filtering moved to DD-7 |
| 2026-01-24 | DD-7 | Enhanced with cross-domain considerations and filtering strategy |
| 2026-01-24 | DD-6 | Decided: Option A (Hard Limits) - 100KB per path, 1MB total, truncate_oldest |
| 2026-01-24 | DD-7 | Decided: Configurable strategy - recent (default), successful, or explicit eval specification |
| 2026-01-24 | DD-8 | Decided: Option B (Simplified) - Mention memory tool in prompt, agent discovers paths via memory_list() |
| 2026-01-24 | DD-9 | Decided: Option A (Isolated) - Single-agent only, no multi-agent sharing needed |
| 2026-01-24 | DD-10 | Decided: Option A (No Filtering) - Synthetic data, local-only access in Phase 1 |
| 2026-01-30 | DD-11 | Decided: Option A (Eager Loading) - Load all memory at task start |
| 2026-01-30 | DD-12 | Decided: Option A (Memory-First) - All knowledge in memory, agent reads as needed |
| 2026-01-30 | DD-13 | Decided: Option A (Memory Ignored) - Memory access decoupled from checkpoint evaluation |
| 2026-01-30 | DD-14 | Decided: Option A (No Guarantee) - Reproducibility is user's responsibility, use explicit strategy |
| 2026-01-30 | DD-15 | Decided: Option A (No Validation) - Agent's scratchpad, no content constraints |
| 2026-01-30 | Impl | Phase 1 Implementation Complete - Core memory module created |
| 2026-01-30 | Impl | Created: `saber/inspect_ai/memory/config.py` - MemoryConfig dataclass |
| 2026-01-30 | Impl | Created: `saber/inspect_ai/memory/extractor.py` - MemoryExtractor for .eval files |
| 2026-01-30 | Impl | Created: `saber/inspect_ai/memory/selector.py` - MemorySelector with 3 strategies |
| 2026-01-30 | Impl | Created: `saber/inspect_ai/memory/resolver.py` - MemoryResolver (main entry point) |
| 2026-01-30 | Impl | Updated: `solver_factory.py` - Added memory_config loading from domain.yaml |
| 2026-01-30 | Impl | Updated: `react.py` - Added memory tool integration to agent |
| 2026-01-30 | Impl | Added: `domains/excytin/domain.yaml` - memory_config section example |
| 2026-01-30 | Impl | Created: `domains/excytin/server/config/seeds/` - Example seed files |