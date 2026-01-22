# CTI Detection Task Files

This directory contains YAML task definitions for the CTI Realm domain evaluation.

## Files

### `shared.yaml`
Shared configuration inherited by all tasks in this directory:
- Sandbox environment: `cti_realm_sandbox`
- Kusto connection details
- MITRE ATT&CK service endpoints

### `cti_trajectory_example.yaml`
Single example task (`linux_002`) demonstrating the full task structure with all 5 checkpoints (C0-C4).

### `cti_stratified.yaml` ✨ NEW
**25 tasks** - Stratified sample across platforms for faster evaluation:
- **15 Linux tasks**: Process-based detections, credential access, persistence
- **6 Kubernetes (AKS) tasks**: RBAC abuse, secret access, ServiceAccount manipulation
- **4 Cloud (Azure) tasks**: Administrative Units, VM provisioning, Key Vault chains, service principal escalation

Use for: Quick validation runs, CI/CD testing, development

**Command:**
```bash
inspect eval domains/cti_realm --model openai/azure/gpt-5.1
```

### `cti_full.yaml` ✨ NEW
**102 tasks** - Complete dataset across all platforms:
- **70 Linux tasks**: Comprehensive Linux threat detection scenarios
- **20 Kubernetes (AKS) tasks**: Full Kubernetes attack surface
- **12 Cloud (Azure) tasks**: Complete cloud kill chain scenarios

Use for: Full benchmark evaluation, leaderboard submissions, comprehensive testing

**Command:**
```bash
inspect eval domains/cti_realm --model openai/azure/gpt-5.1
```

## Task Structure

Each task follows the 5-checkpoint CTI evaluation system:

### Submission Evaluation
- **Strategy**: `trajectory_analysis` - Analyzes final submission against detection objectives
- **Scoring**: 10.0 points maximum

### Subtask Checkpoints (C0-C4)

1. **C0: CTI Report Usage** (1.25 points)
   - Strategy: `cti_tool_llm` - LLM judges CTI report usage in trajectory
   - Validates threat intelligence analysis

2. **C1: Threat Context - MITRE Techniques** (0.75 points)
   - Strategy: `trajectory_jaccard` - Jaccard similarity on MITRE technique IDs
   - Measures coverage of expected techniques (T1059, T1546, etc.)

3. **C2: Data Exploration - Data Sources** (1.0 point)
   - Strategy: `tool_call_jaccard` - Jaccard similarity on data source access
   - Validates exploration of expected tables (DeviceProcessEvents, AKSAudit, etc.)

4. **C3: Query Execution** (0.5 points)
   - Strategy: `tool_call_count` - Counts KQL query executions
   - Rewards iterative query development (min 2 executions)

5. **C4: Detection Quality** (6.5 points)
   - Strategy: `f1_sigma_scoring` - F1 score for KQL + LLM judge for Sigma rules
   - **KQL F1 Score (5.0 weighted)**: Validates query results against `regex_patterns`
   - **Sigma Quality (1.5 weighted)**: LLM evaluates Sigma rule syntax and specificity

### Ground Truth Encoding

Ground truth is embedded in YAML via:
- `expected_techniques`: List of MITRE ATT&CK technique IDs
- `expected_data_sources`: List of expected log tables
- `regex_patterns`: Field-level patterns for KQL result validation

Example:
```yaml
regex_patterns:
  initiatingprocessfilename: ^(apt|apt-get|bash)$
  initiatingprocesscommandline: .*Pre-Invoke.*
  filename: ^(python3|python)$
  processcommandline: .*f8e2a4c6-7d9b-4f3e-8a1c-5e7f9d2b4c8a-T2.*
```

The F1 scorer validates that agent's KQL query returns rows matching these patterns.

## Generation

Tasks generated from:
- `data/data/dataset_samples_stratified.jsonl` → `cti_stratified.yaml`
- `data/data/dataset_samples.jsonl` → `cti_full.yaml`
- `data/data/dataset_answers_stratified.jsonl` (detection descriptions)
- `data/data/dataset_answers.jsonl` (detection descriptions)

Each sample JSONL entry contains:
- `id`: Task identifier (linux_001, aks_001, cloud_002, etc.)
- `ground_truth.mitre_techniques`: Expected MITRE ATT&CK techniques
- `ground_truth.data_sources`: Expected log sources
- `ground_truth.regex_patterns`: KQL result validation patterns

## Task Filtering

Filter tasks using glob patterns:
```bash
# Run only Linux tasks
inspect eval domains/cti_realm -T task_filter="linux_*" --model openai/azure/gpt-5.1

# Run only Kubernetes tasks
inspect eval domains/cti_realm -T task_filter="aks_*" --model openai/azure/gpt-5.1

# Run only Cloud tasks
inspect eval domains/cti_realm -T task_filter="cloud_*" --model openai/azure/gpt-5.1

# Run specific task
inspect eval domains/cti_realm -T task_filter="linux_002" --model openai/azure/gpt-5.1
```

## Scoring Summary

| Checkpoint | Strategy | Max Score | Weight | Description |
|-----------|----------|-----------|--------|-------------|
| Submission | trajectory_analysis | 10.0 | N/A | Overall submission quality |
| C0 | cti_tool_llm | 1.25 | 1.0 | CTI report usage |
| C1 | trajectory_jaccard | 0.75 | 1.0 | MITRE technique coverage |
| C2 | tool_call_jaccard | 1.0 | 1.0 | Data source exploration |
| C3 | tool_call_count | 0.5 | 1.0 | Iterative query development |
| C4 | f1_sigma_scoring | 6.5 | 1.0 | Detection rule quality (F1 + Sigma) |

**Total**: 20.0 points maximum (10.0 submission + 10.0 weighted subtasks)

Normalized to 1.0 for Inspect AI reporting.
