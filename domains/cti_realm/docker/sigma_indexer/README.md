# Sigma Rules Indexer

Pre-downloads Sigma detection rules from the [SigmaHQ repository](https://github.com/SigmaHQ/sigma) for fast searching during evaluation.

## Purpose

Helps the agent avoid recreating existing Sigma detection rules by providing a searchable database of existing rules.

## Categories Indexed

- `linux/process_creation` - Linux process creation detection rules (120 rules)
- `cloud/azure/activity_logs` - Azure activity log detection rules (42 rules)

## How It Works

1. **Pre-download** (one-time): Run `build_index.py` to fetch all `.yml` rule files from specified categories
2. **Parsing**: Extracts key metadata from each YAML rule:
   - Title and description
   - MITRE ATT&CK techniques (extracted from tags using regex `attack\.(t\d{4}(?:\.\d{3})?)`)
   - Platform (from logsource.product/service)
   - Detection logic snippet (first 200 chars)
   - Source URL for reference
3. **Storage**: Saves all rules to `../data/sigma_rules.json` (162 rules, ~110KB)

## Updating Rules

To refresh the Sigma rules index:

```bash
cd src/inspect_evals/cti_realm
python -c "
import sys
sys.path.insert(0, 'docker/sigma_indexer')
from build_index import build_index
from pathlib import Path
build_index(Path('data/sigma_rules.json'))
"
```

The pre-downloaded index is included in the repository, so no runtime download is needed.

## Search Tool

The agent can search the index using the `search_sigma_rules()` tool with parameters:

- `keyword`: Search in title/description (case-insensitive)
- `technique_id`: Filter by MITRE technique (e.g., "T1053", "T1053.003")
- `platform`: Filter by platform (e.g., "linux", "azure")
- `limit`: Max results (default 5, max 20)

Example searches:
```python
search_sigma_rules(keyword="cron", platform="linux")
search_sigma_rules(technique_id="T1053.003")
search_sigma_rules(platform="azure", limit=10)
```

## Output Format

Each rule in the index contains:
```json
{
  "title": "Rule Title",
  "description": "What the rule detects",
  "techniques": ["T1234.567"],
  "platform": "linux",
  "logsource": {"product": "linux", "category": "process_creation"},
  "detection_snippet": "CommandLine|contains: ...",
  "path": "linux/process_creation/rule.yml",
  "url": "https://github.com/SigmaHQ/sigma/blob/master/rules/..."
}
```

## Dependencies

- `requests>=2.31.0` - GitHub API calls
- `pyyaml>=6.0` - YAML rule parsing
