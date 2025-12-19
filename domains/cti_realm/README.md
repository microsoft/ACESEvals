# CTI Realm - Cyber Threat Intelligence Domain

**Cyber threat intelligence analysis and detection rule development benchmark**

## Overview

The CTI Realm domain simulates real-world cyber threat intelligence analysis scenarios where agents must:

- Analyze threat intelligence reports to understand attack patterns
- Map threats to MITRE ATT&CK framework techniques  
- Explore security telemetry data using KQL (Kusto Query Language)
- Develop detection rules in Sigma format
- Test detection capabilities against real security data

The domain uses a **dual-environment architecture**:
- **Sandbox environment**: Python-based execution environment with CTI tools
- **Permanent services**: Persistent Kusto database with security telemetry and MITRE ATT&CK API

## Key Components

### Domain Structure

```
cti_realm/
├── domain.yaml              # Domain configuration and metadata
├── client/
│   └── saber.yaml          # Client evaluation configuration
├── server/
│   ├── config/             # Task definitions and prompt templates
│   ├── data/               # Core modules, datasets, and reports
│   ├── docker/             # Container definitions and build scripts
│   └── logs/               # Runtime logs
└── README.md               # This file
```

### Key Features

- **Comprehensive CTI Workflow**: 5-step pipeline from report analysis to detection deployment
- **Real Security Data**: 12+ telemetry data sources with 50K+ security events
- **MITRE ATT&CK Integration**: Native API integration for technique mapping
- **Sigma Rule Development**: Industry-standard detection rule format
- **Kusto Database**: Production-like query environment with security schema

## Setup

### Download Data from Azure

Before running the evaluation, download the required data files:

```bash
# Navigate to the data directory
cd /root/SABER/domains/cti_realm/server/data

# Download with default configuration
python download_data.py
```

**Files Downloaded:**

1. **Dataset Files** (to `server/data/`):
   - `dataset_samples.jsonl` - Detection objectives and sample metadata
   - `dataset_answers.jsonl` - Ground truth answers and scoring data

2. **Kusto Telemetry Data** (to `server/data/kusto_init/data/`):
   - Security event logs from 12+ data sources including Azure AD, AKS, endpoints, and Office 365

3. **CTI Reports** (to `server/data/cti_reports/`):
   - Threat intelligence reports for analysis

**Custom Configuration:**
```bash
# Override storage location
python download_data.py --storage-account custom-account --container custom-container

# Use custom directory paths
python download_data.py --directory custom/path
```

## Overview

CTI Realm tests an AI agent's capability to:

1. **MITRE Technique Mapping** - Identify relevant ATT&CK techniques from threat intelligence
2. **Data Source Discovery** - Explore available Kusto data sources dynamically  
3. **Sigma Rule Generation** - Create properly formatted detection rules
4. **KQL Development** - Write and test queries against real data
5. **Results Analysis** - Interpret findings and answer analytical questions

## Architecture

- **Sandbox Environment**: Docker container with Kusto access and security tools
- **Dynamic Port Management**: Automatic port allocation to support concurrent evaluations
- **MITRE ATT&CK Integration**: Live API service for technique research and mapping
- **Dynamic Data Discovery**: Agents explore unknown data sources using tools
- **Iterative Development**: Query building through incremental testing and validation
- **Advanced Scoring**: LLM-as-judge with F1-score metrics for comprehensive evaluation

## Key Features

- **Realistic Workflow**: Mirrors actual CTI analyst processes
- **Real Kusto Integration**: Local Kusto server with actual KQL queries ✨
- **Tool-Based Exploration**: Dynamic discovery rather than static knowledge
- **Security Isolation**: Sandboxed environment with controlled access
- **Practical Skills**: Real-world detection rule development

## Kusto Integration

The benchmark includes a lightweight Kusto-compatible server that provides realistic KQL functionality:

### **Security Data Tables**
- `AzureActivity`: Azure resource management and administrative operations
- `AuditLogs`: Azure AD audit logs for identity and access events
- `SigninLogs`: User authentication and sign-in events
- `AADServicePrincipalSignInLogs`: Service principal authentication logs
- `DeviceProcessEvents`: Process creation with command lines and parent processes
- `DeviceFileEvents`: File creation, modification, and access events
- `AKSAudit`: Azure Kubernetes Service audit logs
- `AKSAuditAdmin`: AKS administrative operations
- `OfficeActivity`: Office 365 user and admin activity
- `MicrosoftGraphActivityLogs`: Microsoft Graph API usage logs
- `AzureDiagnostics`: Azure resource diagnostic logs
- `StorageBlobLogs`: Azure Storage blob access logs

### **Real KQL Tools**
- `list_kusto_tables()`: Discover available data sources
- `get_table_schema()`: Examine table structures and column types
- `sample_table_rows()`: Preview data samples
- `test_kql_snippet()`: Test queries safely with limits
- `execute_kql_with_limit()`: Run production queries with safeguards

### **Sample Threat Data**
Pre-loaded with realistic security scenarios covering:
- Cloud infrastructure attacks and misconfigurations
- Azure AD identity compromise and privilege escalation
- Kubernetes security events and container threats
- Cross-platform endpoint detection scenarios

## Usage

The CTI Realm benchmark offers multiple task variants to test different aspects of AI agent capability:

### Task Variants

#### **Difficulty Levels**

Three difficulty levels control the amount of guidance provided to the agent:

1. **Easy (Default)** - Full guidance with explicit instructions
   - Complete tool catalog with descriptions
   - Step-by-step workflow guidance
   - Critical rules and best practices spelled out
   - Recommended for baseline capability assessment

2. **Medium** - Minimal guidance, focus on best practices
   - Tool categories without detailed descriptions
   - High-level workflow suggestions
   - Agent must discover tool details through exploration
   - Tests adaptability and tool discovery

3. **Hard** - Minimal prompting, maximum autonomy
   - Basic mission statement only
   - No tool guidance or workflow steps
   - Agent must independently discover tools and approach
   - Tests reasoning and self-directed problem solving

#### **Dataset Sizes**

Two dataset options for different evaluation needs:

1. **Full Dataset (102 samples)** - Comprehensive evaluation
   - All threat scenarios across platforms
   - Full diversity of complexity and techniques
   - Longer evaluation time (~3-4 hours for complete run)

2. **Stratified Sample (25 samples)** - Quick balanced testing
   - Representative subset maintaining platform distribution
   - 60% Linux (15 samples), 24% AKS (6 samples), 16% Cloud (4 samples)
   - Faster evaluation (~45-60 minutes for complete run)
   - Samples shuffled to avoid ordering bias

### Usage Examples

#### Full Dataset - All Difficulty Levels

```bash
# Easy (default) - Full guidance
inspect eval inspect_evals/cti_realm --model openai/gpt-4o --limit 5

# Medium - Minimal guidance
inspect eval inspect_evals/cti_realm_medium --model openai/gpt-4o --limit 5

# Hard - Maximum autonomy
inspect eval inspect_evals/cti_realm_hard --model openai/gpt-4o --limit 5

# Run multiple samples sequentially (recommended to avoid port conflicts)
inspect eval inspect_evals/cti_realm --model openai/gpt-4o --limit 10 --max-samples 1
```

#### Stratified Sample - All Difficulty Levels

```bash
# Easy - Full guidance, balanced sample
inspect eval inspect_evals/cti_realm_stratified --model openai/gpt-4o --limit 5

# Medium - Minimal guidance, balanced sample
inspect eval inspect_evals/cti_realm_stratified_medium --model openai/gpt-4o --limit 5

# Hard - Maximum autonomy, balanced sample
inspect eval inspect_evals/cti_realm_stratified_hard --model openai/gpt-4o --limit 5

# Run all stratified samples
inspect eval inspect_evals/cti_realm_stratified --model openai/gpt-4o --max-samples 1
```

### Advanced Configuration

```bash
# Run with custom configuration
inspect eval inspect_evals/cti_realm \
    --model openai/gpt-4o \
    --limit 2 \
    --max-samples 1 \
    --log-level info

# Use different log directory
inspect eval inspect_evals/cti_realm_medium \
    --model openai/gpt-4o \
    --log-dir custom_logs \
    --limit 5
```

### Important Notes

- **Sequential Execution**: Use `--max-samples 1` when running multiple samples to avoid Docker port conflicts
- **Docker Required**: Ensure Docker is running as the benchmark uses containerized services
- **Memory Requirements**: Recommend at least 4GB available RAM for Docker containers

## Sample Scenarios

The benchmark includes diverse threat scenarios:
- **Cloud Infrastructure**: Azure resource manipulation and configuration changes
- **Identity and Access**: Azure AD compromise and authentication anomalies
- **Kubernetes Security**: AKS attacks and container escape attempts
- **Cross-Platform Threats**: Multi-stage attacks across cloud and endpoint environments

## Evaluation Metrics

### **Multi-Subtask Scoring**

The benchmark uses checkpoint-based scoring across 5 subtasks:

1. **C0 - CTI Analysis (1.25 points max)**: LLM-as-judge evaluates threat intelligence understanding and context alignment
2. **C1 - MITRE Mapping (0.75 points max)**: Jaccard similarity on technique identification (precision/recall on ATT&CK techniques)
3. **C2 - Data Discovery (1.0 points max)**: Jaccard similarity on table exploration (measures effective data source discovery)
4. **C3 - Query Execution (0.5 points max)**: Binary success on KQL query execution
5. **C4 - KQL Quality (varies)**: F1-score on query results (precision, recall, and quality bonus)

**Total Score**: Sum of all checkpoint scores (maximum varies by sample, typically 3.5-4.5 points)

**Scoring Philosophy:**
- **Jaccard Similarity (C1, C2)**: Partial credit for overlapping sets - rewards discovering relevant techniques/tables even if incomplete
- **F1-Score (C4)**: Balances precision (avoiding false positives) and recall (finding all relevant data) with quality bonuses for perfect matches
- **LLM-as-Judge (C0)**: Structured evaluation of contextual understanding and analytical reasoning

This multi-metric approach captures both technical accuracy and practical security effectiveness.

### **Difficulty Impact on Scoring**

Scoring remains consistent across all difficulty levels - only the prompt guidance changes:

**Easy Mode Prompts:**
- Complete tool catalog with detailed descriptions
- Explicit workflow steps (analyze → map → discover → query → interpret)
- Critical rules spelled out (e.g., "Never assume table names", "Always test queries")
- Example patterns and best practices included

**Medium Mode Prompts:**
- Tool categories without detailed descriptions
- High-level workflow guidance
- Agent must explore tools to understand capabilities
- Best practices mentioned but not explicitly listed

**Hard Mode Prompts:**
- Basic mission statement only
- No tool guidance beyond availability
- No workflow steps or structure
- Agent must independently discover approach and tools

This design allows comparison of model performance with varying levels of human guidance - testing both prompted capability (Easy) and autonomous reasoning (Hard).

### **Detailed Scoring Components**

Each checkpoint uses specialized metrics for accurate capability measurement:

- **CTI Analysis (C0)**: LLM-as-judge with few-shot examples evaluates threat understanding and strategic context
- **MITRE Mapping (C1)**: Jaccard similarity measures overlap between predicted and ground truth ATT&CK techniques
- **Data Discovery (C2)**: Jaccard similarity on explored tables assesses systematic data source investigation
- **Query Execution (C3)**: Binary success validates proper KQL syntax and database interaction
- **KQL Quality (C4)**: F1-score with quality bonus - balances precision (low false positives) and recall (finding all threats)

### **Advanced Scoring Features**
- **Partial Credit**: Jaccard similarity and F1-scores reward incomplete but partially correct answers
- **Quality Bonuses**: Perfect row matches in KQL results earn up to +20% bonus (5% per perfect match, max 4)
- **Weighted Metrics**: Checkpoint weights reflect real-world importance (CTI context 1.25x, data discovery 1.0x)
- **Ground Truth Validation**: Regex patterns match expected threat indicators in actual query results
- **Robust Evaluation**: Multiple scoring methods with fallback validation for edge cases

## Visualization and Analysis

Generate visualizations from evaluation logs:

```bash
# Generate PNG visualizations from recent evaluations
cd src/inspect_evals/cti_realm
python visualization.py --log-dir ../../../logs --num-files 10 --format png

# Generate interactive HTML visualizations
python visualization.py --log-dir ../../../logs --num-files 10 --format html

# Show only summary statistics (skip visualizations)
python visualization.py --log-dir ../../../logs --num-files 10 --skip-viz
```

**Available Visualizations:**
- **Performance by Model**: Bar chart comparing model scores
- **Performance by Model and Category**: Grouped bars showing performance across threat categories
- **Performance vs Cost**: Scatter plot analyzing cost efficiency
- **Performance vs Tokens**: Token usage analysis
- **Checkpoint Success Rates**: Heatmap showing progression through evaluation stages (C0-C4)
- **Component Breakdown**: F1 scores vs Sigma rule quality comparison

**Output Formats:**
- **PNG**: Static images suitable for presentations and documents (requires `playwright`)
- **HTML**: Interactive visualizations with tooltips and filters (default, no extra dependencies)

This benchmark provides a comprehensive test of AI systems' practical cybersecurity analysis capabilities in realistic operational scenarios.
