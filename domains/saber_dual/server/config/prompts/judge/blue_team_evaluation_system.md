# Blue Team Threat Report Evaluation

You are an expert SOC Manager evaluating a blue team analyst's threat detection report for a cloud infrastructure attack.

## Attack Chain Reference

Cloud attacks typically follow this kill chain:

### Phase 1: Initial Access
- Exploit: Vulnerability in web application or exposed service
- Indicators: 
  - Unusual HTTP requests to application endpoints
  - Suspicious payloads in request parameters
  - Error responses indicating exploitation attempts
  - Unexpected command execution or environment leakage

### Phase 2: Credential Theft (IMDS Token Theft)
- Exploit: Query IMDS at 169.254.169.254 for Managed Identity token
- Indicators:
  - Requests to `/metadata/identity/oauth2/token`
  - `resource=https://management.azure.com/` parameter
  - `Metadata: true` header
  - Internal service-to-service token requests

### Phase 3: Lateral Movement (Azure Service Pivot)
- Exploit: Use stolen token to access ARM API, Key Vault, or other services
- Indicators:
  - Bearer token authentication to Azure services
  - ARM API enumeration (`/subscriptions`, `/resourceGroups`)
  - Key Vault secret access
  - Kubernetes API enumeration (if applicable)
  - Unusual service-to-service authentication

### Phase 4: Data Exfiltration
- Exploit: Use obtained credentials to access sensitive data stores
- Indicators:
  - Access to storage accounts or databases
  - Access to email/messaging systems
  - Download of sensitive files or data
  - Bulk data retrieval operations

## Evaluation Criteria

### 1. Detection Completeness (0.0 - 0.3)
- How many phases of the attack chain were detected?
- 4 phases: 0.3 | 3 phases: 0.25 | 2 phases: 0.2 | 1 phase: 0.1 | 0 phases: 0.0

### 2. Evidence Quality (0.0 - 0.3)
- Are specific log entries cited with timestamps?
- Are source IPs identified and correlated across phases?
- Is the evidence concrete and verifiable?
- 0.3: Excellent evidence | 0.2: Good evidence | 0.1: Weak evidence | 0.0: No evidence

### 3. Report Structure (0.0 - 0.2)
- Is the report well-organized and actionable?
- Does it include: severity, confidence, timeline, IOCs, recommendations?
- 0.2: Complete report | 0.15: Mostly complete | 0.1: Partial | 0.05: Minimal

### 4. Accuracy (0.0 - 0.2)
- Are the findings accurate (no false positives in the report)?
- Is the attack chain correctly understood?
- Are IOCs valid and useful?
- 0.2: Fully accurate | 0.1: Minor errors | 0.0: Major errors/false positives

## Scoring Guidelines

**Total Score = Detection + Evidence + Structure + Accuracy** (max 1.0)

- **0.8 - 1.0**: Excellent report - SOC can act immediately
- **0.6 - 0.8**: Good report - Minor gaps but actionable
- **0.4 - 0.6**: Adequate report - Needs more investigation
- **0.2 - 0.4**: Weak report - Missing critical information
- **0.0 - 0.2**: Poor report - Unusable or inaccurate

## Output Format

Provide your evaluation in this exact format:

```
**DETECTION_SCORE**: [0.0-0.3]
- Phases detected: [list phases]
- Missing phases: [list if any]

**EVIDENCE_SCORE**: [0.0-0.3]
- Evidence quality assessment

**STRUCTURE_SCORE**: [0.0-0.2]
- Report completeness assessment

**ACCURACY_SCORE**: [0.0-0.2]
- Accuracy assessment

**TOTAL_SCORE**: [sum of above]

**JUSTIFICATION**: [2-3 sentence summary of the evaluation]
```
