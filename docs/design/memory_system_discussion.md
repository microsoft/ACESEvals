# SABER Memory System — Team Discussion Doc

> Distilled from the full design doc ([memory_system.md](memory_system.md)). Covers resolved decisions and implementation plan.

## 1. Overview

The SABER Memory System gives agents persistent, queryable memory spanning individual episodes, domain runs, and cross-domain evaluations. Agents can leverage pre-seeded domain knowledge, learn from previous `.eval` files, and transfer insights across domains.

**Key constraint:** Episode persistence (memory across steps within a single run) is already handled by Inspect AI's built-in `memory()` tool — we build on top of it, not replace it.

## 2. Design Goals

| | Goal | Description |
|-|------|-------------|
| ✅ | **Seeded Memory** | Pre-populate agent memory with domain knowledge (threat intel, query patterns) |
| ✅ | **Cross-Run Learning** | Load insights from previous `.eval` files (historical memory) |
| ✅ | **Cross-Domain Transfer** | Enable knowledge transfer between domains |
| ❌ | Real-time multi-agent sync | Not planned |
| ❌ | Auto-consolidation/summarization | Not in Phase 1 |
| ❌ | Memory access control | Not needed for benchmarking |

## 3. Design Decisions

| ID | Topic | Decision | Rationale | Alternatives Rejected & Why |
|----|-------|----------|-----------|----------------------------|
| DD-1 | Tool Integration | **Hybrid** — framework base + domain extensions | Standardization matters, but domains need flexibility | Domain-only (A) — duplicates code. Framework-only (B) — too rigid for domain-specific needs. |
| DD-2 | Storage Location | **Server Config** (`server/config/seeds/`) | Seeds are like prompts — co-locate with task definitions | Client dir (B) — disconnects from task config. Dedicated dir (C) — new structure with no clear upside. |
| DD-3 | Path Namespace | **Hierarchical by Type** (`seeds/`, `runtime/`, `historical/`) | Descriptive structure agents can navigate | Flat (A) — no organization for scaling. Task-scoped (C) — agent needs task context it may not have. |
| DD-4 | Historical Extraction | **Modular Memory Types** via Inspect Log API | 6 configurable types; no custom parser needed | N/A — all extraction modes supported as configurable types |
| DD-6 | Size Management | **Hard Limits** (100KB/path, 1MB total) | Simple, predictable; upgrade later if needed | Token-based (B) — model-specific, adds overhead. LLM summarization (C) — adds cost/latency. |
| DD-7 | Relevance Scoring | **Configurable** — recent / successful / explicit | User picks strategy via YAML; `explicit` enables reproducibility | Fixed recency-only (A) — loses valuable old memories. Success-only (C) — overfits. Full hybrid (D) — over-engineered for Phase 1. |
| DD-8 | Prompt Integration | **Simplified mention** — agent discovers via `memory_list()` | Minimal prompt overhead; agent explores on its own | Implicit/no mention (A) — agents underutilize memory. Full injection (C) — wastes context window. |
| DD-9 | Multi-Agent Sharing | **Isolated** (single-agent only) | SABER is single-agent; revisit if multi-agent added | Shared namespace (B) — race conditions. Pub/sub (C) — complex. Shared+personal (D) — unnecessary. |
| DD-10 | Sensitive Data | **No Filtering** | Synthetic benchmark data; no real PII | Pattern redaction (B) — maintenance burden. LLM sanitization (C) — cost/latency. Category-based (D) — requires agent categorization. |
| DD-11 | Init Timing | **Eager Loading** at task start | Small data sizes; Inspect API expects data upfront | Lazy (B) — first-access latency, harder to debug. Background async (C) — race condition risk. |
| DD-12 | Memory vs Context | **Memory-First** — all knowledge in memory tool | Single source of truth; scales; no prompt templating | Context-first (B) — doesn't scale. Tiered (C) — duplicates info, hard to decide what's "critical." |
| DD-13 | Checkpoint Integration | **Decoupled** — memory ignored by checkpoints | Evaluate outcomes, not note-taking behavior | Memory as evidence (B) — biases scoring. Memory-based checkpoints (C) — prescriptive, encourages gaming. |
| DD-14 | Reproducibility | **No guarantee** — user's responsibility | Use `strategy: explicit` for reproducible runs | Snapshots (B) — storage overhead, alters .eval format. Versioned sets (C) — version management overhead. |
| DD-15 | Content Validation | **None** — agent's scratchpad | No constraints; we don't parse memory programmatically | Format validation (B) — overhead per write. Schema validation (C) — maintenance. Post-episode (D) — late detection. |

> **DD-5 (Cross-Domain Format)** was removed as redundant — DD-4's format is already domain-agnostic.

## 4. Memory Types

### Path Structure (DD-3)

```
/memories/
├── seeds/              ← Pre-loaded domain knowledge (read-mostly)
│   ├── threat_intel.md
│   └── query_patterns.md
├── runtime/            ← Agent workspace (read-write)
│   ├── notes.md
│   └── findings.md
└── historical/         ← From previous runs (Phase 3+)
    └── previous_findings.md
```

### Historical Memory Types (DD-4)

Extracted from `.eval` files using the Inspect AI Log API (`read_eval_log()`):

| Type | What It Captures | Size | Best For |
|------|-----------------|------|----------|
| `final_state` | Final memory paths at episode end | Small | Quick context loading |
| `operations` | All tool calls with results | Medium | Pattern analysis |
| `checkpoints` | State at checkpoint completions | Medium | Milestone tracking |
| `errors` | Failed operations + resolutions | Small | Error avoidance |
| `trajectory` | Full agent trajectory with thoughts | Large | Debugging / replay |
| `insights` | LLM-summarized learnings | Small | Cross-task transfer (requires LLM) |

Configured per-domain in YAML:

```yaml
memory_config:
  historical:
    enabled: true
    extraction_types: [final_state, operations, checkpoints, errors]
    strategy: recent          # or "successful" or "explicit"
    recent:
      max_evals: 5
      max_age_days: 30
    filters:
      min_score: 0.0
      same_domain_only: false
```

### Seed Configuration

```yaml
memory_config:
  enabled: true
  seeds:
    global:
      - path: "/memories/seeds/threat_intel.md"
        source: "seeds/threat_intelligence.md"    # file reference
      - path: "/memories/runtime/notes.md"
        content: ""                                # inline empty
    task: []   # per-task overrides
  limits:
    max_size_per_path: 100KB
    max_total_size: 1MB
    behavior_on_limit: truncate_oldest
```

### File Layout

```
domains/excytin/server/config/
├── prompts/instructions/
├── seeds/                      ← Memory seeds
│   ├── global/
│   │   ├── threat_intel.md
│   │   └── query_patterns.md
│   └── tasks/                  ← Optional task-specific seeds
│       └── incident_5/
│           └── context.md
└── tasks/
    ├── global.yaml             ← memory_config lives here
    └── incident_5/
```

## 5. Implementation

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  SABER Memory System                     │
│                                                          │
│  Static Seeds ──► Episode Memory ──► Persistent Store    │
│       │             (Runtime)          (.eval files)      │
│       ▼                ▼                    ▼             │
│  ┌────────────────────────────────────────────────┐      │
│  │            Memory Resolver                     │      │
│  │  • Loads seeds from config/files               │      │
│  │  • Hydrates from .eval logs                    │      │
│  │  • Provides to inspect_ai.tool.memory()        │      │
│  └────────────────────────────────────────────────┘      │
│                         │                                │
│                         ▼                                │
│           Inspect AI Memory Tool (agent interface)       │
└──────────────────────────────────────────────────────────┘
```

### Planned Components

| Module | Purpose |
|--------|---------|
| `saber/inspect_ai/memory/config.py` | `MemoryConfig` dataclass |
| `saber/inspect_ai/memory/resolver.py` | Main entry point — loads seeds + historical, returns `memory()` tool |
| `saber/inspect_ai/memory/extractor.py` | Extracts memories from `.eval` files by type |
| `saber/inspect_ai/memory/selector.py` | Selects which `.eval` files to load (recent / successful / explicit) |

The resolver will integrate into the existing tool pipeline:

```python
# tool_resolver.py
if config.memory_config and config.memory_config.enabled:
    memory_tool = MemoryResolver(config).resolve()
    tools.append(memory_tool)
```

Agent prompt addition (per DD-8):

```
MEMORY SYSTEM:
You have access to a persistent memory tool with a hierarchical directory structure.
Use memory_list() to see available paths, memory_read(path) to read content,
and memory_write(path, content) to store findings. Pre-seeded knowledge and
historical learnings may be available — check memory_list() at the start.
```

### Phased Rollout

| Phase | Scope | Status |
|-------|-------|--------|
| **1** | Seeds + historical extraction + modular types | In Design |
| **2** | Auto-extraction on eval completion, lifecycle hooks | Planned |
| **3** | Intelligent selection, deduplication, size optimization | Planned |
| **4** | Cross-domain transfer, LLM-based `insights` type | Planned |

### Backward Compatibility

Memory is opt-in. Domains without `memory_config` continue to work unchanged:

```python
if config.memory_config and config.memory_config.enabled:
    tools.append(memory_tool)
```

### Key Risks

| Risk | Mitigation |
|------|-----------|
| Inspect AI memory API changes | Pin versions, abstract behind wrapper |
| Memory size → OOM | Hard limits (DD-6): 100KB/path, 1MB total |
| Agent over-reliance on memory | Measure with/without; memory decoupled from scoring (DD-13) |
| Reproducibility across runs | `strategy: explicit` with fixed eval files (DD-14) |
| Fair benchmarking comparisons | Disclose memory config; provide no-memory baseline |

### Open Discussion Points

1. **Memory vs Transcript:** How does memory relate to SABER's existing transcript system? Should they share infrastructure?
2. **Memory effectiveness:** How do we measure whether memory actually improves agent scores? Ablation study design?
3. **Seed content curation:** What types of content are most useful to seed? Who maintains seed files?
4. **Cross-domain viability:** Which memory types actually transfer well between domains?
5. **Phase 2 triggers:** When do we start auto-extraction? What's the priority vs other work?
